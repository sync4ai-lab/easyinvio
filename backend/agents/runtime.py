"""No durable customer prompts, no model retries, bounded SDK runs and measured usage."""
import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from agents import Agent, Runner, RunConfig, ModelSettings, OpenAIResponsesModel
from openai import AsyncOpenAI
from fastapi import HTTPException


logger = logging.getLogger('easyinvio.agents')


class Cache:
    def __init__(self, capacity, ttl=300):
        self.capacity, self.ttl = capacity, ttl
        self.entries = OrderedDict()

    def get(self, key):
        item = self.entries.get(key)
        if not item:
            return None
        if time.monotonic() - item[0] > self.ttl:
            del self.entries[key]
            return None
        self.entries.move_to_end(key)
        return item[1]

    def put(self, key, value):
        self.entries[key] = (time.monotonic(), value)
        self.entries.move_to_end(key)
        while len(self.entries) > self.capacity:
            self.entries.popitem(last=False)


@dataclass(frozen=True)
class ModelResult:
    value: object
    input_tokens: int
    output_tokens: int
    cached_tokens: int


class AgentRuntime:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client
        if self.client is None and settings.available:
            self.client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value(), max_retries=0,
                                      timeout=settings.logistics_agent_timeout_seconds)
        self.slots = asyncio.Semaphore(settings.logistics_agent_concurrency)
        self.cache = Cache(settings.logistics_agent_cache_entries)
        self.windows = OrderedDict()
        self.usage = {'model_calls': 0, 'embedding_calls': 0, 'input_tokens': 0, 'output_tokens': 0,
                      'cached_input_tokens': 0, 'cache_hits': 0, 'failures': 0, 'deterministic_calls': 0}

    @property
    def available(self):
        return self.settings.available and self.client is not None

    def key(self, tenant, worker, data):
        digest = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
        return str(tenant), worker, self.settings.logistics_agent_model, digest

    def reserve(self, tenant, tokens):
        # Limits are per-process abuse controls, not a monetary billing guarantee.
        now = time.monotonic()
        key = str(tenant)
        window = self.windows.setdefault(key, deque())
        while window and now - window[0][0] >= 60:
            window.popleft()
        if len(window) >= self.settings.logistics_agent_requests_per_minute or sum(item[1] for item in window) + tokens > self.settings.logistics_agent_tokens_per_minute:
            raise HTTPException(429, 'AI assistance limit reached. Use the standard form or try again shortly.')
        window.append((now, tokens))
        self.windows.move_to_end(key)
        while len(self.windows) > 2000:
            self.windows.popitem(last=False)

    def record(self, worker, input_tokens, output_tokens=0, cached_tokens=0):
        self.usage['input_tokens'] += input_tokens
        self.usage['output_tokens'] += output_tokens
        self.usage['cached_input_tokens'] += cached_tokens
        logger.info('agent_usage worker=%s input_tokens=%d output_tokens=%d cached_tokens=%d',
                    worker, input_tokens, output_tokens, cached_tokens)

    async def run(self, tenant, worker, instructions, payload, output_type=None, tools=None):
        if not self.available:
            raise HTTPException(503, 'AI assistance is not configured. Standard shipping tools remain available.')
        key = self.key(tenant, worker, {'payload': payload, 'instructions': instructions})
        cached = self.cache.get(key)
        if cached is not None:
            self.usage['cache_hits'] += 1
            return ModelResult(cached.value, 0, 0, 0)
        text = json.dumps(payload, ensure_ascii=False)
        schema = output_type.model_json_schema() if output_type else {}
        tool_schema = [tool.params_json_schema for tool in tools or []]
        estimated = len((instructions + text + json.dumps(schema) + json.dumps(tool_schema)).encode()) + 2000 + self.settings.logistics_agent_output_tokens
        self.reserve(tenant, estimated)
        agent = Agent(name=worker, instructions=instructions,
            model=OpenAIResponsesModel(self.settings.logistics_agent_model, self.client),
            output_type=output_type, tools=tools or [],
            tool_use_behavior='stop_on_first_tool' if tools else 'run_llm_again',
            model_settings=ModelSettings(temperature=0, max_tokens=self.settings.logistics_agent_output_tokens,
                store=False, parallel_tool_calls=False, tool_choice='required' if tools else None))
        self.usage['model_calls'] += 1
        try:
            async with asyncio.timeout(self.settings.logistics_agent_timeout_seconds):
                async with self.slots:
                    result = await Runner.run(agent, text, max_turns=1,
                        run_config=RunConfig(tracing_disabled=True, trace_include_sensitive_data=False))
            usage = result.context_wrapper.usage
            cached_count = getattr(getattr(usage, 'input_tokens_details', None), 'cached_tokens', 0) or 0
            self.record(worker, usage.input_tokens, usage.output_tokens, cached_count)
            value = output_type.model_validate(result.final_output) if output_type else result.final_output
            answer = ModelResult(value, usage.input_tokens, usage.output_tokens, cached_count)
            self.cache.put(key, answer)
            return answer
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.usage['failures'] += 1
            logger.warning('agent_deferred worker=%s error_type=%s', worker, type(error).__name__)
            raise HTTPException(503, 'AI assistance could not complete. Use the standard form; no booking was made.') from None

    async def embed(self, tenant, texts):
        if not self.available:
            raise HTTPException(503, 'Semantic retrieval is not configured')
        self.reserve(tenant, sum(len(text.encode()) for text in texts) + 100)
        self.usage['embedding_calls'] += 1
        try:
            async with asyncio.timeout(self.settings.logistics_agent_timeout_seconds):
                async with self.slots:
                    result = await self.client.embeddings.create(model=self.settings.logistics_embedding_model,
                        input=texts, dimensions=256, encoding_format='float')
            self.record('document_embeddings', result.usage.prompt_tokens)
            import math
            rows = sorted(result.data, key=lambda row: row.index)
            if len(rows) != len(texts) or [row.index for row in rows] != list(range(len(texts))):
                raise ValueError('Embedding identities differ')
            vectors = [row.embedding for row in rows]
            if any(len(vector) != 256 or not all(math.isfinite(value) for value in vector) or not any(vector) for vector in vectors):
                raise ValueError('Invalid embedding response')
            return vectors
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.usage['failures'] += 1
            logger.warning('embedding_deferred error_type=%s', type(error).__name__)
            raise HTTPException(503, 'Semantic retrieval temporarily unavailable') from None

    async def close(self):
        if self.client is not None:
            await self.client.close()
