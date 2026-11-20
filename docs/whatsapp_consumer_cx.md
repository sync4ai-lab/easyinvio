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

### Configure approved Gupshup templates

`SUPPORT_WHATSAPP_ENABLED=true` and `RETURN_WHATSAPP_ENABLED=true` are correct
boolean settings. They enable the workers, but do not create or approve templates.
Also enable `WHATSAPP_CONSUMER_CX_ENABLED=true` after migration 053 on the web and
worker environment. A Vercel environment-variable change applies to a new
deployment; changing local `.env` does not update an existing hosted process.

`GUPSHUP_TEMPLATES.SUPPORT` and `.RETURN` mean entries inside **one JSON variable
named `GUPSHUP_TEMPLATES`**, not two environment-variable names containing dots.
The entries must identify approved templates belonging to the same Gupshup app
as your business number. A template name, Twilio Content SID, or made-up ID is not
a replacement for the approved Gupshup template ID.

In the Gupshup dashboard, select the EasyInvio WhatsApp app, open **Templates**,
then **Create Template**. Use category **Utility**, a text-only template and the
English language variant supported by your app. Supply synthetic sample values,
submit for approval, then copy the approved template ID and exact language code.
Approval is controlled by Gupshup/Meta. If it is approved as Marketing, do not map
it as Utility: correct the template/category before activation. See the
[official template creation guide](https://docs.gupshup.io/docs/create-template).

The current adapter sends ordered **body parameters**. Use these drafts without
dynamic buttons or required media headers; the current RETURN sender provides
the document/payment URL as body variable 3.

**SUPPORT** — suggested template name `easyinvio_support_update_v1`:

```text
EasyInvio shipping support update.
{{1}}
This is a service notification about a shipment or support case in your workspace. Sign in to EasyInvio to review the details.
```

Sample for variable 1: `Case DEMO-1042: a damaged parcel was reported. Please review the customer request.`
Mapping order: `parameters: ["body"]`.

**RETURN** — suggested template name `easyinvio_return_update_v1`:

```text
EasyInvio return update: {{1}}
{{2}}
Open the secure page for this requested return: {{3}}
Follow the selected carrier's return instructions.
```

Samples: variable 1 `Your return label is ready`; variable 2 `Return for DEMO-1042. Your selected service requires a printed label.`;
variable 3 `https://uat.easyinvio.com/track` (a synthetic sample for approval, not an actual payment/document capability).
Mapping order: `parameters: ["heading", "body", "link"]`.

After approval, use this shape with the actual IDs and language codes. **Do not
activate the placeholder values below.** Preserve any existing SHIPMENT entry.

```json
{
  "SUPPORT": {"provider_id": "REPLACE_WITH_APPROVED_SUPPORT_ID", "language": "en", "category": "UTILITY", "parameters": ["body"]},
  "RETURN": {"provider_id": "REPLACE_WITH_APPROVED_RETURN_ID", "language": "en", "category": "UTILITY", "parameters": ["heading", "body", "link"]}
}
```

For local `.env`, put the JSON on one line with single quotes around the whole
value: `GUPSHUP_TEMPLATES='{"SUPPORT":{...},"RETURN":{...}}'` (replace the
ellipsis with the complete objects above). For Vercel, create/edit the variable
`GUPSHUP_TEMPLATES` and paste the raw JSON object **without** the outer single
quotes. Assign it to the environment used by the final deployment, and any
Preview environment you actually test. JSON uses double quotes internally.

Shipment milestone notifications have a separate approved SHIPMENT mapping and
`SHIPMENT_WHATSAPP_NOTIFICATIONS_ENABLED` flag; enabling SUPPORT and RETURN does
not enable sender milestone alerts. For initial verification, retain UAT mode
and a consenting test-recipient allowlist. `WHATSAPP_OUTBOUND_PAUSED=true` blocks
all WhatsApp sending. Unpause only for the intended test/live sending window.
Merchant OWNER/ADMIN alert recipients still need a verified binding and opt-in.

No merchant return-policy row is created by migration 053. The authenticated
merchant policy API below must be used to explicitly authorize automatic returns;
until then consumer return requests are recorded for retailer review.

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

## Git integration and one manual production release

Completed changes are integrated and pushed to `origin/main` after checks. The
repository sets `git.deploymentEnabled=false` in `vercel.json`, so ordinary Git
pushes do not automatically start deployments. It does not stop existing workers
or remove charges for services that are already running. See
[Vercel Git configuration](https://vercel.com/docs/project-configuration/git-configuration).

At the end of the day:

1. In Vercel project settings, confirm the Production Branch is `main` and the
   production variables include the approved JSON template mappings and feature flags.
2. Open **Deployments → Create Deployment** (sometimes under the page's menu),
   enter the latest `main` commit SHA or the `main` branch, and select the
   Production/main branch configuration if prompted. Check the source commit.
3. Create that deployment once and verify the production domain after it succeeds.

Use a **new deployment from the latest Git reference**, rather than Redeploy on an
old deployment: redeploy rebuilds an existing deployment and is not a way to select
the newest Git commit. See [creating a deployment from a Git reference](https://vercel.com/docs/git#creating-a-deployment-from-a-git-reference).
No command in this guide deploys automatically or sends a WhatsApp message.
