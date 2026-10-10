# Store import and simulated tracking

Current update: [core pillar report](core_pillars/REPORT.md) documents native signed
Shopify/WooCommerce intake, normalized Amazon intake, corrected real-schema import
writes and opt-in Shopify delivery. Migration 016 is applied to the configured
sandbox. The simulation below remains the default when no connector is enabled.

Apply `migrations/009_ecommerce_sync.sql` after 008. Run the file without wrapping it in another transaction, so any PostgreSQL enum addition commits before use. This extends existing single-column status checks; custom multi-column checks, additional required shipment fields, and custom triggers in your remote base schema require review because the original schema is absent from this repository. No migration has been run against your account.

Provision a store through trusted SQL in your Supabase SQL editor (replace the tenant UUID):

```sql
INSERT INTO public.ecommerce_stores (tenant_id, platform, display_name)
VALUES ('YOUR_TENANT_UUID', 'SHOPIFY', 'My test shop') RETURNING id;
```

Send the returned store UUID to `POST /api/v1/integration/pull-orders` with your normal tenant JWT in `Authorization: Bearer ...` and `Content-Type: application/json`:

```json
{
  "store_id": "YOUR_STORE_UUID",
  "platform": "SHOPIFY",
  "topic": "orders/paid",
  "order": {
    "id": 123456,
    "name": "#1024",
    "currency": "GBP",
    "shipping_address": {
      "name": "Alex Smith", "address1": "12 High Street", "address2": "",
      "city": "London", "zip": "SW1A 1AA", "country_code": "GBR"
    },
    "line_items": [{"title": "Running shoes", "quantity": 2, "grams": "450"}]
  }
}
```

Tenant identity comes exclusively from authentication. OWNER, ADMIN and DISPATCHER can import only active stores belonging to their tenant. A repeated create/paid event with identical shipping data returns the same shipment; changed data returns 409 to require reconciliation. Unrelated Shopify fields are ignored. The envelope rejects unexpected fields, including a client-selected tenant ID.

Each item's `grams` represents unit weight. Quantities multiply that value with Decimal arithmetic; optional `length_cm`, `width_cm`, `height_cm` must be supplied together. Dimensions are retained per item and do not pretend to describe a packed parcel. Orders with missing addresses, zero total weight, more than 500 lines, more than 10000 units or more than 1000 kg are rejected. Payloads are limited to 1 MB. Decimal strings are recommended; JSON fractional numbers are parsed as Decimal without a binary float conversion.

Imported shipments remain `PENDING_IMPORT`, with unrated price zero and an expired quote. Existing wallet booking guards reject this status. A dispatch workflow must validate packing, obtain an actual rate and persist a valid QUOTED shipment before booking; import does not purchase labels.

The backend's `FinanceEngine.finish_booking(..., outcome="SUCCESS", tracking_number=..., label_storage_path=..., carrier_name="UPS")` atomically settles the label and creates a tenant-scoped tracking outbox event. After commit it immediately awaits `push_tracking_to_store(tenant_id, store_order_id, tracking_number, carrier_name)`. Pending events survive restarts and a ten-second background worker retries them in batches of 100. Literal millisecond timing is not guaranteed by asynchronous software or databases. The existing project exposes settlement hooks rather than a carrier label-purchase route, so the provider adapter must call this confirmed-success hook.

The push performs an HTTP request/response using httpx MockTransport and marks the event `SIMULATED_DELIVERED`, with a simulated SHIPPED fulfillment response. It uses the event UUID as an idempotency key. No merchant network requests, notifications, store state changes or carrier purchases occur. Known UPS, FedEx, DHL and USPS tracking links are generated with encoded tracking IDs; unknown carriers return a null link instead of an invented URL. Pass the provider's carrier name when settling a label.

This route is an authenticated simulation intake, **not a public Shopify/WooCommerce webhook** or an active store polling job. Actual public webhook HMAC verification, per-store credentials, provider-specific fulfillment-order APIs and live delivery require a separate provider adapter. WooCommerce callers normalize their payload to this documented address and unit-grams structure.

Run checks with `.venv/Scripts/python.exe -m unittest discover -s tests`. Database tests use local doubles; they do not validate your remote schema. Local preview blocks this authenticated endpoint.
