# Subscription tiers: rollout and verification

Migration 050 was already run by the operator during implementation. Do not rerun it.
Run **the complete `migrations/051_subscription_safety_followup.sql` file once** in
the same database. It corrects zero-parcel reporting and guards bespoke margin
rules and BYOC writes. Both migrations are tested against disposable PostgreSQL;
the implementation does not connect to, migrate or inspect the configured database.

Keep `SUBSCRIPTION_TIERS_ENABLED=false` until both migrations and the matching
application version are available. Then set it to `true` on the web and worker
environments together and redeploy each. Use a test database, Stripe test keys
and sandbox carrier accounts for UAT. Promoting a deployment does not replace
the need to configure its environment variables.

## Existing and new workspaces

Existing live workspaces retain their previous access until the platform owner
explicitly enrolls them. Sandbox workspaces are complimentary Command. Verified
web registration accepts only the three allowlisted plan names and monthly or
annual cycles. Starter starts active; Velocity and Command start a bounded
14-day trial (`SUBSCRIPTION_TRIAL_DAYS`, 1–30). Trial expiry, cancellation or past
due status reduces effective access to Starter, without deleting data, disabling
tracking history or taking customer funds. A plan query parameter never grants
a user role, billing credit, verified carrier credentials or staff privileges.

The initial tenant billing mode remains prepaid. Command postpaid eligibility
also requires a separately approved `POSTPAID_30_DAY` billing agreement and an
active billing account. Do not grant credit merely by selecting Command.

Business tier baseline margins are 18%, 9% and 5%, using Decimal calculations.
Starter and Velocity cannot use bespoke margin overrides; Command preserves
approved overrides. Individual-account pricing keeps its existing separate
platform policy. The pricing model does not guarantee a lower carrier wholesale
rate where no such contract exists.

## Roles and commercial access

| Actor | Existing authority, with additional plan checks |
| --- | --- |
| Customer Owner | Workspace settings and team invitations; subscription checkout |
| Legacy customer Admin | Existing dispatch/finance/administration actions; no new owner powers |
| Dispatcher | Quotes, bookings, eligible headless returns and manifests; no team, store-credential or finance administration |
| Accountant | Finance/history and Command ledger export/audits; no purchases, customs generation or subscription checkout |
| Platform SUPER_ADMIN | Plans & Revenue, audited plan changes and explicitly scoped client drilldown |
| Platform AGENT | Existing support/onboarding scope; no platform plan/revenue controls |

Only Owner may invite the existing allowlisted Dispatcher/Accountant roles.
Legacy Admin is not assignable through that flow. Platform assistance never
authorizes customer subscription checkout. All existing JWKS, revocable session,
tenant membership, assistance, CSRF and public/session boundaries remain in use.
Basic public help and previously booked tracking remain available. Transactional
shipment updates and responses explaining an upgrade are not suppressed when a
paid booking feature expires. New WhatsApp booking actions are plan-gated.

Seats include active users plus unexpired pending invitations. Stores count active
store registrations. Tenant-row locks and SQL triggers cover alternate writers,
reactivation and invitation acceptance. Starter stops at 150 booked/held parcels.
Paid usage beyond 2,000/4,000 is flagged; **no automatic overage charge exists**.
Annual billing still has monthly parcel periods, anchored to the billing start
in UTC. Failed drafts are excluded; a previously booked/refunded parcel remains
usage. Financially uncertain holds remain reserved until reconciled, including
across month boundaries. Do not expire them merely to free quota.

New quotes stamp their plan/version; a plan change requires a fresh quote before
reservation. Reconcile old pending financial reservations before enrolling an
existing workspace. Deactivate excess stores/users or cancel pending invitations
before a manual downgrade. Automatic trial expiry retains users' data and blocks
additional capacity; it does not arbitrarily deactivate colleagues.

Shared platform carrier connections are usable on all plans. Unlinked,
tenant-specific credentials are BYOC and require Command for new rating use.
Historical carrier access remains available for already-purchased tracking,
documents and reconciliation. A missing feature fails closed for new actions.

## Optional paid subscription checkout

Trials do not need a new payment flow. If recurring checkout is desired, create
four GBP **recurring** Stripe Prices, separately for test and live mode, and set
`SUBSCRIPTION_PRICE_IDS` on the server to this shape (replace IDs):

```json
{"VELOCITY:MONTHLY":"price_replace_1","VELOCITY:ANNUAL":"price_replace_2","COMMAND:MONTHLY":"price_replace_3","COMMAND:ANNUAL":"price_replace_4"}
```

Amounts must be £29/month, £288/year, £79/month and £780/year respectively.
Prices, currency, interval, quantity and livemode are validated server-side.
`BOOKING_PAGE_URL` must be the correct HTTPS site; redirects are server-owned.
The customer Owner reviews and authorizes recurring billing in Stripe from
Profile → Your plan and usage. No signup redirect charges a card. Empty mapping
returns a clear configuration error and leaves trials available.

Subscribe the existing signature-verified Stripe webhook to:
`checkout.session.completed`, `checkout.session.async_payment_succeeded`,
`checkout.session.expired`, `customer.subscription.updated`,
`customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`.
Keep existing postage-wallet webhook events. Subscription events have separate
receipts and cannot credit the wallet. A durable checkout nonce and one-pending
constraint prevent duplicate subscriptions. A timeout marks REVIEW: investigate
that existing Stripe session before allowing another checkout. Never delete a
pending receipt to retry a possibly successful charge. Current provider state
is read after acquiring the subscription lock, so reordered events cannot apply
an earlier cached observation. Provider-managed plans cannot be manually
overridden in the platform console; arrange changes/cancellation in Stripe and
let verified events synchronize access.

## Plans & Revenue

Platform owner: Overview → Plans & Revenue. Select production/sandbox and a UTC
date range (exclusive end, maximum 366 days). Load more clients with keyset
pagination. Transactions show the latest bounded wallet/booking entries; the API
also supplies a wallet cursor. Plan changes require a reason, version and nonce;
replays return their original audit result, conflicting requests return 409.

MRR is contracted monthly-equivalent software revenue for active, non-complimentary
plans. Trials are excluded. Subscription cash receipts, customer wallet funds,
label sales, recorded wholesale cost and stored gross label margin are separate.
Gross markup is **not net profit**: refunds, carrier adjustments, taxes and
operating expenses are not deducted. Ledger CSV exports are not a certified tax
return. Upcoming marketing capabilities remain labelled upcoming.

## Preflight SQL (read-only; no secrets)

```sql
SELECT tenant_id, subscription_plan, plan_status, plan_enforcement_enabled,
       plan_version, plan_period_start, plan_period_end
FROM public.tenants;
SELECT * FROM public.v_tenant_monthly_usage;
SELECT tenant_id, count(*) AS active_users FROM public.users
WHERE is_active GROUP BY tenant_id;
SELECT tenant_id, count(*) AS active_stores FROM public.ecommerce_stores
WHERE is_active GROUP BY tenant_id;
SELECT tenant_id, status, count(*) FROM public.wallet_reservations
WHERE status::text IN ('RESERVED','SUBMITTED') GROUP BY tenant_id,status;
```

Test each customer role on each tier; verify 402 for locked features and 403 for
wrong roles, 150th/151st Starter parcel behavior, pending-invite seat accounting,
store reactivation, trial expiry, fresh-quote fencing and duplicate billing events.
Confirm a Stripe test subscription never changes the postage-wallet balance.
Do not claim production verification until those tests pass in your own UAT setup.
