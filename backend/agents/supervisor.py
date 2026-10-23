"""Bounded orchestration around existing, authoritative logistics services."""
import asyncio
from fastapi import HTTPException
from backend.agents.config import AgentSettings
from backend.agents.models import Workflow, State
from backend.agents.runtime import AgentRuntime
from backend.agents.workers import (IngestionWorkerAgent, CustomsHarmonizerAgent,
    InvoiceSurchargeAuditorAgent, ProactiveClaimsSupportAgent)
from backend.agents.rag_support import HelpRetriever, documentation_question


class LogisticsSupervisor:
    def __init__(self, settings=None, runtime=None):
        self.runtime = runtime or AgentRuntime(settings or AgentSettings())
        self.ingestion = IngestionWorkerAgent(self.runtime)
        self.customs = CustomsHarmonizerAgent(self.runtime)
        self.invoice = InvoiceSurchargeAuditorAgent(self.runtime)
        self.support = ProactiveClaimsSupportAgent(self.runtime)
        self.help = HelpRetriever(self.runtime)
        from backend.agents.margin_optimizer import MarginOptimizerAgent
        self.optimizer = MarginOptimizerAgent(self.runtime)

    @staticmethod
    def dispatch_permission(context):
        if context.role not in {'OWNER', 'ADMIN', 'DISPATCHER', 'ACCOUNTANT'}:
            raise HTTPException(403, 'Dispatch or finance permission required')

    async def interpret(self, context, text):
        self.dispatch_permission(context)
        workflow = Workflow()
        workflow.move(State.VALIDATING)
        from backend.agents.status_guidance import status_question
        if status_question(text) or documentation_question(text):
            guidance = await self.help.answer(context, text)
            workflow.move(State.READY)
            workflow.move(State.EXECUTING)
            workflow.move(State.COMPLETED)
            return {'workflow': workflow.model_dump(mode='json'), 'intent': {'intent': 'HELP'},
                    'message': guidance['answer'], 'help': guidance, 'booking_authorized': False}
        try:
            intent = await self.ingestion.message(context, text)
        except ValueError:
            workflow.move(State.REVIEW_REQUIRED)
            return {'workflow': workflow.model_dump(mode='json'), 'intent': None,
                'message': 'Please check the weight and countries in the standard shipping form.',
                'booking_authorized': False}
        workflow.move(State.NEEDS_INPUT)
        return {'workflow': workflow.model_dump(mode='json'), 'intent': intent.model_dump(mode='json'),
            'message': 'Review these details. Add the full addresses, measured packaging and goods information before requesting rates.',
            'booking_authorized': False}

    async def quote(self, request, context, rating_request):
        from main import get_rates
        self.dispatch_permission(context)
        workflow = Workflow()
        workflow.move(State.VALIDATING)
        workflow.move(State.READY)
        workflow.move(State.EXECUTING)
        try:
            result = await get_rates(rating_request, request, context)
        except BaseException:
            workflow.move(State.REVIEW_REQUIRED)
            raise
        workflow.move(State.COMPLETED)
        return {'workflow': workflow.model_dump(mode='json'), 'quote': result.model_dump(mode='json')}

    async def rates(self, context, body, rating_service):
        self.dispatch_permission(context)
        workflow = Workflow()
        workflow.move(State.VALIDATING)
        workflow.move(State.READY)
        workflow.move(State.EXECUTING)
        try:
            result = await rating_service.quote(context, body)
            result = await self.optimizer.recommend(context, result, getattr(rating_service, 'pool', None))
        except BaseException:
            workflow.move(State.REVIEW_REQUIRED)
            raise
        workflow.move(State.COMPLETED)
        self.runtime.usage['deterministic_calls'] += 1
        return result

    async def confirm(self, context, body, service):
        # No model or tool-call output reaches this capability. Only the existing
        # authenticated booking route supplies a validated, explicitly chosen offer.
        workflow = Workflow()
        workflow.move(State.VALIDATING)
        if context.tenant_id != body.tenant_id:
            raise HTTPException(403, 'Booking belongs to another workspace')
        workflow.move(State.READY)
        workflow.move(State.EXECUTING)
        try:
            result = await service.confirm(context, body)
        except BaseException:
            workflow.move(State.REVIEW_REQUIRED)
            raise
        workflow.move(State.REVIEW_REQUIRED if result.get('status') == 'SYNC_PENDING' else State.COMPLETED)
        # Preserve the exact public response and document proxy behavior. The existing
        # lifecycle owns FinanceEngine reservations/capture, reconciliation and PDFs.
        self.runtime.usage['deterministic_calls'] += 1
        return result

    async def whatsapp_quote(self, context, text):
        # Parsing occurs before the existing WhatsApp receipt/wallet database locks.
        from main import ParsedQuote
        try:
            async with asyncio.timeout(min(3, self.runtime.settings.logistics_agent_timeout_seconds)):
                intent = await self.ingestion.message(context, text)
            if intent.intent != 'QUOTE' or any(value is None for value in
                    (intent.weight_kg, intent.origin_country, intent.destination_country)):
                return None
            from decimal import Decimal
            return ParsedQuote(Decimal(intent.weight_kg), intent.origin_country,
                               intent.destination_country, intent.route_code)
        except (HTTPException, ValueError, TimeoutError):
            return None


def supervisor(request):
    instance = getattr(request.app.state, 'logistics_supervisor', None)
    if instance is None:
        raise HTTPException(503, 'Assistance service unavailable; use the standard shipping tools')
    return instance
