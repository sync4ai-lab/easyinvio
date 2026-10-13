"""Native return tracking without forward fulfillment, refunds or restocking."""
import json
import re
import httpx
from fastapi import HTTPException
from backend.ecommerce_connectors import ShopifyFulfillment


class ShopifyReturnTracking(ShopifyFulfillment):
    async def inspect(self, body):
        reference = body.get('store_return_reference', '')
        if not re.fullmatch(r'gid://shopify/ReverseFulfillmentOrder/[1-9][0-9]{0,30}', reference):
            raise HTTPException(409, 'A verified Shopify reverse fulfillment order reference is required')
        result = await self.graphql('''query EasyInvioReturn($id:ID!) {
            reverseFulfillmentOrder(id:$id) { id status order { id }
              lineItems(first:100) { pageInfo { hasNextPage } nodes { id totalQuantity } }
              reverseDeliveries(first:100) { pageInfo { hasNextPage } nodes { id
                deliverable { ... on ReverseDeliveryShippingDeliverable { tracking { number url } } } } }
            } }''', {'id': reference})
        reverse = result.get('reverseFulfillmentOrder')
        if not reverse or (reverse.get('order') or {}).get('id') != 'gid://shopify/Order/' + body['store_order_id']:
            raise HTTPException(409, 'Return reference does not belong to the original storefront order')
        if reverse['lineItems']['pageInfo']['hasNextPage'] or reverse['reverseDeliveries']['pageInfo']['hasNextPage']:
            raise HTTPException(409, 'Return allocation requires explicit pagination review')
        return reverse

    async def deliver(self, body, *, verify_only=False):
        if body.get('tracking_lifecycle_type') != 'RETURN_SHIPMENT':
            raise HTTPException(409, 'Reverse delivery requires a return shipment')
        reverse = await self.inspect(body)
        for delivery in reverse['reverseDeliveries']['nodes']:
            if ((delivery.get('deliverable') or {}).get('tracking') or {}).get('number') == body['tracking_number']:
                return {'reverse_delivery_id': delivery['id'], 'store_return_reference': reverse['id'],
                        'return_tracking_attached': True, 'original_fulfillment_changed': False, 'replayed': True}
        if verify_only:
            raise HTTPException(409, 'Return tracking is not confirmed; submission hold remains')
        if reverse['status'] != 'OPEN' or reverse['reverseDeliveries']['nodes']:
            raise HTTPException(409, 'Closed or partially dispatched returns require explicit warehouse allocation')
        lines = reverse['lineItems']['nodes']
        if not lines or any(type(line['totalQuantity']) is not int or line['totalQuantity'] <= 0 for line in lines):
            raise HTTPException(409, 'Return quantities require warehouse review')
        if body.get('return_quantity') != sum(line['totalQuantity'] for line in lines):
            raise HTTPException(409, 'Return quantities differ from the packed return shipment; prepare an accurately allocated return first')
        tracking = {'number': body['tracking_number']}
        if body.get('tracking_url'):
            tracking['url'] = body['tracking_url']
        result = await self.graphql('''mutation EasyInvioReverse($id:ID!,$lines:[ReverseDeliveryLineItemInput!]!,$tracking:ReverseDeliveryTrackingInput!) {
          reverseDeliveryCreateWithShipping(reverseFulfillmentOrderId:$id,reverseDeliveryLineItems:$lines,
              trackingInput:$tracking,notifyCustomer:false) { reverseDelivery { id } userErrors { field message } }
        }''', {'id': reverse['id'], 'lines': [{'reverseFulfillmentOrderLineItemId': line['id'], 'quantity': line['totalQuantity']} for line in lines], 'tracking': tracking})
        created = result['reverseDeliveryCreateWithShipping']
        if created.get('userErrors') or not created.get('reverseDelivery'):
            raise HTTPException(409, 'Return tracking requires store reconciliation')
        return {'reverse_delivery_id': created['reverseDelivery']['id'], 'store_return_reference': reverse['id'],
                'return_tracking_attached': True, 'original_fulfillment_changed': False, 'replayed': False}


async def sync_return_jobs(service):
    """Commit the submission fence before mutation; recovery only verifies GET state."""
    from backend.store_connections import resolve_connector
    async with service.pool.acquire() as connection:
        jobs = await connection.fetch('''SELECT o.id,o.tenant_id,o.shipment_id,o.store_id,o.payload,o.store_sync_error_code
            FROM public.ecommerce_tracking_outbox o JOIN public.ecommerce_stores s ON s.tenant_id=o.tenant_id AND s.id=o.store_id
            WHERE o.tracking_lifecycle_type='RETURN_SHIPMENT' AND o.status='RECONCILIATION_REQUIRED' AND s.is_active
              AND o.attempts<30 AND o.store_sync_error_code IN ('RETURN_ADAPTER_UPGRADE_REQUIRED','RETURN_SUBMITTED')
            ORDER BY o.created_at,o.id LIMIT 50''')
    for job in jobs:
        body = json.loads(job['payload']) if isinstance(job['payload'], str) else job['payload']
        config = await resolve_connector(service, job['store_id'])
        if not config or config.tenant_id != job['tenant_id']:
            continue
        code = None
        if config.platform != 'SHOPIFY':
            code = 'RETURN_NATIVE_PROGRAM_NOT_CONFIGURED'
        elif not body.get('store_return_reference'):
            code = 'RETURN_REFERENCE_REQUIRED'
        if code:
            async with service.pool.acquire() as connection:
                await connection.execute('UPDATE public.ecommerce_tracking_outbox SET store_sync_error_code=$3 WHERE tenant_id=$1 AND id=$2', job['tenant_id'], job['id'], code)
            continue
        if not config.live_delivery:
            continue
        verify_only = job['store_sync_error_code'] == 'RETURN_SUBMITTED'
        if verify_only:
            async with service.pool.acquire() as connection:
                await connection.execute('UPDATE public.ecommerce_tracking_outbox SET attempts=attempts+1 WHERE tenant_id=$1 AND id=$2',job['tenant_id'],job['id'])
        if not verify_only:
            async with service.pool.acquire() as connection:
                claimed = await connection.fetchval("UPDATE public.ecommerce_tracking_outbox SET store_sync_error_code='RETURN_SUBMITTED',attempts=attempts+1 WHERE tenant_id=$1 AND id=$2 AND store_sync_error_code='RETURN_ADAPTER_UPGRADE_REQUIRED' RETURNING id", job['tenant_id'], job['id'])
            if not claimed:
                continue
        try:
            response = await ShopifyReturnTracking(service.client, config).deliver(body, verify_only=verify_only)
        except (HTTPException,httpx.HTTPError,ValueError,KeyError,TypeError):
            continue
        async with service.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("UPDATE public.ecommerce_tracking_outbox SET status='DELIVERED',delivered_at=now(),response=$3::jsonb,store_sync_error_code=NULL WHERE tenant_id=$1 AND id=$2 AND store_sync_error_code='RETURN_SUBMITTED'", job['tenant_id'], job['id'], json.dumps(response))
                await connection.execute("UPDATE public.shipments SET store_return_status=CASE WHEN status IN ('IN_TRANSIT','EXCEPTION') THEN 'IN_TRANSIT' WHEN status='DELIVERED' THEN 'RECEIVED' ELSE 'APPROVED' END WHERE tenant_id=$1 AND id=$2", job['tenant_id'], job['shipment_id'])
