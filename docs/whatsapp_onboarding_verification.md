# WhatsApp and onboarding verification — 11 October 2026

## Why Mavuri was missing

The screenshot showed **SAMPLE CONTROL PLANE** and **Connect workspace**. The
unauthenticated frontend deliberately added the customer to its in-memory sample
array, with a `sample-...` slug, instead of calling the authenticated admin API.
Neither the tenant nor a wallet was written to Supabase. The displayed Mavuri UUID
does not exist in the database. This was a misleading sample onboarding workflow.

The fix removes that sample-create path. The onboarding button now says **Sign in
to onboard a tenant** when disconnected and opens the login dialog. Form submission
also independently checks the session. Authenticated onboarding calls the existing
admin endpoint and requires a confirmed tenant UUID and provisioned wallet before
displaying success. Server-side platform-owner authentication remains mandatory.

Sign in using **Connect workspace**, select Super-Admin, and re-enter Mavuri's full
company details to create the real customer. The old sample record cannot be
automatically migrated from its name/email alone: contact/address fields are
required, and anonymous preview actions must not grant database privileges.

## Database verification

`tests/tenant_onboarding_database_probe.py` called the actual onboarding service
against Supabase inside an outer transaction and verified:

- one tenant INSERT;
- one GBP wallet with zero balance;
- one durable HubSpot sync job created by the existing database trigger;
- the same request ID returns the same tenant rather than creating a duplicate.

All probe-created records were rolled back. No CRM network request occurred.
`HUBSPOT_ENABLED=false` remains configured; jobs queue locally until synchronization
is deliberately enabled with a validated HubSpot account configuration.

## Live WhatsApp verification and authorized setup

The user's **Hello EasyInvio** message reached the ngrok callback and returned the
workspace-registration reply over WhatsApp. Local ingress records matched the
configured Twilio account and the privately saved phone. The original Twilio
signature was independently verified before pairing.

The requested Harbor Commerce row in the screenshot was also a browser sample.
The selected real sandbox workspace is:

**SEED24 - Harbor Commerce 01**

`11de776d-4faf-f071-eb53-76d35aa619db`

The authorized setup committed:

- a DISPATCHER membership for the configured platform-owner Auth identity;
- an active, verified WhatsApp binding to that membership;
- an `EXPORT_US` saved route using the existing synthetic GB–US shipment addresses
  and dimensions. These are sandbox fixtures, not production addresses;
- an identified local quote test receipt. It does not buy a label or debit credit.

No permanent tenant, wallet balance, payment or HubSpot changes were made by setup.
No actual phone numbers, tokens or signatures are committed in this report.
The pairing helper reads the phone from private `.env` and checks it against a
provider message or cryptographically verified original callback before writing.

The fixture verification scripts now count the original synthetic principals
separately from legitimate testing memberships/bindings. All 72 original synthetic
members remain present. No new schema migration or SQL-editor update is required.

## Results and remaining dependencies

| Check | Result |
| --- | --- |
| Real phone → Twilio → public callback → WhatsApp reply | Confirmed |
| Saved phone/account matched original signed inbound callback | Passed |
| Sandbox tenant membership, verified binding, GB–US route | Committed and verified |
| Paired quote request | HTTP 200; correct workspace resolved |
| Actual multi-carrier prices | Blocked: selected tenant has 0 active TEST carrier accounts |
| Initial proactive outbound test | Twilio HTTP 400, error 21654; not delivered |
| Real subsequent inbound conversational reply | Confirmed by the user's received reply and tunnel records |
| Admin/WhatsApp/gateway/sandbox automated suite | 60 test executions passed |
| Browser onboarding and existing enterprise navigation/contrast checks | Passed; no JavaScript errors |
| Real database tenant/wallet/CRM-queue/idempotency probe | Passed; rolled back |

The account's Message-list API returned no records during the check despite the
signed incoming callbacks being recorded locally. The initial outbound rejection
is not treated as a successful send. The proven path is the incoming conversational
webhook and its TwiML reply; unrestricted proactive delivery still requires the
existing support consent/window/template configuration.

To test actual prices, configure an EasyPost TEST account or a supported regional
provider's genuine sandbox credentials for this tenant in **Carrier Provider
Settings**. Dummy seeded encrypted credentials remain inactive. Send
`Quote 4.5kg from GB to US` from the paired phone; until a carrier is configured, the
reply will explain that rates are temporarily unavailable. For later production
use, replace the fixture route with real addresses and measured dimensions.

The public ngrok endpoint forwards only the two Twilio callback paths. App/admin
pages remain local. Booking links additionally require a separately configured,
authenticated public `BOOKING_PAGE_URL`; that URL is now omitted until a real booking page is deployed.
