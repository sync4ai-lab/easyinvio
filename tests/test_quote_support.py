"""Internal quote intake does not invoke provider or payment capabilities."""
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock
from fastapi import HTTPException
from backend.package_guidance import QuoteSupport, build_router
from backend.rate_diagnostics import record_quote_case
from backend.support_workflow import present_ticket


class QuoteSupportTests(unittest.IsolatedAsyncioTestCase):
    async def test_case_is_transactional_and_bound_to_verified_tenant(self):
        tenant,key,failure,ticket=uuid4(),uuid4(),uuid4(),uuid4()
        calls=[]
        class Pool:
            @asynccontextmanager
            async def acquire(self):yield self
            @asynccontextmanager
            async def transaction(self):yield
            async def fetchval(self,sql,*args):
                calls.append((sql,args))
                return failure if 'public.automation_failures' in sql else ticket
        result=await record_quote_case(Pool(),tenant,key,'Route needs carrier review')
        self.assertEqual(result,ticket)
        self.assertEqual(calls[0][1][:2],(tenant,key))
        self.assertEqual(calls[1][1][:2],(tenant,failure))
        self.assertIn('ON CONFLICT',calls[0][0])
        self.assertIn('ON CONFLICT',calls[1][0])
        self.assertTrue(all('wallet' not in sql and 'outbox' not in sql for sql,args in calls))

    async def test_sea_intake_uses_existing_cases_without_booking(self):
        from unittest.mock import patch
        tenant,key,ticket=uuid4(),uuid4(),uuid4()
        body=QuoteSupport(origin_country='GB',destination_country='US',cargo_type='PALLET',
            actual_weight_kg='100',dimensions={'length_cm':'120','width_cm':'80','height_cm':'100'},
            request_id=key,transport_mode='SEA',notes='Two pallets; loading dock available')
        endpoint=next(route.endpoint for route in build_router(lambda:None).routes if route.path.endswith('quote-support'))
        pool=object();request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(finance=SimpleNamespace(pool=pool))))
        context=SimpleNamespace(tenant_id=tenant,role='DISPATCHER')
        with patch('backend.rate_diagnostics.record_quote_case',new=AsyncMock(return_value=ticket)) as save:
            result=await endpoint(body,request,context)
            self.assertEqual(result['case_id'],str(ticket))
            self.assertFalse(result['booked'])
            self.assertEqual(save.await_args.args[:3],(pool,tenant,key))
            self.assertIn('SEA',save.await_args.args[3])
            self.assertEqual(save.await_args.args[4],'FREIGHT_QUOTE_REQUESTED')
            with self.assertRaises(HTTPException) as error:
                await endpoint(body,request,SimpleNamespace(role='VIEWER'))
            self.assertEqual(error.exception.status_code,403)
            self.assertEqual(save.await_count,1)

    def test_admin_case_keeps_actionable_summary(self):
        case=present_ticket({'automation_failure_id':uuid4(),'error_code':'FREIGHT_QUOTE_REQUESTED',
            'ai_summary':'SEA quote, GB to US, 100 kg, reference ABC','notifications':[]})
        self.assertEqual(case['ticket_title'],'Freight quote request')
        self.assertIn('100 kg',case['ai_summary'])
        self.assertEqual(case['ticket_type'],'PROCESSING_ISSUE')
