"""Source-grounded stall incidents, deduplicated before optional AI explanation."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger('easyinvio.delay_sentinel')


class DelayExplanation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=10,max_length=400)


class ProactiveDelaySentinelAgent:
    @staticmethod
    def detect(status: str, booked_at: datetime, last_scan: datetime | None,
               now: datetime | None = None) -> str | None:
        now=now or datetime.now(timezone.utc)
        if status=='EXCEPTION':
            return 'CARRIER_EXCEPTION'
        if status in {'BOOKED','MANIFESTED','DISPATCHED'} and last_scan is None and now-booked_at>timedelta(hours=48):
            return 'NO_FIRST_SCAN_48H'
        if status=='IN_TRANSIT' and now-(last_scan or booked_at)>timedelta(hours=72):
            return 'IN_TRANSIT_STALLED_72H'
        return None

    @staticmethod
    def explain(reason: str) -> str:
        return {
            'CARRIER_EXCEPTION':'The carrier has reported an exception. Review the latest carrier scan and contact the carrier if action is required. No delivery date is confirmed.',
            'NO_FIRST_SCAN_48H':'This label has no recorded carrier scan more than 48 hours after booking. Check handover or collection with the carrier; missing scans alone do not prove the parcel is lost.',
            'IN_TRANSIT_STALLED_72H':'No new in-transit scan has been recorded for more than 72 hours. Ask the carrier for a trace. This is a recorded-data alert, not a confirmed loss or delivery prediction.'}[reason]


    @classmethod
    async def explain_bounded(cls,runtime: Any,tenant_id: UUID,reason: str) -> str:
        approved=cls.explain(reason)
        if runtime is None or not runtime.available:return approved
        try:
            result=await runtime.run(tenant_id,'ProactiveDelaySentinelAgent',
                'Return the supplied source-grounded explanation exactly. Never add dates, locations, loss confirmation, liability or payment promises.',
                {'reason':reason,'approved_explanation':approved},output_type=DelayExplanation,output_token_limit=160)
            candidate=DelayExplanation.model_validate(result.value).text
            # A model cannot introduce new facts, even through a persuasive paraphrase.
            return candidate if candidate==approved else approved
        except (HTTPException,ValueError,TimeoutError):return approved


class DelaySentinel:
    def __init__(self,pool: Any,environment: str,state: Any=None) -> None:
        self.pool,self.environment=pool,environment
        self.state=state

    async def scan(self) -> int:
        from backend.cx_support import SupportCase,record_case
        total=0
        async with self.pool.acquire() as c:
            rows=await c.fetch('''SELECT s.id,s.tenant_id,s.status,coalesce(s.booked_at,s.created_at) AS booked_at,s.last_tracking_event_at
                FROM public.shipments s JOIN public.tenants t USING(tenant_id)
                JOIN public.carrier_accounts a ON a.tenant_id=s.tenant_id AND a.id=s.carrier_account_id
                WHERE t.workspace_status='ACTIVE' AND a.environment=$1 AND s.status::text IN ('BOOKED','MANIFESTED','DISPATCHED','IN_TRANSIT','EXCEPTION')
                AND coalesce(s.booked_at,s.created_at)>now()-interval '90 days'
                AND (s.status::text='EXCEPTION'
                  OR (s.status::text='IN_TRANSIT' AND coalesce(s.last_tracking_event_at,s.booked_at,s.created_at)<now()-interval '72 hours')
                  OR (s.status::text IN ('BOOKED','MANIFESTED','DISPATCHED') AND s.last_tracking_event_at IS NULL
                    AND coalesce(s.booked_at,s.created_at)<now()-interval '48 hours'))
                AND NOT EXISTS(SELECT 1 FROM public.cx_delay_incidents i WHERE i.tenant_id=s.tenant_id AND i.shipment_id=s.id
                  AND i.created_at>coalesce(s.last_tracking_event_at,s.booked_at,s.created_at)
                  AND i.incident_key LIKE CASE WHEN s.status::text='EXCEPTION' THEN 'CARRIER_EXCEPTION:%'
                    WHEN s.status::text='IN_TRANSIT' THEN 'IN_TRANSIT_STALLED_72H:%' ELSE 'NO_FIRST_SCAN_48H:%' END)
                ORDER BY coalesce(s.last_tracking_event_at,s.booked_at,s.created_at) LIMIT 100''',self.environment)
            for row in rows:
                reason=ProactiveDelaySentinelAgent.detect(row['status'],row['booked_at'],row['last_tracking_event_at'])
                if reason is None:
                    continue
                explanation=ProactiveDelaySentinelAgent.explain(reason)
                if self.state is not None and getattr(self.state.settings,'cx_delay_llm_enabled',False):
                    runtime=getattr(getattr(self.state,'logistics_supervisor',None),'runtime',None)
                    explanation=await ProactiveDelaySentinelAgent.explain_bounded(runtime,row['tenant_id'],reason)
                incident=reason+':'+(row['last_tracking_event_at'] or row['booked_at']).isoformat()
                identifier=uuid5(NAMESPACE_URL,f"cx-delay:{row['tenant_id']}:{row['id']}:{incident}")
                async with c.transaction():
                    await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',f"cx-delay-shipment:{row['tenant_id']}:{row['id']}")
                    await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',str(identifier))
                    exists=await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.cx_delay_incidents WHERE tenant_id=$1 AND shipment_id=$2 AND incident_key=$3)',row['tenant_id'],row['id'],incident)
                    if exists:
                        continue
                    current=await c.fetchrow('SELECT status,last_tracking_event_at FROM public.shipments WHERE tenant_id=$1 AND id=$2 FOR SHARE',row['tenant_id'],row['id'])
                    if not current or current['status']!=row['status'] or current['last_tracking_event_at']!=row['last_tracking_event_at']:
                        continue
                    ticket=await c.fetchval("SELECT id FROM public.support_tickets WHERE tenant_id=$1 AND shipment_id=$2 AND status IN ('OPEN','IN_REVIEW') AND (tracking_event_id IS NOT NULL OR issue_category='MISSING_DELAYED') ORDER BY id LIMIT 1",row['tenant_id'],row['id'])
                    if ticket is None:
                        ticket=await record_case(c,SupportCase(request_id=identifier,tenant_id=row['tenant_id'],shipment_id=row['id'],kind='SERVICE_REQUEST',category='MISSING_DELAYED',summary=explanation))
                    await c.execute('INSERT INTO public.cx_delay_incidents(tenant_id,shipment_id,incident_key,ticket_id) VALUES($1,$2,$3,$4)',row['tenant_id'],row['id'],incident,ticket)
                    total+=1
        return total

    async def worker(self) -> None:
        import asyncpg
        while True:
            try:
                await self.scan()
            except asyncpg.PostgresError:
                logger.warning('delay_sentinel_storage_unavailable')
            await asyncio.sleep(300)
