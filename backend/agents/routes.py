"""Authenticated AI preparation and documentation; no general-purpose action tools."""
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import Field
from backend.agents.models import StrictOutput, MessageRequest, HelpQuestion
from backend.agents.supervisor import supervisor


class Description(StrictOutput):
    description: str = Field(min_length=3, max_length=500)
    sku: str | None = Field(default=None, min_length=1, max_length=200)


class CustomsItems(StrictOutput):
    items: list[dict] = Field(min_length=1, max_length=100)


def build_router(authenticate, rating_model, authenticate_platform_owner):
    router = APIRouter(tags=['Bounded logistics assistance'])

    @router.post('/api/v1/agents/interpret')
    async def interpret(body: MessageRequest, request: Request, context=Depends(authenticate)):
        return await supervisor(request).interpret(context, body.text)

    async def quote(body, request: Request, context=Depends(authenticate)):
        return await supervisor(request).quote(request, context, body)
    quote.__annotations__['body'] = rating_model
    router.add_api_route('/api/v1/agents/quote', quote, methods=['POST'])

    @router.post('/api/v1/agents/customs/suggest')
    async def customs(body: Description, request: Request, context=Depends(authenticate)):
        engine = supervisor(request)
        engine.dispatch_permission(context)
        product = None
        if body.sku:
            from backend.tenant_catalogs import TenantCatalogService, database_error
            import asyncpg
            finance = getattr(request.app.state, 'finance', None)
            if finance is None:
                raise HTTPException(503, 'Catalog storage is unavailable')
            try:
                product = await TenantCatalogService(finance.pool).product_by_sku(context, body.sku)
            except asyncpg.PostgresError as error:
                raise database_error(error) from None
        return await engine.customs.suggest(context, body.description, product=product)

    @router.post('/api/v1/agents/customs/information')
    async def information(body: CustomsItems, request: Request, context=Depends(authenticate)):
        engine = supervisor(request)
        engine.dispatch_permission(context)
        from pydantic import ValidationError
        try:
            return await engine.customs.information(context, body.items)
        except (ValueError, ValidationError):
            raise HTTPException(422, 'Review the item quantities, weights, values and country codes') from None

    @router.post('/api/v1/help/search-agent')
    async def search(body: HelpQuestion, request: Request, context=Depends(authenticate)):
        return await supervisor(request).help.answer(context, body.query)

    @router.get('/api/v1/admin/agents/metrics')
    async def metrics(request: Request, actor=Depends(authenticate_platform_owner)):
        engine = supervisor(request)
        return {'configured': engine.runtime.available, 'scope': 'current application process',
            'usage': dict(engine.runtime.usage), 'model': engine.runtime.settings.logistics_agent_model,
            'embedding_model': engine.runtime.settings.logistics_embedding_model,
            'customer_prompt_logging': False, 'autonomous_purchases': False}

    return router
