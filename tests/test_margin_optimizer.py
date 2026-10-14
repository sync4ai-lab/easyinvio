"""Deterministic profit selection and strictly optional, immutable recommendation."""
import asyncio
import time
import unittest
from decimal import Decimal
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock
from fastapi import HTTPException
from main import ClientRate,RatingResponse
from backend.agents.config import AgentSettings
from backend.agents.runtime import AgentRuntime,ModelResult
from backend.agents.margin_optimizer import MarginOptimizerAgent,StrategicChoice
from backend.carrier_consolidation import consolidate_rates


def rate(carrier,price,wholesale,service='STANDARD',**fields):
    return ClientRate(provider='REGIONAL',account_id=uuid4(),upstream_shipment_id='private',upstream_rate_id=str(uuid4()),
        carrier_code=carrier,service_code=service,currency='GBP',client_price_ex_tax=price,delivery_days=3,
        fee_breakdown={'wholesale_total':wholesale},**fields)


def response(rates):
    now=datetime.now(timezone.utc)
    return RatingResponse(request_id=uuid4(),currency='GBP',quoted_at=now,expires_at=now+timedelta(minutes=5),partial=False,rates=rates,issues=[],weight={})


class OptimizerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        settings=AgentSettings.model_construct(logistics_agents_enabled=True,openai_api_key=SimpleNamespace(get_secret_value=lambda:'mock-key'))
        self.runtime=AgentRuntime(settings,client=SimpleNamespace())
        self.worker=MarginOptimizerAgent(self.runtime)
        self.context=SimpleNamespace(tenant_id=uuid4(),user_id=uuid4(),role='OWNER')
        self.rates=[rate('DHL','12.30','10.00'),rate('UPS','14.20','11.00'),rate('DPD','16.00','12.00')]

    async def test_ai_changes_only_one_badge_and_keeps_order_and_decimal_prices(self):
        original=response(self.rates)
        self.runtime.run=AsyncMock(return_value=ModelResult(StrategicChoice(selected_index=1,basis='BALANCED'),20,10,0))
        result=await self.worker.recommend(self.context,original,None)
        self.assertEqual([rate.offer_id for rate in result.rates],[rate.offer_id for rate in original.rates])
        self.assertEqual([rate.client_price_ex_tax for rate in result.rates],[Decimal('12.30'),Decimal('14.20'),Decimal('16.00')])
        self.assertEqual(sum(bool(rate.recommendation_badge) for rate in result.rates),1)
        self.assertIsNone(original.rates[1].recommendation_badge)
        for before,after in zip(original.rates,result.rates):
            self.assertEqual(before.model_dump(exclude={'recommendation_badge'}),after.model_dump(exclude={'recommendation_badge'}))
        payload=self.runtime.run.call_args.args[3]
        self.assertEqual(len(payload['offers']),3)
        self.assertTrue(all('account_id' not in item and 'wholesale_total' not in item for item in payload['offers']))
        self.assertIsNone(payload['offers'][0]['route_risk_level'])

    async def test_unknown_history_cannot_receive_reliability_badge(self):
        self.runtime.run=AsyncMock(return_value=ModelResult(StrategicChoice(selected_index=0,basis='RELIABILITY'),20,10,0))
        original=response(self.rates)
        self.assertIs(await self.worker.recommend(self.context,original,None),original)

    async def test_complete_ten_offer_payload_can_recommend_tenth_offer(self):
        rates=[rate('DHL',str(Decimal('10.00')+index),'8.00',service=f'SERVICE_{index}') for index in range(10)]
        original=response(rates)
        self.runtime.run=AsyncMock(return_value=ModelResult(StrategicChoice(selected_index=9,basis='BALANCED'),20,10,0))
        result=await self.worker.recommend(self.context,original,None)
        payload=self.runtime.run.call_args.args[3]['offers']
        self.assertEqual(len(payload),10)
        self.assertEqual([item['index'] for item in payload],list(range(10)))
        self.assertEqual([item['client_price_ex_tax'] for item in payload],[str(item.client_price_ex_tax) for item in rates])
        self.assertTrue(result.rates[9].recommendation_badge)
        self.assertEqual(sum(bool(item.recommendation_badge) for item in result.rates),1)
        for before,after in zip(original.rates,result.rates):
            self.assertEqual(before.model_dump(exclude={'recommendation_badge'}),after.model_dump(exclude={'recommendation_badge'}))

    async def test_index_beyond_available_shortlist_returns_unchanged_rates(self):
        original=response(self.rates)
        self.runtime.run=AsyncMock(return_value=ModelResult(StrategicChoice(selected_index=9,basis='BALANCED'),20,10,0))
        self.assertIs(await self.worker.recommend(self.context,original,None),original)
        self.assertEqual(len(self.runtime.run.call_args.args[3]['offers']),3)

    async def test_known_reliable_lane_uses_only_supported_badge(self):
        self.rates[0]=self.rates[0].model_copy(update={'on_time_samples':20,'on_time_rate':Decimal('95'),'history_samples':20})
        self.runtime.run=AsyncMock(return_value=ModelResult(StrategicChoice(selected_index=0,basis='RELIABILITY'),20,10,0))
        result=await self.worker.recommend(self.context,response(self.rates),None)
        self.assertIn('recorded 90-day',result.rates[0].recommendation_badge)

    async def test_cheapest_claim_cannot_be_attached_to_more_expensive_offer(self):
        self.runtime.run=AsyncMock(return_value=ModelResult(StrategicChoice(selected_index=2,basis='PRICE'),20,10,0))
        original=response(self.rates);self.assertIs(await self.worker.recommend(self.context,original,None),original)

    async def test_disabled_ai_does_not_call_runtime(self):
        self.runtime.settings.logistics_agents_enabled=False
        self.runtime.run=AsyncMock()
        original=response(self.rates);self.assertIs(await self.worker.recommend(self.context,original,None),original)
        self.runtime.run.assert_not_awaited()

    async def test_network_timeout_is_cancelled_and_falls_back(self):
        async def slow(*args,**kwargs):await asyncio.sleep(5)
        self.runtime.run=AsyncMock(side_effect=slow)
        original=response(self.rates);start=time.monotonic()
        self.assertIs(await self.worker.recommend(self.context,original,None),original)
        self.assertLess(time.monotonic()-start,2.2)

    async def test_model_access_failure_keeps_all_offers(self):
        self.runtime.run=AsyncMock(side_effect=HTTPException(503,'Unavailable'))
        original=response(self.rates);self.assertIs(await self.worker.recommend(self.context,original,None),original)
        self.assertEqual(len(original.rates),3)

    async def test_support_scheduling_failure_cannot_break_quotes(self):
        self.runtime.run=AsyncMock(side_effect=HTTPException(503,'Unavailable'))
        self.worker.queue_failure=lambda *args:(_ for _ in ()).throw(RuntimeError('Queue unavailable'))
        original=response(self.rates)
        self.assertIs(await self.worker.recommend(self.context,original,object()),original)

    async def test_ticket_writes_are_background_only_and_deduplicated(self):
        gate=asyncio.Event()
        async def store(*args):await gate.wait()
        self.worker.persist_failure=AsyncMock(side_effect=store)
        self.worker.queue_failure(self.context,uuid4(),'AI_RECOMMENDATION_TIMEOUT',object())
        self.worker.queue_failure(self.context,uuid4(),'AI_RECOMMENDATION_TIMEOUT',object())
        self.assertEqual(len(self.worker.pending),1)
        gate.set();await self.worker.close()
        self.worker.persist_failure.assert_awaited_once()


class ColdSelectionTests(unittest.TestCase):
    def test_internal_ticket_preserves_rate_trace_without_claiming_shipment_failure(self):
        from backend.support_workflow import present_ticket
        result=present_ticket({'automation_failure_id':uuid4(),'error_code':'AI_RECOMMENDATION_TIMEOUT',
            'ai_summary':'Quote trace: unchanged offers returned; no wallet mutation.'})
        self.assertEqual(result['ticket_title'],'Quote recommendation assistance')
        self.assertEqual(result['pod_state'],'NOT_APPLICABLE')
        self.assertIn('unchanged offers',result['ai_summary'])

    def test_highest_absolute_profit_duplicate_then_lowest_ten_prices(self):
        low=rate('DHL','10.00','9.00')
        high=rate('DHL','14.00','10.00')
        choices=[rate('UPS','11.00','9.00'),rate('DPD','12.00','10.00'),rate('FEDEX','16.00','13.00'),low,high]
        choices.extend(rate('UPS',str(Decimal('20.00')+index),'15.00',service=f'EXTRA_{index}') for index in range(10))
        selected=consolidate_rates(choices)[:10]
        self.assertEqual([item.client_price_ex_tax for item in selected],
            [Decimal('11.00'),Decimal('12.00'),Decimal('14.00'),Decimal('16.00')]+
            [Decimal('20.00')+index for index in range(6)])
        self.assertIn(high,selected);self.assertNotIn(low,selected)
        self.assertEqual(len({(item.carrier_code,item.service_code) for item in selected}),10)


if __name__=='__main__':unittest.main()
