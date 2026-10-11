"""Real onboarding transaction verification; all new rows are rolled back."""
import asyncio
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import asyncpg
from main import Settings, database_tls_context
from backend.admin_portal import AdminService, PlatformOwner, TenantCreate


async def run():
    settings = Settings()
    actor = PlatformOwner(UUID('117d268d-b034-4a74-ad4d-050813bf67ac'))
    assert str(actor.user_id) in {str(value) for value in settings.platform_admin_user_ids}
    connection = await asyncpg.connect(settings.database_url.get_secret_value(),
        ssl=database_tls_context(settings.database_ca_file, strict=settings.database_tls_strict), timeout=15)

    class BorrowedPool:
        @asynccontextmanager
        async def acquire(self):
            yield connection

    transaction = connection.transaction()
    await transaction.start()
    try:
        service = AdminService(BorrowedPool())
        body = TenantCreate(request_id=uuid4(), billing_plan='PREPAID_WALLET',
            default_currency='GBP', is_sandbox=True, company_profile={
                'company_name':'ONBOARDING ROLLBACK TEST', 'contact_name':'Synthetic Test',
                'billing_email':'onboarding-test@example.invalid', 'address_line1':'1 Fixture Way',
                'city':'London', 'postal_code':'SW1A 1AA', 'country_code':'GB'})
        created = await service.create_tenant(body, actor)
        assert await connection.fetchval('SELECT count(*) FROM public.tenants WHERE tenant_id=$1', created.tenant_id) == 1
        assert await connection.fetchval('SELECT count(*) FROM public.wallets WHERE tenant_id=$1 AND currency=$2 AND balance=0',created.tenant_id,'GBP') == 1
        assert await connection.fetchval('SELECT count(*) FROM public.hubspot_sync_jobs WHERE tenant_id=$1',created.tenant_id) == 1
        replay = await service.create_tenant(body, actor)
        assert replay.tenant_id == created.tenant_id
        print('PASS: real tenant INSERT, zero GBP wallet, CRM queue trigger, idempotent retry. Rolling back all test rows; no external CRM calls.')
    finally:
        await transaction.rollback()
        await connection.close()


if __name__ == '__main__':
    asyncio.run(run())
