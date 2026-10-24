"""Execute the staff migration and authorization boundaries on disposable PostgreSQL."""
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import asyncpg
import pytest
from tests.test_tracking_workspace_postgres import world
from backend.platform_staff import platform_role

@pytest.mark.asyncio
async def test_staff_cannot_also_be_a_customer_and_audit_is_immutable(world):
    c=world.db
    await c.command(Path('migrations/048_platform_agents.sql').read_text(encoding='utf-8'),mode='exec')
    actor=world.actors[0];settings=SimpleNamespace(platform_admin_user_ids=[])
    assert await platform_role(c,settings,actor) is None
    with pytest.raises(asyncpg.CheckViolationError):
        await c.execute('INSERT INTO public.platform_staff(auth_user_id,created_by) VALUES($1,$1)',actor)
    await c.execute('UPDATE public.users SET is_active=false WHERE auth_user_id=$1',actor)
    await c.execute('INSERT INTO public.platform_staff(auth_user_id,created_by) VALUES($1,$1)',actor)
    assert await platform_role(c,settings,actor)=='AGENT'
    with pytest.raises(asyncpg.CheckViolationError):
        await c.execute('UPDATE public.users SET is_active=true WHERE auth_user_id=$1',actor)
    # Assistance audit memberships may exist but never grant ordinary login.
    await c.execute("INSERT INTO public.users(id,tenant_id,auth_user_id,role,is_active) VALUES($1,$2,$3,'OWNER',false)",uuid4(),world.tenants[1],actor)
    await c.execute("INSERT INTO public.platform_staff_events(actor_auth_user_id,staff_auth_user_id,is_active,reason) VALUES($1,$1,true,'Explicit test staff grant')",actor)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await c.execute('DELETE FROM public.platform_staff_events')
    await c.execute('UPDATE public.platform_staff SET is_active=false WHERE auth_user_id=$1',actor)
    assert await platform_role(c,settings,actor) is None
    for table in ('platform_staff','platform_staff_events'):
        assert await c.fetchval('SELECT relrowsecurity FROM pg_class WHERE oid=$1::regclass','public.'+table)
        for role in ('anon','authenticated'):
            assert not await c.fetchval('SELECT has_table_privilege($1,$2,$3)',role,'public.'+table,'SELECT')


@pytest.mark.asyncio
async def test_shipping_card_scope_matches_exact_tenant_actor_price_and_status(world):
    from decimal import Decimal
    from fastapi import HTTPException
    from backend.platform_staff import checkout_roles
    c=world.db;actor=world.actors[0];tenant=world.tenants[0];cart=uuid4()
    await c.command("CREATE TABLE public.payment_carts(id uuid PRIMARY KEY,tenant_id uuid,requested_by uuid,amount numeric,status text)",mode='exec')
    await c.execute("INSERT INTO public.payment_carts VALUES($1,$2,$3,12.50,'CREATING')",cart,tenant,actor)
    context=SimpleNamespace(tenant_id=tenant,user_id=actor)
    class MoneyConnection:
        async def fetchrow(self,sql,*args):
            row=await c.fetchrow(sql,*args)
            return {**row,'amount':Decimal(str(row['amount']))} if row else None
    money=MoneyConnection()
    assert 'DISPATCHER' in await checkout_roles(money,context,cart,Decimal('12.50'))
    for candidate,amount in [(SimpleNamespace(tenant_id=world.tenants[1],user_id=actor),Decimal('12.50')),
                            (SimpleNamespace(tenant_id=tenant,user_id=world.actors[1]),Decimal('12.50')),
                            (context,Decimal('100.00'))]:
        with pytest.raises(HTTPException):await checkout_roles(money,candidate,cart,amount)
    await c.execute("UPDATE public.payment_carts SET status='COMPLETED' WHERE id=$1",cart)
    with pytest.raises(HTTPException):await checkout_roles(money,context,cart,Decimal('12.50'))
