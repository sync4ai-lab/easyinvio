"""Private, versioned tenant registries. No bookings, wallet changes or AI calls."""
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from backend.ai_engine import strict_decimal, country_code


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_version: int | None = Field(default=None, strict=True, ge=1)


class ProductInput(Input):
    sku: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=3, max_length=500)
    unit_weight_kg: Decimal = Field(gt=0, le=30000, decimal_places=3)
    unit_value: Decimal = Field(gt=0, le=1000000, decimal_places=2)
    currency: Literal['GBP', 'EUR', 'USD'] = 'GBP'
    origin_country: str
    hs_code: str | None = Field(default=None, pattern=r'^([0-9]{6}|[0-9]{8}|[0-9]{10})$')
    hs_reviewed: bool = Field(default=False, strict=True)

    @field_validator('unit_weight_kg', 'unit_value', mode='before')
    @classmethod
    def decimals(cls, value):
        return strict_decimal(value)

    @field_validator('origin_country')
    @classmethod
    def country(cls, value):
        return country_code(value)

    @model_validator(mode='after')
    def review(self):
        if self.hs_reviewed and self.hs_code is None:
            raise ValueError('A reviewed classification requires an HS code')
        return self


class ArchiveInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(strict=True, ge=1)


TABLES = {'addresses': 'tenant_catalog_addresses', 'contacts': 'tenant_catalog_contacts', 'products': 'tenant_catalog_products'}
READ_ROLES = {'OWNER', 'ADMIN', 'DISPATCHER', 'ACCOUNTANT'}
WRITE_ROLES = {'OWNER', 'ADMIN', 'DISPATCHER'}


def permission(context, write=False):
    if context.role not in (WRITE_ROLES if write else READ_ROLES):
        raise HTTPException(403, 'Your workspace role does not allow this catalog action')


def public_record(row):
    result = {key: value for key, value in dict(row).items() if key not in
        {'tenant_id', 'created_by', 'updated_by', 'hs_reviewed_by', 'archived_at'}}
    if isinstance(result.get('address'), str):
        result['address'] = json.loads(result['address'])
    if 'hs_reviewed_at' in result:
        result['hs_reviewed'] = result['hs_reviewed_at'] is not None
    for key, value in result.items():
        if isinstance(value, (Decimal, UUID)):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
    return result


def database_error(error):
    if isinstance(error, asyncpg.UndefinedTableError):
        return HTTPException(503, 'Catalog storage is not ready. Ask your workspace administrator to complete the settings setup.')
    if isinstance(error, asyncpg.UniqueViolationError):
        return HTTPException(409, 'This SKU or default address already exists. Refresh the catalog and check the saved record.')
    return HTTPException(503, 'Catalog storage is temporarily unavailable. Your shipment has not been changed.')


class TenantCatalogService:
    def __init__(self, pool):
        self.pool = pool

    async def product_by_sku(self, context, sku):
        permission(context)
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow('SELECT * FROM public.tenant_catalog_products WHERE tenant_id=$1 AND lower(sku)=lower($2) AND archived_at IS NULL', context.tenant_id, sku)
        if row is None:
            raise HTTPException(404, 'SKU not found in this workspace')
        return public_record(row)

    async def list(self, context, kind, q='', offset=0, limit=50, address_role=None):
        permission(context)
        table = TABLES[kind]
        pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        search = "(sku ILIKE $2 OR description ILIKE $2)" if kind == 'products' else "(label ILIKE $2 OR address->>'name' ILIKE $2 OR address->>'company' ILIKE $2 OR address->>'city' ILIKE $2)"
        params = [context.tenant_id, pattern, limit + 1, offset]
        role_filter = ''
        if address_role is not None:
            role_filter = ' AND address_role=$5'
            params.append(address_role)
        ordering = 'is_default DESC,updated_at DESC,id' if kind == 'addresses' else 'updated_at DESC,id'
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(f'SELECT * FROM public.{table} WHERE tenant_id=$1 AND archived_at IS NULL AND {search}{role_filter} ORDER BY {ordering} LIMIT $3 OFFSET $4', *params)
        return {'items': [public_record(row) for row in rows[:limit]], 'has_more': len(rows)>limit, 'offset': offset, 'limit': limit}

    async def save(self, context, kind, body, record_id=None):
        permission(context, True)
        table = TABLES[kind]
        if record_id is not None and body.expected_version is None:
            raise HTTPException(422, 'Refresh the record before editing it')
        if record_id is None and body.expected_version is not None:
            raise HTTPException(422, 'A new record cannot have an existing version')
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                if kind == 'addresses':
                    await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", 'catalog-addresses:' + str(context.tenant_id))
                if record_id is not None:
                    existing = await connection.fetchrow(f'SELECT version FROM public.{table} WHERE tenant_id=$1 AND id=$2 AND archived_at IS NULL FOR UPDATE', context.tenant_id, record_id)
                    if existing is None:
                        raise HTTPException(404, 'Catalog record not found in this workspace')
                    if existing['version'] != body.expected_version:
                        raise HTTPException(409, 'Someone updated this record. Refresh it before saving your changes.')
                identifier = record_id or uuid4()
                values = body.model_dump(exclude={'expected_version'})
                if kind == 'products':
                    reviewed = values.pop('hs_reviewed')
                    values['hs_reviewed_at'] = datetime.now(timezone.utc) if reviewed else None
                    values['hs_reviewed_by'] = context.user_id if reviewed else None
                else:
                    values['address'] = json.dumps(body.address.model_dump(mode='json'))
                if kind == 'addresses' and body.is_default:
                    await connection.execute('''UPDATE public.tenant_catalog_addresses SET is_default=false,version=version+1,updated_by=$3,updated_at=now()
                        WHERE tenant_id=$1 AND address_role=$2 AND is_default AND archived_at IS NULL AND id<>$4''', context.tenant_id, body.address_role, context.user_id, identifier)
                columns = list(values)
                if record_id is None:
                    columns = ['id', 'tenant_id', 'created_by', 'updated_by'] + columns
                    params = [identifier, context.tenant_id, context.user_id, context.user_id] + list(values.values())
                    row = await connection.fetchrow(f"INSERT INTO public.{table} ({','.join(columns)}) VALUES ({','.join('$'+str(i+1) for i in range(len(params)))}) RETURNING *", *params)
                else:
                    params = [context.tenant_id, identifier, context.user_id] + list(values.values())
                    assignments = ','.join(column+'=$'+str(i+4) for i, column in enumerate(columns))
                    row = await connection.fetchrow(f'UPDATE public.{table} SET {assignments},updated_by=$3,updated_at=now(),version=version+1 WHERE tenant_id=$1 AND id=$2 RETURNING *', *params)
                return public_record(row)

    async def archive(self, context, kind, identifier, version):
        permission(context, True)
        table = TABLES[kind]
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                if kind == 'addresses':
                    await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", 'catalog-addresses:' + str(context.tenant_id))
                row = await connection.fetchrow(f'SELECT version FROM public.{table} WHERE tenant_id=$1 AND id=$2 AND archived_at IS NULL FOR UPDATE', context.tenant_id, identifier)
                if row is None:
                    raise HTTPException(404, 'Catalog record not found in this workspace')
                if row['version'] != version:
                    raise HTTPException(409, 'Record changed; refresh before archiving it')
                default = ',is_default=false' if kind == 'addresses' else ''
                await connection.execute(f'UPDATE public.{table} SET archived_at=now(),updated_at=now(),updated_by=$3,version=version+1{default} WHERE tenant_id=$1 AND id=$2', context.tenant_id, identifier, context.user_id)
        return {'archived': True, 'id': str(identifier)}


def build_router(authenticate, address_model):
    router = APIRouter(prefix='/api/v1/catalog', tags=['Private workspace catalogs'])

    class ContactInput(Input):
        label: str = Field(min_length=1, max_length=100)
        address: address_model

    class AddressInput(ContactInput):
        address_role: Literal['SENDER','RETURN','PICKUP','INVOICE']
        is_default: bool = Field(default=False, strict=True)

    def service(request):
        finance = getattr(request.app.state, 'finance', None)
        if finance is None:
            raise HTTPException(503, 'Sign in to a configured workspace to use saved catalogs')
        return TenantCatalogService(finance.pool)

    def routes(kind, model):
        async def listing(request: Request, q: str = Query(default='', max_length=100), offset: int = Query(default=0, ge=0, le=10000), limit: int = Query(default=50, ge=1, le=100), address_role: Literal['SENDER','RETURN','PICKUP','INVOICE'] | None = None, context=Depends(authenticate)):
            permission(context)
            if address_role is not None and kind != 'addresses':
                raise HTTPException(422, 'Address roles apply only to warehouse addresses')
            try:
                return await service(request).list(context, kind, q, offset, limit, address_role)
            except asyncpg.PostgresError as error:
                raise database_error(error) from None

        async def create(body, request: Request, context=Depends(authenticate)):
            permission(context, True)
            try:
                return await service(request).save(context, kind, body)
            except asyncpg.PostgresError as error:
                raise database_error(error) from None

        async def update(record_id: UUID, body, request: Request, context=Depends(authenticate)):
            permission(context, True)
            try:
                return await service(request).save(context, kind, body, record_id)
            except asyncpg.PostgresError as error:
                raise database_error(error) from None

        async def archive(record_id: UUID, body: ArchiveInput, request: Request, context=Depends(authenticate)):
            permission(context, True)
            try:
                return await service(request).archive(context, kind, record_id, body.expected_version)
            except asyncpg.PostgresError as error:
                raise database_error(error) from None

        create.__annotations__['body'] = model
        update.__annotations__['body'] = model
        router.add_api_route('/'+kind, listing, methods=['GET'], name='list_'+kind)
        router.add_api_route('/'+kind, create, methods=['POST'], status_code=201, name='create_'+kind)
        router.add_api_route('/'+kind+'/{record_id}', update, methods=['PUT'], name='update_'+kind)
        router.add_api_route('/'+kind+'/{record_id}', archive, methods=['DELETE'], name='archive_'+kind)

    routes('addresses', AddressInput)
    routes('contacts', ContactInput)
    routes('products', ProductInput)

    @router.get('/products/by-sku/{sku:path}')
    async def by_sku(sku: str, request: Request, context=Depends(authenticate)):
        if not 1 <= len(sku) <= 200:
            raise HTTPException(422, 'Enter a valid SKU')
        try:
            return await service(request).product_by_sku(context, sku)
        except asyncpg.PostgresError as error:
            raise database_error(error) from None
    return router
