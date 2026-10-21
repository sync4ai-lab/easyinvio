"""Optional HubSpot CRM synchronization with durable PostgreSQL jobs.

No credential prefix denotes test mode in HubSpot: pat-* tokens access the
account that issued them. Use a separate developer/test account for testing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Any
from uuid import UUID

import asyncpg
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, SecretStr, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("veloce.crm")
API_BASE_URL = "https://api.hubapi.com"
_service: HubSpotService | None = None


class HubSpotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    hubspot_enabled: bool = False
    hubspot_access_token: SecretStr | None = None
    hubspot_expected_portal_id: int | None = Field(default=None,ge=1)
    hubspot_environment: str = Field(default='SANDBOX',pattern=r'^(SANDBOX|PRODUCTION)$')
    hubspot_provisioning_enabled: bool = False
    hubspot_webhook_client_secret: SecretStr | None = None
    hubspot_webhook_url: str = ""
    hubspot_webhook_app_id: int | None = Field(default=None, ge=1)
    hubspot_closed_won_stage_ids: list[str] = Field(default_factory=lambda: ["closedwon"])
    hubspot_upsell_enabled: bool = False
    hubspot_upsell_pipeline_id: str = ""
    hubspot_upsell_stage_id: str = ""

    @field_validator('hubspot_expected_portal_id', 'hubspot_webhook_app_id',mode='before')
    @classmethod
    def optional_account(cls,value):
        if value is None or isinstance(value,str) and not value.strip():return None
        if isinstance(value,bool):raise ValueError('HubSpot account ID must be a positive integer')
        return value

    @field_validator('hubspot_access_token', 'hubspot_webhook_client_secret',mode='before')
    @classmethod
    def clean_token(cls,value):
        if value is None:return None
        text=value.get_secret_value() if isinstance(value,SecretStr) else str(value)
        text=text.strip()
        if not text:return None
        if any(c.isspace() or ord(c)<32 or ord(c)==127 for c in text):
            raise ValueError('Use the raw access token without a Bearer prefix or internal whitespace')
        return SecretStr(text)

    @field_validator('hubspot_upsell_pipeline_id','hubspot_upsell_stage_id')
    @classmethod
    def safe_id(cls,value):
        if value and not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value):
            raise ValueError('Use an internal pipeline/stage identifier, not a URL or display label')
        return value

    @model_validator(mode='after')
    def activated(self):
        if self.hubspot_enabled and (not self.hubspot_access_token or not self.hubspot_expected_portal_id):
            raise ValueError('Enabled CRM requires an access token and expected HubSpot account ID')
        if self.hubspot_upsell_enabled and (not self.hubspot_upsell_pipeline_id or not self.hubspot_upsell_stage_id):
            raise ValueError('Upsell requires both internal pipeline and stage IDs')
        if self.hubspot_provisioning_enabled:
            from urllib.parse import urlsplit
            url = urlsplit(self.hubspot_webhook_url)
            if not self.hubspot_enabled or not self.hubspot_webhook_client_secret or not self.hubspot_webhook_app_id:
                raise ValueError("Provisioning requires enabled CRM, webhook app ID and app client secret")
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment or url.path != "/api/v1/integrations/hubspot-webhook":
                raise ValueError("Configure the exact public HTTPS HubSpot webhook endpoint without query parameters")
            if not self.hubspot_closed_won_stage_ids or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", v) for v in self.hubspot_closed_won_stage_ids):
                raise ValueError("Configure internal closed-won stage IDs")
        return self


class CRMError(Exception):
    """Sanitized errors: never retain request headers or remote response bodies."""
    def __init__(self, code: str, retryable: bool = True, retry_after: float = 0):
        super().__init__(code)
        self.code, self.retryable, self.retry_after = code, retryable, retry_after


def spend_string(value: Decimal) -> str:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0 or value >= Decimal("1e14"):
        raise ValueError("Spend must be a finite, nonnegative Decimal below 1e14")
    if value * 100 != (value * 100).to_integral_value():
        raise ValueError("Spend must have at most two decimal places")
    return format(value, ".2f")


def validate_profile(company_name: str, email: str, vat_number: str):
    for value, limit in [(company_name, 200), (email, 254), (vat_number, 100)]:
        if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid company/contact details")
    if not company_name.strip() or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Company name and primary email are required")


def retry_seconds(value: str | None) -> float:
    if value is None:
        return 0
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            seconds = (when - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return 0
    return max(0, min(seconds, 86400)) if seconds == seconds else 0


class HubSpotClient:
    def __init__(self, http: httpx.AsyncClient, settings: HubSpotSettings, sleep=asyncio.sleep):
        self.http, self.settings, self.sleep = http, settings, sleep
        token = settings.hubspot_access_token
        if token is None or not token.get_secret_value().strip():
            raise ValueError("HUBSPOT_ACCESS_TOKEN is required when CRM is enabled")
        self.token = token
        self.schema_verified = False
        self.account_verified = False
        self.contact_ids: dict[str, str] = {}

    async def request(self, method: str, path: str, body: dict | None = None) -> dict:
        if not path.startswith("/crm/") and path!='/account-info/v3/details':
            raise ValueError("Unsupported HubSpot API path")
        for attempt in range(5):
            try:
                response = await self.http.request(
                    method, API_BASE_URL + path, json=body,
                    headers={"Authorization": "Bearer " + self.token.get_secret_value(), "Content-Type": "application/json"},
                    timeout=httpx.Timeout(15, connect=5), follow_redirects=False)
            except httpx.HTTPError:
                # Do not repeat an ambiguous create inline. The durable job uses
                # unique CRM properties to recover existing records on its retry.
                raise CRMError("hubspot_transport_failure") from None
            if response.status_code>=500 and method=='POST' and path in {'/crm/v3/objects/companies','/crm/v3/objects/contacts','/crm/v3/objects/deals'}:
                raise CRMError('hubspot_create_outcome_uncertain')
            if response.status_code == 429 or response.status_code >= 500:
                delay = max(retry_seconds(response.headers.get("Retry-After")), (2 ** attempt) + random.uniform(0, .25))
                if attempt == 4 or delay > 30:
                    raise CRMError("hubspot_rate_limited" if response.status_code == 429 else "hubspot_server_failure", retry_after=delay)
                await self.sleep(delay)
                continue
            if response.status_code == 403:
                logger.warning("HubSpot scope access denied; check Companies/Contacts object and schema scopes. Logistics continues; CRM jobs remain durable.")
                raise CRMError("hubspot_http_403", retryable=False)
            if not 200 <= response.status_code < 300:
                raise CRMError(f"hubspot_http_{response.status_code}", retryable=response.status_code in {408, 409, 423})
            try:
                data = response.json() if response.content else {}
            except ValueError:
                raise CRMError("hubspot_invalid_response") from None
            if not isinstance(data, dict) or data.get("errors") or data.get("status") == "PENDING":
                raise CRMError("hubspot_incomplete_batch")
            return data
        raise CRMError("hubspot_retry_exhausted")

    async def verify_schema(self):
        if self.schema_verified:
            return
        await self.verify_account()
        definitions = [
            ("companies", "veloce_tenant_id", True), ("companies", "veloce_vat_number", False),
            ("companies", "veloce_package_count", False), ("companies", "veloce_total_spend", False),
            ("companies", "veloce_currency", False),
            ("companies", "veloce_total_shipments", False), ("companies", "veloce_wallet_balance", False)]
        if self.settings.hubspot_upsell_enabled:
            definitions.append(('deals','veloce_milestone_id',True))
        for object_type, name, unique in definitions:
            definition = await self.request("GET", f"/crm/v3/properties/{object_type}/{name}")
            if unique and definition.get("hasUniqueValue") is not True:
                raise CRMError("hubspot_unique_property_required", retryable=False)
            numeric=name in {'veloce_package_count','veloce_total_shipments','veloce_total_spend','veloce_wallet_balance'}
            if definition.get('type')!=('number' if numeric else 'string') or definition.get('fieldType')!=('number' if numeric else 'text'):
                raise CRMError('hubspot_property_type_mismatch',retryable=False)
            metadata=definition.get('modificationMetadata') or {}
            if not isinstance(metadata,dict):
                raise CRMError('hubspot_invalid_property_metadata',retryable=False)
            if definition.get('archived') or metadata.get('readOnlyValue'):
                raise CRMError('hubspot_property_not_writable',retryable=False)
        await self.request('GET','/crm/v3/properties/contacts/email')
        if self.settings.hubspot_upsell_enabled:
            pipeline = await self.request("GET", "/crm/v3/pipelines/deals/" + self.settings.hubspot_upsell_pipeline_id)
            if not any(str(stage.get("id")) == self.settings.hubspot_upsell_stage_id for stage in pipeline.get("stages", [])):
                raise CRMError("hubspot_stage_not_in_pipeline", retryable=False)
        self.schema_verified = True

    async def verify_account(self):
        if self.account_verified:return
        if self.settings.hubspot_expected_portal_id is None:
            raise CRMError('hubspot_expected_account_required',retryable=False)
        details=await self.request('GET','/account-info/v3/details')
        if str(details.get('portalId'))!=str(self.settings.hubspot_expected_portal_id):
            raise CRMError('hubspot_account_mismatch',retryable=False)
        if self.settings.hubspot_environment=='SANDBOX' and details.get('accountType') not in {'SANDBOX','DEVELOPER_TEST'}:
            raise CRMError('hubspot_test_account_required',retryable=False)
        if self.settings.hubspot_environment=='PRODUCTION' and details.get('accountType')!='STANDARD':
            raise CRMError('hubspot_production_account_required',retryable=False)
        self.account_verified=True

    async def find(self, object_type: str, property_name: str, value: str) -> str | None:
        data = await self.request("POST", f"/crm/v3/objects/{object_type}/search", {
            "filterGroups": [{"filters": [{"propertyName": property_name, "operator": "EQ", "value": value}]}], "limit": 2})
        records = data.get("results")
        if not isinstance(records, list) or len(records) > 1:
            raise CRMError("hubspot_ambiguous_identity", retryable=False)
        return self.record_id(records[0]) if records else None

    @staticmethod
    def record_id(data: dict) -> str:
        value = data.get("id")
        if not isinstance(value, (str, int)) or not str(value).isdigit():
            raise CRMError("hubspot_invalid_record_id")
        return str(value)

    async def upsert(self, object_type: str, key: str, value: str, properties: dict) -> str:
        record_id = await self.find(object_type, key, value)
        if record_id:
            await self.request("PATCH", f"/crm/v3/objects/{object_type}/{record_id}", {"properties": properties})
            return record_id
        created = await self.request("POST", f"/crm/v3/objects/{object_type}", {"properties": properties})
        return self.record_id(created)

    async def onboard(self, tenant_id: UUID, company_name: str, email: str, vat_number: str, *, address:dict|None=None, existing_company_id: str | None = None) -> str:
        validate_profile(company_name, email, vat_number)
        await self.verify_schema()
        properties={"name": company_name, "veloce_tenant_id": str(tenant_id), "veloce_vat_number": vat_number}
        if address:
            for source,target in [('line1','street'),('city','city'),('postal_code','zip'),('country_code','country')]:
                value=address.get(source)
                if isinstance(value,str) and value.strip() and len(value)<=250 and not any(ord(c)<32 for c in value):properties[target]=value.strip()
        if existing_company_id:
            company_id = self.record_id({'id': existing_company_id})
            await self.request('PATCH', f'/crm/v3/objects/companies/{company_id}', {'properties': properties})
        else:
            company_id = await self.upsert("companies", "veloce_tenant_id", str(tenant_id),properties)
        contact_id = await self.upsert("contacts", "email", email, {"email": email})
        await self.request("POST", "/crm/v3/associations/contacts/companies/batch/create", {
            "inputs": [{"from": {"id": contact_id}, "to": {"id": company_id}, "type": "contact_to_company"}]})
        self.contact_ids[str(tenant_id)] = contact_id
        return company_id

    async def milestone(self, tenant_id: UUID, company_id: str, company_name: str, count: int, spend: Decimal, currency: str, wallet_balance: Decimal | None = None):
        await self.verify_schema()
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("Package count must be a nonnegative integer")
        amount = spend_string(spend)
        properties = {"veloce_package_count": str(count), "veloce_total_shipments": str(count),
                      "veloce_total_spend": amount, "veloce_currency": currency}
        if wallet_balance is not None:
            properties["veloce_wallet_balance"] = spend_string(wallet_balance)
        await self.request("PATCH", f"/crm/v3/objects/companies/{company_id}", {"properties": properties})
        if count <= 50 or not self.settings.hubspot_upsell_enabled:
            return None
        # Unique milestone identity prevents repeated upsells, including recovery
        # after a network timeout or a process crash after the remote create.
        key = str(tenant_id) + ":high-volume-51"
        deal_id = await self.find("deals", "veloce_milestone_id", key)
        if deal_id is None:
            data = await self.request("POST", "/crm/v3/objects/deals", {"properties": {
                "dealname": company_name + " — High-Volume Upsell", "pipeline": self.settings.hubspot_upsell_pipeline_id,
                "dealstage": self.settings.hubspot_upsell_stage_id, "veloce_milestone_id": key}})
            deal_id = self.record_id(data)
        await self.request("POST", "/crm/v3/associations/deals/companies/batch/create", {
            "inputs": [{"from": {"id": deal_id}, "to": {"id": company_id}, "type": "deal_to_company"}]})
        return deal_id


class HubSpotService:
    def __init__(self, pool, client: HubSpotClient):
        self.pool, self.client = pool, client

    async def enqueue(self, tenant_id: UUID):
        async with self.pool.acquire() as connection:
            if not await connection.fetchval("SELECT EXISTS(SELECT 1 FROM public.tenants WHERE tenant_id=$1)", tenant_id):
                raise HTTPException(404, "Tenant not found")
            await connection.execute("""INSERT INTO public.hubspot_sync_jobs(tenant_id) VALUES ($1)
                ON CONFLICT (tenant_id) DO UPDATE SET revision=hubspot_sync_jobs.revision+1,
                attempts=0,next_attempt_at=now(),last_error=NULL,blocked=false""", tenant_id)

    async def sync(self, tenant_id: UUID, company_name: str, email: str, vat_number: str):
        validate_profile(company_name, email, vat_number)
        # Public utility queues only canonical tenant data, never caller-provided
        # changes to another tenant's contact details.
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow("SELECT company_name,company_profile,billing_email,vat_registration_number FROM public.tenants WHERE tenant_id=$1", tenant_id)
        if row is None:
            raise HTTPException(404, "Tenant not found")
        profile = json.loads(row["company_profile"]) if isinstance(row["company_profile"], str) else row["company_profile"]
        if (company_name, email, vat_number) != (row["company_name"], row.get('billing_email') or profile.get("billing_email"),row.get('vat_registration_number') or profile.get("tax_id") or ""):
            raise ValueError("CRM profile must match the stored tenant profile")
        await self.enqueue(tenant_id)

    async def log_activity(self, company_name: str, package_count: int, total_spend: Decimal):
        spend_string(total_spend)
        if isinstance(package_count, bool) or not isinstance(package_count, int) or package_count < 0:
            raise ValueError("Package count must be a nonnegative integer")
        # Company names are not unique tenant identifiers. Fail closed on an
        # ambiguous name; jobs always carry the actual tenant UUID.
        async with self.pool.acquire() as connection:
            rows = await connection.fetch("SELECT tenant_id FROM public.tenants WHERE company_name=$1 LIMIT 2", company_name)
            if len(rows) != 1:
                raise ValueError("Company name must identify exactly one tenant")
            tenant_id = rows[0]["tenant_id"]
            totals = await self.totals(connection, tenant_id)
        if totals["package_count"] != package_count or totals["total_spend"] != total_spend:
            raise ValueError("Milestones must match confirmed shipment totals")
        await self.enqueue(tenant_id)

    async def totals(self, connection, tenant_id):
        row = await connection.fetchrow("""SELECT coalesce(sum(s.parcel_count),0)::bigint AS package_count,
            coalesce(sum(s.final_client_price),0)::numeric AS total_spend,
            count(*) FILTER (WHERE s.currency<>t.default_currency)::int AS mixed_currency
            FROM public.shipments s JOIN public.tenants t ON t.tenant_id=s.tenant_id
            WHERE s.tenant_id=$1 AND s.status::text IN ('BOOKED','MANIFESTED','DISPATCHED','IN_TRANSIT','EXCEPTION','DELIVERED')""", tenant_id)
        if row["mixed_currency"]:
            raise CRMError("crm_mixed_currency_requires_conversion", retryable=False)
        return row

    async def process(self, tenant_id: UUID):
        # Session advisory lock serializes this tenant across worker processes.
        # No SQL transaction stays open while making HTTP calls or sleeping.
        async with self.pool.acquire() as connection:
            key = "hubspot:" + str(tenant_id)
            if not await connection.fetchval("SELECT pg_try_advisory_lock(hashtextextended($1,0))", key):
                return
            try:
                job = await connection.fetchrow("SELECT revision,attempts FROM public.hubspot_sync_jobs WHERE tenant_id=$1 AND NOT blocked AND next_attempt_at<=now()", tenant_id)
                if job is None:
                    return
                try:
                    tenant = await connection.fetchrow("SELECT company_name,company_profile,default_currency,billing_email,vat_registration_number,billing_address,is_sandbox FROM public.tenants WHERE tenant_id=$1", tenant_id)
                    if tenant is None:
                        raise CRMError("crm_tenant_missing", retryable=False)
                    settings=getattr(self.client,'settings',None)
                    if settings and bool(tenant['is_sandbox'])!=(settings.hubspot_environment=='SANDBOX'):
                        raise CRMError('crm_tenant_environment_mismatch',retryable=False)
                    profile = json.loads(tenant["company_profile"]) if isinstance(tenant["company_profile"], str) else tenant["company_profile"]
                    try:
                        email=tenant.get('billing_email') or profile.get('billing_email','')
                        vat=tenant.get('vat_registration_number') or profile.get('tax_id') or ''
                        address=tenant.get('billing_address')
                        address=json.loads(address) if isinstance(address,str) else address
                        extra={'address':address} if address else {}
                        if settings:
                            linked = await connection.fetchrow('SELECT company_id FROM public.hubspot_tenant_links WHERE tenant_id=$1 AND portal_id=$2', tenant_id,settings.hubspot_expected_portal_id)
                            if linked:
                                extra['existing_company_id'] = linked['company_id']
                        company_id = await self.client.onboard(tenant_id, tenant["company_name"],email,vat,**extra)
                    except ValueError:
                        raise CRMError("crm_tenant_profile_invalid", retryable=False) from None
                    contact_id = getattr(self.client, 'contact_ids', {}).pop(str(tenant_id), None)
                    if contact_id:
                        await connection.execute("""INSERT INTO public.hubspot_tenant_links(tenant_id,company_id,contact_id,portal_id)
                            VALUES($1,$2,$3,$4) ON CONFLICT(tenant_id) DO UPDATE SET
                            company_id=$2,contact_id=$3,portal_id=$4,last_synced_at=now()""",
                            tenant_id,company_id,contact_id,settings.hubspot_expected_portal_id)
                        await connection.execute("""UPDATE public.tenants SET company_profile=company_profile ||
                            jsonb_build_object('hubspot',jsonb_build_object('portal_id',$2::text,'company_id',$3::text,'contact_id',$4::text))
                            WHERE tenant_id=$1 AND company_profile->'hubspot' IS DISTINCT FROM
                            jsonb_build_object('portal_id',$2::text,'company_id',$3::text,'contact_id',$4::text)""",
                            tenant_id, str(settings.hubspot_expected_portal_id), company_id, contact_id)
                    if settings:
                        async with connection.transaction(isolation='repeatable_read', readonly=True):
                            totals = await self.totals(connection, tenant_id)
                            wallet = await connection.fetchrow("SELECT balance,currency FROM public.wallets WHERE tenant_id=$1", tenant_id)
                    else:
                        totals = await self.totals(connection, tenant_id)
                        wallet = None
                    if settings and (wallet is None or wallet['currency'] != tenant['default_currency']):
                        raise CRMError('crm_wallet_currency_mismatch', retryable=False)
                    try:
                        deal_id = await self.client.milestone(tenant_id, company_id, tenant["company_name"], totals["package_count"], totals["total_spend"], tenant["default_currency"], **({"wallet_balance": wallet["balance"]} if wallet else {}))
                    except ValueError:
                        raise CRMError("crm_shipment_totals_invalid", retryable=False) from None
                    await connection.execute("""INSERT INTO public.hubspot_tenant_links(tenant_id,company_id,upsell_deal_id,last_synced_at)
                        VALUES($1,$2,$3,now()) ON CONFLICT(tenant_id) DO UPDATE SET
                        company_id=$2,upsell_deal_id=coalesce($3,hubspot_tenant_links.upsell_deal_id),last_synced_at=now()""", tenant_id, company_id, deal_id)
                    if contact_id:
                        await connection.execute("UPDATE public.hubspot_tenant_links SET contact_id=$2,portal_id=$3 WHERE tenant_id=$1", tenant_id,contact_id,settings.hubspot_expected_portal_id)
                    await connection.execute("DELETE FROM public.hubspot_sync_jobs WHERE tenant_id=$1 AND revision=$2", tenant_id, job["revision"])
                except CRMError as exc:
                    attempts = job["attempts"] + 1
                    delay = max(exc.retry_after, min(3600, 2 ** min(attempts, 12)))
                    await connection.execute("""UPDATE public.hubspot_sync_jobs SET attempts=$3,last_error=$4,
                        blocked=$5,next_attempt_at=now()+$6*interval '1 second'
                        WHERE tenant_id=$1 AND revision=$2""", tenant_id, job["revision"], attempts,
                        exc.code, not exc.retryable or attempts >= 12, float(delay))
                    logger.warning("HubSpot sync deferred: %s", exc.code)
            finally:
                await connection.execute("SELECT pg_advisory_unlock(hashtextextended($1,0))", key)

    async def worker(self):
        while True:
            try:
                async with self.pool.acquire() as connection:
                    jobs = await connection.fetch('''SELECT j.tenant_id FROM public.hubspot_sync_jobs j JOIN public.tenants t ON t.tenant_id=j.tenant_id
                        WHERE NOT j.blocked AND j.next_attempt_at<=now() AND t.is_sandbox=$1 ORDER BY j.next_attempt_at LIMIT 20''',self.client.settings.hubspot_environment=='SANDBOX')
                if self.client.settings.hubspot_provisioning_enabled:
                    from backend.hubspot_provisioning import process_pending
                    await process_pending(self)
                for job in jobs:
                    try:
                        await self.process(job["tenant_id"])
                    except Exception:
                        logger.warning("HubSpot worker deferred an internal/database failure")
            except Exception:
                logger.warning("HubSpot queue unavailable")
            await asyncio.sleep(5)


def configure_hubspot_service(service: HubSpotService | None):
    global _service
    _service = service


async def sync_tenant_to_hubspot(tenant_id: UUID, company_name: str, email: str, vat_number: str):
    if _service is None:
        raise HTTPException(503, "HubSpot integration is disabled")
    await _service.sync(tenant_id, company_name, email, vat_number)


async def log_shipping_activity(company_name: str, package_count: int, total_spend: Decimal):
    if _service is None:
        raise HTTPException(503, "HubSpot integration is disabled")
    await _service.log_activity(company_name, package_count, total_spend)


class SyncTenantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID


def build_router(authenticate):
    router = APIRouter(tags=["HubSpot CRM"])
    from backend.hubspot_provisioning import webhook
    router.add_api_route("/api/v1/integrations/hubspot-webhook", webhook, methods=["POST"], status_code=202)

    @router.post("/api/v1/crm/sync-tenant", status_code=202)
    async def sync_tenant(body: SyncTenantInput, request: Request, background_tasks: BackgroundTasks, context: Any = Depends(authenticate)):
        if context.tenant_id != body.tenant_id:
            raise HTTPException(403, "Tenant mismatch")
        if context.role not in {"OWNER", "ADMIN"}:
            raise HTTPException(403, "Tenant administrator required")
        service = getattr(request.app.state, "hubspot", None)
        if service is None:
            raise HTTPException(503, "HubSpot integration is disabled")
        try:
            await service.enqueue(body.tenant_id)
        except asyncpg.PostgresError:
            raise HTTPException(503, "CRM queue unavailable") from None
        background_tasks.add_task(safe_process, service, body.tenant_id)
        return {"tenant_id": str(body.tenant_id), "status": "QUEUED"}

    from backend.admin_portal import authenticate_platform_owner

    @router.get("/api/v1/admin/integrations/alerts")
    async def integration_alerts(request: Request, owner: Any = Depends(authenticate_platform_owner)):
        # CRM incidents are tenant-level; never forge a shipment-linked support ticket.
        try:
            async with request.app.state.finance.pool.acquire() as connection:
                rows = await connection.fetch("""SELECT tenant_id,last_error,attempts,blocked,next_attempt_at
                    FROM public.hubspot_sync_jobs WHERE last_error IS NOT NULL
                    ORDER BY next_attempt_at DESC LIMIT 100""")
        except asyncpg.PostgresError:
            raise HTTPException(503, "Integration alerts are temporarily unavailable") from None
        alerts = []
        for row in rows:
            code = row["last_error"]
            remedy = (
                "Grant Companies and Contacts read/write permissions plus the required CRM schema permissions in the correct HubSpot test account; then requeue tenant synchronization."
                if code == "hubspot_http_403" else
                "Verify the configured HubSpot account, environment and schema, resolve the reported integration error, then requeue tenant synchronization."
            )
            alerts.append({"tenant_id": str(row["tenant_id"]), "source": "HUBSPOT",
                "code": code, "status": "BLOCKED" if row["blocked"] else "RETRY_PENDING",
                "attempts": row["attempts"], "ai_summary": remedy,
                "ai_method": "DETERMINISTIC_REMEDIATION", "next_attempt_at": row["next_attempt_at"].isoformat()})
        return {"alerts": alerts, "limit": 100}

    return router


async def safe_process(service: HubSpotService, tenant_id: UUID):
    """BackgroundTasks accelerator; the durable worker recovers failures."""
    try:
        await service.process(tenant_id)
    except Exception:
        logger.warning("Optional CRM background task deferred; durable job retained")


async def sync_new_tenant_to_crm(tenant_id: UUID, company_name: str, email: str):
    if _service is None:
        raise HTTPException(503, "HubSpot integration is disabled")
    async with _service.pool.acquire() as connection:
        vat = await connection.fetchval("SELECT coalesce(nullif(vat_registration_number,''),company_profile->>'tax_id','') FROM public.tenants WHERE tenant_id=$1", tenant_id)
    await _service.sync(tenant_id, company_name, email, vat or "")
    await safe_process(_service, tenant_id)


async def sync_tenant_metrics_to_crm(tenant_id: UUID):
    if _service is None:
        return
    try:
        await _service.enqueue(tenant_id)
        await safe_process(_service, tenant_id)
    except Exception:
        logger.warning("Optional CRM metrics task deferred")
