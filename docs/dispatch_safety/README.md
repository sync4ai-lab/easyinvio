# Dispatch safety remediation

## Implemented

Shippo remains on `https://api.goshippo.com`, with `Authorization: ShippoToken ...`,
`/orders/` and `/transactions/`. `https://goshippo.com` is not the documented API
origin. Redirects remain disabled so authorization cannot follow another host.
[Official transaction reference](https://docs.goshippo.com/shippoapi/public-api/transactions/createtransaction).

Sendcloud asynchronous announcements now POST to `/api/v3/shipments`, not
`/shipments/announce`. HTTP 202 is always pending; documented 201 responses with
ANNOUNCING parcels are also pending. The native shipment ID is persisted on the
original tenant shipment after its reservation has been marked SUBMITTED.
No final label or tracking number is inserted on acceptance alone.
[Official announcement reference](https://sendcloud.dev/api/v3/shipments/create-and-announce-a-shipment-asynchronously).

`PartnerLifecycleService.poll_and_finalize_sendcloud_label(shipment_id)` uses
the same advisory lock as preparation and booking. It checks the original
credential fingerprint, tenant, account and reservation, and only GETs the
saved native shipment. Labels need a matching shipment identity, tracking number
and HTTPS label document; announcing, failed or cancelled parcels cannot settle.
The existing financial transaction atomically decrements balance and reserved
balance, inserts exactly one CAPTURE ledger record, and saves the tracking label.
Polling survives process restarts and disabling an aggregator. Backoff is durable,
bounded at 30 attempts; exhausted/uncertain outcomes retain held credit for
reconciliation. A timeout never triggers a second announcement.

To preserve existing analytics, fulfillment, support and refund contracts,
canonical `shipments.status` remains BOOKING then BOOKED. The additional persisted
`logistics_metadata.label_lifecycle_status` is SYNC_PENDING then LABEL_CREATED.
The booking endpoint returns HTTP 202 for pending labels. Manifest responses expose
`label_status` to dispatchers without exposing private adapter metadata, and the
manifest displays the new label states. Pending bulk replays return pending,
not a new purchase. Document links only appear after confirmation.

## Cargo capability boundary

| Cargo | EasyPost | Sendcloud v3 | Shippo |
| --- | --- | --- | --- |
| PARCEL | Native supported flow | Native supported flow | Native supported flow |
| LETTER, under 0.5 kg | Weight plus Letter predefined package; dimensions excluded | Refused until a verified letter service mapping exists | Refused until a verified letter service mapping exists |
| PALLET / OVERLAND_FREIGHT | Explicit native-contract rejection | Explicit native-contract rejection | Explicit native-contract rejection |

Order and purchase wrappers now validate cargo before sending parcel mutations.
Industrial freight is never silently converted to a parcel. Existing internal
freight floor/stackability calculations and compatible custom regional rate
contracts remain available, but this change does not claim native freight label
support for these three parcel adapters. Provider-specific freight contracts,
documented payload schemas, and a verified carrier/class/accessorial mapping are
required to implement that remaining dispatch capability. Density alone must not
be presented as a certified freight classification.

## Webhook security and deployment

Existing encrypted Shippo URL_TOKEN authentication remains mandatory and uses
constant-time comparison. Missing, wrong or repeated tokens are rejected.
Application/HTTP/uvicorn log filters redact query tokens, including exception
tracebacks. Local uvicorn access logging and automatic proxy-header rewriting
are disabled. Native signatures remain enabled for all three providers.

Optional source-IP restriction uses these server environment variables:

```dotenv
# Copy currently documented Shippo egress IPs for your deployment region.
SHIPPO_WEBHOOK_ALLOWED_IPS=
# Trust only the actual proxy socket peers. Never use 0.0.0.0/0 or ::/0.
TRACKING_WEBHOOK_TRUSTED_PROXY_CIDRS=
```

If the allowlist is configured, unapproved source addresses return HTTP 403 even
with a correct token. An untrusted peer cannot bypass it using X-Forwarded-For.
Trusted proxy chains are evaluated from the socket peer toward the first
untrusted hop. For an external uvicorn launcher, use `--no-proxy-headers` so this
code receives the real socket peer. Configure your trusted reverse proxy to
overwrite/append forwarded headers correctly. The optional IP policy is not
enabled automatically because the actual proxy topology has not been verified.
[Shippo egress IPs and HMAC setup](https://docs.goshippo.com/tracking/webhook-security/).

Python cannot redact logs owned by ngrok, nginx or a hosting provider. When using
URL_TOKEN, start ngrok with `ngrok http 8000 --inspect=false` and disable full-URL
logging at each reverse proxy (for nginx, use a token-free `$uri` log format or
`access_log off` on this endpoint). Verify cloud request capture is disabled.
Prefer provisioned Shippo HMAC to avoid a secret in the URL entirely. No tunnel or
external provider subscription settings were changed in this remediation.

## Database and verification

No required schema change: durable polling uses existing shipment JSON metadata
and wallet reservations. For a larger queue, apply the optional
[025_pending_label_poll_index.sql](../../migrations/025_pending_label_poll_index.sql)
after 024; it adds only a partial lookup index. It was not applied remotely.

* Full Python suite: 275 passed, including eight new dispatch/security tests.
* [Actual Supabase rollback probe](database_probe.json): pending native ID, held
  Decimal reservation, no premature tracking, pending GET, provider-disable
  recovery, booking replay, one POST and one ledger capture all passed.
* HTTP provider responses in that database probe are controlled with MockTransport;
  no genuine Sendcloud purchase or free carrier sandbox pass is claimed.
* No live carrier, Stripe, WhatsApp or HubSpot operations were executed.

The existing Sendcloud TEST purchase guard remains intact: an ordinary account's
announcements can incur real charges. A verified non-billable test contract is
still necessary before genuine Sendcloud purchase testing.
