"""Backend role template runs only on an explicitly disposable database."""
from pathlib import Path
from uuid import uuid4
import asyncpg
import pytest
from tests.test_tracking_workspace_postgres import world

@pytest.mark.asyncio
async def test_backend_role_template_preserves_identity_and_membership_history(world):
    c=world.db;uid=uuid4();actor=world.actors[1]
    await c.command("""ALTER TABLE auth.users ADD COLUMN email text;
      ALTER TABLE public.users ADD COLUMN full_name text, ADD COLUMN updated_at timestamptz DEFAULT now();
      ALTER TABLE public.users ALTER COLUMN id SET DEFAULT gen_random_uuid();
      CREATE UNIQUE INDEX test_users_tenant_identity ON public.users(tenant_id,auth_user_id);
      CREATE TABLE public.app_user_profiles(auth_user_id uuid PRIMARY KEY,full_name text,updated_at timestamptz DEFAULT now());
      CREATE TABLE public.app_auth_sessions(id uuid,auth_user_id uuid);
      CREATE TABLE public.admin_client_assistance_sessions(actor_auth_user_id uuid,revoked_at timestamptz);
    """,mode='exec')
    await c.command(Path('migrations/048_platform_agents.sql').read_text(encoding='utf-8'),mode='exec')
    await c.execute("INSERT INTO auth.users(id,email) VALUES($1,'person@example.invalid')",uid)
    source=Path('docs/backend_user_administration.sql').read_text(encoding='utf-8')
    async def run(action='INSPECT',tenant=None,role='DISPATCHER'):
        sql=source.replace("access_action='INSPECT'","access_action='"+action+"'")
        sql=sql.replace('replace-user@example.invalid','person@example.invalid')
        sql=sql.replace("actor_id='00000000-0000-0000-0000-000000000000'","actor_id='"+str(actor)+"'")
        sql=sql.replace("tenant_id='00000000-0000-0000-0000-000000000000'","tenant_id='"+str(tenant or world.tenants[0])+"'")
        sql=sql.replace("customer_role='DISPATCHER'","customer_role='"+role+"'")
        sql=sql.replace("access_reason=''","access_reason='Reviewed fixture access change'")
        await c.command(sql,mode='exec')
    await run()
    assert await c.fetchval('SELECT count(*) FROM public.users WHERE auth_user_id=$1',uid)==0
    await run('ASSIGN_CUSTOMER')
    member=await c.fetchrow('SELECT id,role,is_active FROM public.users WHERE auth_user_id=$1',uid)
    assert member['role']=='DISPATCHER' and member['is_active']
    await run('ASSIGN_CUSTOMER',role='ACCOUNTANT')
    changed=await c.fetchrow('SELECT id,role FROM public.users WHERE auth_user_id=$1',uid)
    assert changed['id']==member['id'] and changed['role']=='ACCOUNTANT'
    with pytest.raises(asyncpg.PostgresError):await run('ASSIGN_CUSTOMER',world.tenants[1])
    await c.command('ROLLBACK',mode='exec')
    await run('ASSIGN_AGENT')
    assert await c.fetchval('SELECT is_active FROM public.platform_staff WHERE auth_user_id=$1',uid)
    retained=await c.fetchrow('SELECT id,is_active FROM public.users WHERE auth_user_id=$1',uid)
    assert retained['id']==member['id'] and not retained['is_active']
    await run('DISABLE_AGENT')
    assert not await c.fetchval('SELECT is_active FROM public.platform_staff WHERE auth_user_id=$1',uid)
    assert await c.fetchval('SELECT count(*) FROM public.platform_staff_events WHERE staff_auth_user_id=$1',uid)==2
    assert await c.fetchval('SELECT email FROM auth.users WHERE id=$1',uid)=='person@example.invalid'
