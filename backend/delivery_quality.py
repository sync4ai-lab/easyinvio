"""Tenant-bound tracking readiness; status transport and quality are separate."""
import asyncpg
import pycountry
from fastapi import APIRouter, Depends, HTTPException, Request


async def tracking_readiness(pool, tenant_id, origin, destination, environment):
    async with pool.acquire() as c:
        configuration = await c.fetchrow('''SELECT count(*) AS connections,
            count(*) FILTER(WHERE o.webhook_enabled AND o.webhook_secret IS NOT NULL) AS receivers
            FROM public.carrier_accounts a LEFT JOIN public.partner_provider_options o ON o.platform_connection_id=a.platform_connection_id
            WHERE a.tenant_id=$1 AND a.is_active''', tenant_id)
        events = await c.fetchrow('''SELECT count(*) AS received,
            count(*) FILTER(WHERE e.status='IN_TRANSIT' AND e.response->>'applied'='true') AS transit,
            count(*) FILTER(WHERE e.status='DELIVERED' AND e.response->>'applied'='true') AS delivered
            FROM public.tracking_events e JOIN public.shipments s ON s.tenant_id=e.tenant_id AND s.id=e.shipment_id
            WHERE e.tenant_id=$1 AND s.origin_country=$2 AND s.destination_country=$3''', tenant_id, origin, destination)
        history = await c.fetchrow('''SELECT count(*) FILTER(WHERE s.status='DELIVERED' AND s.delivered_at IS NOT NULL) AS delivered,
            count(*) FILTER(WHERE s.pricing_snapshot->'selected_rate'->>'delivery_days' IS NOT NULL) AS estimated
            FROM public.shipments s JOIN public.carrier_accounts a ON a.tenant_id=s.tenant_id AND a.id=s.carrier_account_id
            WHERE s.tenant_id=$1 AND s.origin_country=$2 AND s.destination_country=$3 AND a.environment='LIVE'
            AND coalesce(s.delivered_at,s.last_tracking_event_at,s.booked_at,s.created_at)>=now()-interval '90 days'
            AND s.logistics_metadata->>'synthetic' IS DISTINCT FROM 'true' AND NOT(s.logistics_metadata ? 'fixture_batch')''', tenant_id, origin, destination)
    reasons = []
    if environment == 'TEST':
        reasons.append('TEST shipments do not establish real carrier performance. Measured scores use completed LIVE deliveries in your workspace over the last 90 days.')
    if not configuration['receivers']:
        reasons.append('Authenticated tracking receivers are not enabled on your active connections. The platform owner must configure signing credentials and register a public HTTPS receiver with each provider.')
    if not events['received']:
        reasons.append('No tracking events have been received for this route.')
    if not history['delivered']:
        reasons.append('No completed LIVE deliveries have been recorded for this route yet.')
    if not history['estimated']:
        reasons.append('On-time percentages additionally require a saved carrier delivery estimate; a delivery scan alone is not an on-time promise.')
    return {'origin_country': origin, 'destination_country': destination, 'active_connections': configuration['connections'],
            'configured_tracking_receivers': configuration['receivers'], 'received_tracking_events': events['received'],
            'accepted_transit_events': events['transit'], 'accepted_delivery_events': events['delivered'],
            'live_deliveries': history['delivered'], 'reasons': reasons,
            'method': 'Observed transit: first verified in-transit/dispatch to delivery, in calendar days. On-time: compared with the saved business-day estimate, excluding weekends; holidays are not adjusted. Carrier estimates are separate from measured history.'}


def build_router(authenticate):
    router = APIRouter(tags=['Delivery quality readiness'])

    @router.get('/api/v1/analytics/tracking-readiness')
    async def readiness(origin_country: str, destination_country: str, request: Request, context=Depends(authenticate)):
        from main import validate_tenant_query
        validate_tenant_query(request, context.tenant_id)
        if context.role not in {'OWNER', 'ADMIN', 'DISPATCHER', 'ACCOUNTANT'}:
            raise HTTPException(403, 'Workspace analytics permission required')
        if any(pycountry.countries.get(alpha_2=country) is None for country in (origin_country, destination_country)):
            raise HTTPException(422, 'Select valid ISO countries')
        try:
            return await tracking_readiness(request.app.state.finance.pool, context.tenant_id,
                origin_country, destination_country, request.app.state.settings.provider_environment)
        except asyncpg.PostgresError:
            raise HTTPException(503, 'Tracking diagnostics are temporarily unavailable') from None

    return router
