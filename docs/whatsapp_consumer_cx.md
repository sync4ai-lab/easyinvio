# Capability-scoped WhatsApp customer experience

This extends the existing Gupshup **Self-Service v2** ingress and encrypted queue.
It does not add a CC Express or bot-builder adapter. No LLM can buy postage,
void labels, authorize a refund, or edit a wallet through these additions.

## Enable after migration

1. Apply the complete `migrations/053_whatsapp_consumer_cx.sql` once, after 052,
   in the database used by the deployment. The migration sends nothing and
   authorizes no merchant spending. Do not rerun earlier migrations.
2. Set `WHATSAPP_CONSUMER_CX_ENABLED=true` on the matching web and worker
   environments, then release matching source/bundle versions. Existing provider,
   UAT allowlists, outbound pause, and encrypted queue key-ring controls apply.
3. For merchant alerts enable `SUPPORT_WHATSAPP_ENABLED`, configure an approved
   `GUPSHUP_TEMPLATES.SUPPORT` Utility template, and retain verified OWNER/ADMIN
   notification opt-in. A case is recorded even when no alert recipient is eligible.
4. For automatic return document notices enable `RETURN_WHATSAPP_ENABLED` and
   configure `GUPSHUP_TEMPLATES.RETURN`. A private logistics media bucket, quote
   signing secret, return warehouse, eligible plan/carrier and payment configuration
   remain prerequisites. Provider acceptance is not proof of delivery.

## Consumer use

Send `Track link <token>` or paste the merchant's HTTPS tracking URL. The
tracking capability is validated and its encrypted 15-minute session is keyed
by provider/app, sender and business receiver. Every subsequent turn rechecks
expiry/revocation and parcel membership. Session expiry is not extended by chat.
Raw tracking capabilities are encrypted at rest; database lookup uses SHA-256.
No merchant role is issued to the consumer.

Examples: `My parcel arrived damaged`, `Driver missed delivery`, `Please change
my address`, `Where is my refund?`, `I want to return this parcel`. For grouped
links, `Use parcel 2` selects a parcel in the same ordered public projection.
Requests return a support UUID and stage an opt-in merchant alert without
publishing customer notes to WhatsApp admin notifications. Existing public
intake limits remain three requests per tracking capability per day.

Consumer product-refund inquiries report recorded return tracking and the
carrier delivery timestamp, not merchant inspection, refund approval or payment.
Merchant label-refund inquiries require an unmanifested BOOKED shipment and
record a void review only. Existing provider confirmation and reconciliation
still control prepaid wallet credit; there is no guaranteed elapsed time.

## Explicit merchant return authority

Automatic postage generation is **off unless a merchant opts in**. An active
merchant OWNER/ADMIN can GET/PUT `/api/v1/whatsapp/consumer-return-policy` using
the existing authenticated API/session and CSRF controls. Platform assistance
sessions cannot grant this authority. Example PUT body (synthetic configuration):

```json
{
  "enabled": true,
  "window_days": 30,
  "charge_bearer": "RETAILER_PAY",
  "maximum_price_gbp": "10.00"
}
```

Use `CUSTOMER_PAY` for a secure Stripe payment handoff. The price cap is GBP
postage **excluding tax**, consistent with existing return offers. Existing tax
and funding checks still apply. The policy records its named author and version;
execution revalidates the author's active merchant role and the policy before
selection. Revoking the policy stops new selections; existing submitted payments
or carrier jobs require reconciliation through their original workflows.

Consumers must explicitly reply `Confirm return` after confirming original
contents/weight/dimensions. Automatic processing requires their signed-webhook
phone to exactly match the recorded original recipient E.164 phone, UK domestic
GBP parcels, a carrier-recorded delivery inside the merchant window, complete
rates and a service below the cap. The existing return review checks parcel
grouping, warehouse, entitlements, finance and duplicate-purchase guards.
International/customs changes, changed packaging, missing policy, unverified
recipient, incomplete rates and over-cap requests remain recorded retailer cases.

Merchant-paid returns reuse `ReturnReviewService` and attach the actual
carrier-issued QR PNG, with an expiring document link fallback, where supported.
Customer-paid returns produce the existing Stripe checkout; no QR is exposed
before verified payment and carrier confirmation. The existing return worker
reconciles completion and sends its approved Utility-template document notice.
That notice contains document links; it is not a new media-header template.

Durable consumer message receipts fence duplicate/uncertain actions. Interrupted
processing requires review rather than replaying a purchase. Old cached QR
responses cannot bypass an expired or revoked capability. No hosted migration,
real payment, live carrier purchase or WhatsApp send is part of offline tests.
