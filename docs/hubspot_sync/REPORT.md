# HubSpot lifecycle and activation verification

Implemented in the existing CRM module without replacing its durable worker,
account fence, unique tenant identities or optional upsell behavior.

## Results

- **81 automated tests passed**: CRM onboarding/replay, signatures, stage/account
  checks, margin/admin security, freight, tracking/support, dashboards and CSV.
- **Real Supabase sandbox rollback probe passed**: migration 018 rerun,
  duplicate company across two won deals, atomic active tenant/zero wallet,
  outbound reuse of the inbound company, company/contact metadata persistence,
  Decimal zero metrics, revision-safe queue completion and queue RLS/grants.
- **Chromium checks passed**: admin timeline link, malformed CRM ID rejection,
  company-name escaping, hidden client admin hub, no horizontal overflow at
  375/768/1024/1366 pixels, and no JavaScript errors.

HubSpot HTTP responses were controlled test responses. **No real CRM objects,
payments, messages or customer logins were created.** The real database probe
rolled back every change, including migration 018. These results verify code
and SQL behavior, not live HubSpot write permissions or webhook delivery.

## Changes

`backend/hubspot_crm.py` now exposes the requested lifecycle/metrics helpers,
retains company and contact IDs after association, and exports confirmed lifetime
parcel counts, Decimal spend and wallet credit. The existing package-count field
remains supported alongside `veloce_total_shipments`. Ledger and wallet reads use
a consistent snapshot, ending before any remote PATCH. Bulk label fulfillment
uses BackgroundTasks, backed by durable SQL jobs. Wallet balance changes also
enqueue work; synthetic seed opening credits are excluded.

`backend/hubspot_provisioning.py` handles the signed inbound endpoint. Native
v3 signatures require the app client secret, exact configured public HTTPS URL,
raw body and fresh timestamp. Portal/app boundaries are checked before queuing.
Canonical deal, company and contact data is re-fetched from the verified account.
Ambiguous associations, non-won current deals and incomplete addresses fail closed.
Portal/deal replay keys and company locks prevent duplicate workspaces.

The Client Accounts Hub adds actual record timeline links only for valid numeric
portal/company IDs, using the admin-only API and safe external-link attributes.

## Deployment required

1. Run `migrations/018_hubspot_activation_and_metrics.sql` after 017.
2. Create/verify the seven company properties from `config/hubspot_properties.json`.
3. Keep the existing **Service Key**; grant CRM and schema/account read/write
   permissions as described in `docs/hubspot_crm.md`.
4. Choose the environment matching the actual API account type. The last live
   account check returned **STANDARD**, so SANDBOX will deliberately reject it.
   PRODUCTION targets non-sandbox tenants only; this does not require a paid plan.
5. For native inbound events, configure a HubSpot app deal-property subscription,
   app ID, signing client secret, exact public HTTPS URL and internal won stage IDs.
   Service keys alone do not provide webhook subscriptions.
6. Run `python -m backend.check_hubspot` before enabling CRM, then restart the
   configured backend. Enable provisioning only after its separate configuration.

Missing inbound settings were added as empty local `.env` fields; activation
flags and existing credentials were preserved. No real token is in Git.
There is no automatic customer Auth user or login invitation: owner membership
must be assigned through the established platform workflow.

## Reproduce

```powershell
$env:PYTHONPATH='C:\Projects\veloce-ai;C:\Projects\veloce-ai\tests'
.\.venv\Scripts\python.exe -m unittest tests.test_hubspot_crm tests.test_hubspot_activation tests.test_core_pillars tests.test_admin_portal tests.test_support_monitoring tests.test_dashboard_portal tests.test_automation_freight tests.test_enterprise_security tests.test_order_csv -q
.\.venv\Scripts\python.exe -m tests.hubspot_database_probe
.\.venv\Scripts\python.exe -m tests.test_hubspot_browser
```
