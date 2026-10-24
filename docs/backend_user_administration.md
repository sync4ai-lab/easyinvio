# Manage EasyInvio users from the backend

These instructions are for the EasyInvio platform owner with Supabase project access. SQL Editor is privileged and bypasses application permissions; it must not be shared with customer Owners, Dispatchers, Accountants or support Agents.

## 1. Create the sign-in identity

In your UAT Supabase project, open Authentication, then Users. Use the supported Add/Invite user workflow with the person's real email. The person can use the invitation or EasyInvio's Forgot password flow to set their password. Keep an existing identity when changing a role; do not delete/recreate it or insert rows directly into auth.users. The Auth UUID is the stable reference used by memberships, shipments and audits.

Creating an Auth identity alone does not grant access to a customer workspace or the platform console. Do not change auth.users.role to OWNER, AGENT or SUPER_ADMIN; authenticated is the Supabase authentication role, not an EasyInvio business permission.

## 2. Choose the correct authority source

| Kind of user | Where access is assigned | Notes |
| --- | --- | --- |
| EasyInvio platform owner (SUPER_ADMIN) | PLATFORM_ADMIN_USER_IDS in Vercel environment variables and local .env | JSON array of Auth UUIDs. No customer membership or platform_staff row is required. |
| EasyInvio support Agent | public.platform_staff | Role is AGENT; keep is_active true. No active customer membership. Record a grant/disable reason in platform_staff_events. |
| Customer business Owner | public.users | Role OWNER, linked by auth_user_id to Auth and by tenant_id to the existing business. |
| Customer Dispatcher | public.users | Role DISPATCHER, same company as their Owner. |
| Customer Accountant | public.users | Role ACCOUNTANT, same company as their Owner. |
| Name and contact phone | public.app_user_profiles | Keyed by auth_user_id. A profile phone is not verified WhatsApp pairing. |
| Business/workspace | public.tenants | Use an existing active workspace, or onboard one through the platform console. Do not invent wallet balances in SQL. |

The legacy company ADMIN role is not the platform owner. New customer assignments should use OWNER, DISPATCHER or ACCOUNTANT. The company Owner can invite Dispatcher/Accountant through Settings; this is preferable for routine team invitations because it completes the invitation and membership workflow.

## 3. Set the platform owner

Run this read-only lookup in Supabase SQL Editor, replacing the example email:

```sql
SELECT id AS auth_user_id, email
FROM auth.users
WHERE lower(email) = lower('owner@example.com');
```

Copy that UUID. In Vercel, open the EasyInvio project, Settings, Environment Variables. Set PLATFORM_ADMIN_USER_IDS to a JSON array such as `["AUTH-USER-UUID"]`. Do not wrap the entire array in another pair of quotes. Save it for Production (the deployment environment used by UAT), and Preview if preview deployments should also recognize the owner. Put the same JSON array in the local .env setting. Keep the owner list restricted to the actual platform owner; support staff go in platform_staff instead.

Redeploy after changing Vercel variables. Updating .env alone does not change the hosted application. Sign out and sign back in after the new deployment is ready. SUPER_ADMIN login should open the platform console without a customer tenant. A client assistance session deliberately shows a selected customer's Owner view; use Return to platform to leave it.

If a recent hosted sign-in is still Dispatcher while the local allowlist recognizes the same UUID as SUPER_ADMIN, check the Vercel value, environment scope and deployed revision. Editing public.users.role cannot grant platform-owner authority. Adding SUPER_ADMIN to platform_staff is also incorrect: its constraint admits AGENT only.

## 4. Assign Agents and customer roles with SQL

Open the companion docs/backend_user_administration.sql in SQL Editor. It defaults to INSPECT and makes no changes in that mode. Replace the example email. For a mutation, also enter your own platform-owner Auth UUID as actor_id and a clear reason of at least 10 characters. Choose one action:

- ASSIGN_AGENT: grant support access, disable the person's active customer memberships, preserve their UUID/history and append a staff grant event.
- DISABLE_AGENT: disable support access and append the disable event.
- ASSIGN_CUSTOMER: supply an existing tenant_id and OWNER, DISPATCHER or ACCOUNTANT. The script rejects active membership in another business, refuses staff/customer identity mixing and prevents demoting the last active Owner.

Read the inspection results and verify the email and company before changing INSPECT to an assignment action. The template requires migration 048. It revokes the target's app sessions after a mutation; the person signs in again. An optional display_name updates the app profile and membership name without changing passwords, phone verification or historical shipment references.

The SQL template manages database authorization for EasyInvio's password-verified app sessions. Issuer-controlled Auth app_metadata is not a substitute for a membership or staff grant. If you maintain direct Supabase-JWT integrations outside the EasyInvio sign-in flow, update their tenant binding through the supported Supabase Admin API as part of your provisioning workflow; do not rely on user_metadata or arbitrary JWT role edits.

Never edit shipment created_by values, audit actors, wallet ledgers or historical foreign keys when changing access. Do not rename an existing person's email just to change their role. Support staff enter customer operations through Assist a client, rather than taking over a customer's password or acquiring active employee membership.

## 5. Verify

After re-sign-in, open User Profile and check the displayed role. The authenticated /api/v1/auth/me endpoint reports the current identity role, and /api/v1/profile reports the platform/customer view and tenant scope. SQL inspection cannot read Vercel's owner allowlist: check that variable separately for SUPER_ADMIN. Test a permitted action and a denied action using the actual user session, not SQL Editor.


## 6. Platform owner console

The platform console aggregates client activity. Use **Assist a client** for customer shipment or wallet operations; it retains the operator identity and audit trail. The platform owner is not a customer employee.

| Tab | Platform purpose |
| --- | --- |
| Overview | Environment and date-scoped shipping revenue, stored gross markup, active clients, carrier distribution, monthly package trends, leading clients, booking-state cohorts, current wallet exposure, account cohorts, billing/payment pipelines and support threads. Currencies are separate. Gross markup is not net profit. |
| Client Accounts | Client registrations, billing plans, environment, CRM linkage and processing status, optional quote-recommendation preferences, and the newest 200 wallet events in the selected ledger environment. The client registry is capped at 200 loaded accounts; reporting totals are queried across the selected environment. |
| Carrier Connections | Platform-owned shared aggregator/direct-carrier connections, their capabilities and diagnostics. Client-assigned accounts are older or administrator-created tenant connections, not marketplace stores or self-service customer carrier credentials. The client-account filter and archived/disabled-legacy filter are independent. |
| Marketplace Connections | Environment-scoped client/store registrations and saved-setting status, lifetime imported-order count and most recent import. Search company, store or marketplace. Up to 200 matches are displayed. Saved credentials are not evidence of valid remote access or a successful live health check. |
| Pricing & Margins | Business/client/lane pricing rules and personal-account global markup. These are platform pricing controls, not the customer's warehouse controls. |
| Platform Shipments | Latest 200 shipment records across clients, with company and sandbox/production context, lifecycle evidence and document visibility. Search by company or shipment. This recent-record register is not the complete historical analytics dataset; use Overview for reporting. |
| User Profile | The authenticated operator's identity and profile. It does not change platform authority. |

Agents have the read-only/support views appropriate to their role, including Marketplace Connections; carrier credentials, pricing mutations and recommendation preference changes remain platform-owner controls.

CRM labels distinguish disabled runtime processing, environment mismatch, queued work, blocked work, retry and saved links. A missing link alone does not prove a HubSpot outage. Runtime CRM configuration belongs to the deployed application's environment; a local .env does not establish Vercel's state. CRM work uses the existing durable jobs and configured worker. This console does not turn on CRM processing or transmit additional client records by itself.

The business recommendation preference is an explicit saved choice. Balanced advice considers price/speed/risk. Budget preference may recommend an eligible Evri, Royal Mail or Yodel offer no dearer than other eligible offers and no more than two estimated days slower than the fastest non-budget service, excluding active exceptions/high-delay alerts. It only influences optional recommendation advice; it never changes quoted prices, hides other offers, books automatically or guarantees advice when the agent is unavailable. Personal accounts use budget preference automatically.

Wallet rows are append-only accounting events. RESERVE holds funds; a successful confirmed label purchase appends CAPTURE, reducing balance and held funds. RELEASE removes an unused hold. TOPUP credits a confirmed wallet payment (sandbox may have explicit fixture/test credits). SHIPMENT_REFUND credits an eligible shipment refund; REFUND_DEBIT reverses a refunded top-up. Balance/hold changes are signed deltas; wallet-after and held-after are historical balances at that row. A reserve row never changes into a capture row.

WhatsApp support-alert recipients are identity bindings, not a report of all WhatsApp label purchasers or sender shipment-update subscriptions. Verification and notification consent are separate. The platform may pause/resume eligible alerts, but must not opt in for a recipient. A customer Owner/legacy company Admin can open User Profile → WhatsApp support alerts and save their own preference for active verified bindings. The read endpoint is scoped to that tenant and authenticated user. This control is hidden during assistance and for platform staff, dispatchers and accountants. The displayed company is the bound user's workspace; a seeded company indicates a test binding. Shipment milestone email/WhatsApp subscriptions have their own settings and are not represented by this table.

Validation: tests/test_platform_console.py, tests/platform_console_browser.py and tests/mobile_auth_browser.py cover authorization, reporting scope, public metadata, populated tables, independent carrier filters, explicit preference saving, consent labels and phone/tablet/desktop layouts. Browser fixtures use synthetic identities and never contact shipping, CRM, payment or messaging providers.
