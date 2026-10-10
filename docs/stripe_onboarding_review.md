# EasyInvio.com Stripe onboarding and preliminary integration review

Business: EasyInvio.com. Logistics and shipping provider.
Requested products: Payments, Invoicing, Tax.

## Setup verified

- `codex plugin add stripe@openai-curated` completed successfully.
- The installed plugin includes Stripe best-practices skills and the official
  `https://mcp.stripe.com` server configuration.
- `codex mcp add stripe --url https://mcp.stripe.com` completed successfully.
- Stripe OAuth authentication completed: Codex reported "Successfully logged in".
- No Stripe tools, including `stripe_implementation_planner`, were exposed in
  the current session after installation/authentication. Start a new Codex
  session to load the plugin and MCP tools. Authentication alone does not prove
  which Stripe account/environment the planner will access; verify it with
  the account-info tool before any account operation.

**This is a preliminary source review using the installed Stripe skill. It is
not output from stripe_implementation_planner.** No fallback skills installation
was attempted because the plugin installed and authenticated successfully;
the requested new-session tool reload is the next step.

In the next session, request:

> Use stripe_implementation_planner for EasyInvio.com, a B2B logistics and
> shipping provider needing Payments, Invoicing and Tax. Review our existing
> FastAPI/asyncpg Stripe Checkout and Supabase prepaid-wallet implementation.
> Include prepaid funding and POSTPAID_30_DAY accounts, signed webhook
> reconciliation, tenant isolation, refund/dispute handling and appropriate
> invoicing/tax treatment of wallet funding versus fulfilled shipping services.
> Verify the connected sandbox account. Generate the plan before changing code
> or creating any live Stripe resources.

Only if the planner remains unavailable after restarting and verifying MCP
should the user-requested `npx skills add https://docs.stripe.com` fallback be
considered. Do not describe a manually written review as a planner-generated plan.

## Existing Payments implementation

The repository already has StripeClient with native async Checkout creation,
tenant-scoped customer creation, financial-role authorization, Decimal amounts,
idempotency keys, explicit test/live environment fences, and a hosted Checkout
popup with a fallback link. Supabase remains the wallet accounting authority.

The webhook verifies the original request bytes with the Stripe signing secret,
checks payment/customer/tenant/amount/currency identities, and credits only paid
sessions. The wallet increment, ledger insertion and top-up state change occur
in one locked database transaction. Replay checks prevent duplicate funding.
The browser confirms database status rather than treating a success URL as
payment evidence. Previous controlled tests and Supabase rollback evidence are
documented in `docs/payment_gateway.md`; these are not real Stripe payment tests.

## Gaps to reconcile with the planner

| Area | Current implementation | Recommended next work |
| --- | --- | --- |
| API access | Test gateway explicitly requires `sk_test_`; other finance code supports restricted keys | Support a least-privilege test restricted key consistently, while retaining environment fences and explicit access tests |
| Payment methods | Checkout and legacy mock PaymentIntent harness hardcode card-only methods | Remove manual method restrictions for customer Checkout and configure eligible methods in Stripe; keep delayed-payment credit gates |
| SDK/API lifecycle | `stripe==14.4.1` lock; requirements exclude 15.x | Review current supported SDK/API release with the planner, upgrade with compatibility tests, and make the API-version strategy explicit |
| Checkout attribution | Tenant/purpose/top-up metadata present | Review current `integration_identifier` support for the selected API version before adding stable attribution |
| Failed/expired payments | Only paid completion/async-success events reconcile wallets | Handle expired Checkout sessions and asynchronous failures without credit, and provide retry/reconciliation visibility |
| Refunds and disputes | No refund/dispute event reconciliation found | Add durable event handling, appropriate reversal/debt/reservation policies, and auditable compensating ledger entries; never silently allow negative/spent-credit inconsistencies |
| Stripe Invoicing | POSTPAID_30_DAY billing plan exists locally; no Stripe invoice creation or invoice-paid handlers | Implement tenant-scoped draft invoice creation from confirmed billable shipments, invoice IDs, invoice status webhooks and paid-period reconciliation |
| Stripe Tax | No `automatic_tax` or tax-registration integration found | Confirm tax settings, registrations, customer location, tax codes and product/price tax behavior before enabling tax |

Invoicing should distinguish a wallet funding receipt from an invoice for
fulfilled shipping services. A postpaid invoice payment must not accidentally
become a prepaid wallet top-up through the Checkout webhook handler.

Current wallet reconciliation expects amount_total to equal the registered
credit amount. Adding tax to Checkout without changing that accounting design
would either fail reconciliation or incorrectly credit collected tax as wallet
principal. Confirm where tax is recognized for the business model before
implementing it; do not automatically enable Tax on wallet deposits.

Stripe Tax depends on configured business/customer locations, selected product
tax codes and active registrations where collection is appropriate. It does
not calculate customs duties. Confirm VAT/tax treatment and registration
obligations with the business's accountant before enabling live collection;
do not invent a logistics tax code or create registrations automatically.

## Credential state and next verification

The local read-only configuration check found:

- STRIPE_ENABLED=false.
- No configured `sk_test_` or `rk_test_` application API key.
- No configured `whsec_` endpoint signing secret.
- STRIPE_LIVEMODE=false and DATABASE_ENVIRONMENT=SANDBOX.

OAuth grants the MCP client access; it does not replace these backend secrets.
Keep application credentials in the ignored `.env` file, never in chat or Git.
Use the signing secret for the actual local Stripe CLI listener or deployed
webhook endpoint. Keep Stripe disabled until the required configuration passes.

After the planner is available and the appropriate credentials are configured,
verify account/environment and API permissions read-only, then run a clearly
identified sandbox Checkout and signed webhook against a designated sandbox
tenant. Reconcile the Stripe session, top-up record, ledger and wallet balance.
No live customer resources, tax registrations, charges or invoice emails were
created during this setup/review.

Sources: [Stripe MCP setup and tools](https://docs.stripe.com/mcp),
[dynamic payment methods](https://docs.stripe.com/payments/payment-methods/dynamic-payment-methods),
[Checkout fulfillment](https://docs.stripe.com/checkout/fulfillment),
[Stripe Tax setup](https://docs.stripe.com/tax/set-up),
[restricted API keys](https://docs.stripe.com/keys/restricted-api-keys).
