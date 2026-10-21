"""Actual manifest joins on explicit disposable PostgreSQL, never Supabase."""
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
import httpx
import pytest

from backend.advanced_logistics import build_router
from test_tracking_workspace_postgres import world


@pytest.mark.asyncio
async def test_manifest_join_does_not_duplicate_orders_and_requote_retains_tenant_scope(world):
    w=world
    await w.db.command('''ALTER TABLE public.tenants ADD COLUMN billing_plan text DEFAULT 'PREPAID_WALLET';
        ALTER TABLE public.shipments ADD COLUMN currency text DEFAULT 'GBP',
        ADD COLUMN final_client_price numeric DEFAULT 19.94,ADD COLUMN service_code text DEFAULT 'TRACKED_48',
        ADD COLUMN quote_expires_at timestamptz DEFAULT now()+interval '5 minutes',ADD COLUMN quoted_at timestamptz DEFAULT now(),
        ADD COLUMN pricing_snapshot jsonb DEFAULT '{}',ADD COLUMN customs_required boolean DEFAULT false,
        ADD COLUMN customs_items jsonb DEFAULT '[]',ADD COLUMN customs_reviewed_at timestamptz,
        ADD COLUMN sender_address jsonb DEFAULT '{}',ADD COLUMN recipient_address jsonb DEFAULT '{}',
        ADD COLUMN parcel_weight_kg numeric DEFAULT 2,ADD COLUMN parcel_length_cm numeric DEFAULT 24,
        ADD COLUMN parcel_width_cm numeric DEFAULT 16,ADD COLUMN parcel_height_cm numeric DEFAULT 8;
        CREATE TABLE public.wallet_reservations(tenant_id uuid,shipment_id uuid,status text,UNIQUE(tenant_id,shipment_id));
        CREATE TABLE public.partner_order_jobs(tenant_id uuid,shipment_id uuid,carrier_account_id uuid,state text);
    ''',mode='exec')
    # Different historical carrier jobs must not multiply the recent-order list.
    for _ in range(2):
        await w.db.execute("INSERT INTO public.partner_order_jobs VALUES($1,$2,$3,'RECONCILIATION_REQUIRED')",w.tenants[0],w.shipments[0],uuid4())
    async def auth():return SimpleNamespace(tenant_id=w.tenants[0],user_id=w.actors[0],role='OWNER')
    app=FastAPI();app.state.finance=SimpleNamespace(pool=w.db);app.include_router(build_router(auth,None))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://offline.test') as client:
        response=await client.get('/api/v1/shipments/manifest')
        assert response.status_code==200,response.text
        rows=response.json()['shipments']
        assert len(rows)==1 and rows[0]['carrier_code']=='ROYALMAIL' and rows[0]['service_code']=='TRACKED_48'
        assert rows[0]['quote_expires_at'] and not rows[0]['workflow']['can_requote']
        # Failed but uncertain jobs cannot be copied to a second carrier purchase.
        await w.db.execute("UPDATE public.shipments SET status='FAILED',booked_at=NULL WHERE id=$1",w.shipments[0])
        assert (await client.get(f'/api/v1/shipments/{w.shipments[0]}/requote-context')).status_code==409
        await w.db.execute("UPDATE public.partner_order_jobs SET state='FAILED'")
        restored=await client.get(f'/api/v1/shipments/{w.shipments[0]}/requote-context')
        assert restored.status_code==200,restored.text
        assert restored.json()['packages'][0]['length_cm']=='24'
        assert (await client.get(f'/api/v1/shipments/{w.shipments[1]}/requote-context')).status_code==404
