from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', hide_input_in_errors=True, env_ignore_empty=True)
    logistics_agents_enabled: bool = False
    openai_api_key: SecretStr = SecretStr('')
    logistics_agent_model: str = 'gpt-4o-mini'
    logistics_embedding_model: str = 'text-embedding-3-small'
    logistics_agent_timeout_seconds: float = Field(default=6, ge=1, le=20)
    logistics_agent_concurrency: int = Field(default=4, ge=1, le=16)
    logistics_agent_output_tokens: int = Field(default=600, ge=128, le=1200)
    logistics_agent_tokens_per_minute: int = Field(default=100000, ge=10000, le=1000000)
    logistics_agent_requests_per_minute: int = Field(default=20, ge=1, le=100)
    logistics_agent_cache_entries: int = Field(default=256, ge=16, le=2000)

    @property
    def available(self):
        return self.logistics_agents_enabled and bool(self.openai_api_key.get_secret_value().strip())
