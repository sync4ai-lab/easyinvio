# Enterprise control plane verification

The complete, readable SPA is in `index.html`; all four JavaScript controllers are embedded. `frontend/enterprise_controls.js` is the editable source for the newest controller, not a runtime dependency.

## Changes

- The platform-owner navbar contains Overview, Client Accounts Node, Carrier Connectors and Margin Rule Matrix. Warehouse forms are excluded from that persona.
- Client owners retain their workspace tools; accountants have overview, wallet/billing, customs and store integrations. Warehouse dispatchers have exactly Speed Quote Matrix, Box Profiles and Manifest & Labels.
- Tenant onboarding creates the existing company/wallet records through the protected admin endpoint. Owner configuration controls list the network, edit/retire margin formulas, register encrypted carrier accounts and change provider parameters. Client Accounts includes the latest 200 network wallet ledger entries, retaining each transaction's currency.
- Carrier and margin removal retires active configuration; historical shipment references remain valid. Configuration changes and their credential-free audit records commit together.
- E-commerce registry controls are tenant-scoped. Current order import/tracking integrations remain simulations; this panel does not install remote storefront plugins.
- Customs suggestion selection fills declaration draft fields and clears the review checkbox. Confidence remains explicitly simulated and the curated descriptions are not presented as authoritative national tariff rulings.
- Manifest exception rows open a bottom sheet with stored support guidance, POD inspection and unsent dispute drafts. Dispatchers cannot access the financial dispute action.
- Dark native date inputs, dropdown options, text fields, dialogs and table cells use explicit foreground/background pairs. Responsive navigation has SVG fallbacks if the Lucide CDN is unavailable.

## Verification

71 backend regression/security tests passed. Management routes reject anonymous tokens and customer tokens, including forged platform-admin metadata. Server authorization uses verified Supabase JWT identity plus the configured owner allowlist. Dispatcher responses exclude wallet balances, wholesale/platform margin fee splits and invoice-baseline metadata; customer quote prices remain available for carrier selection.

`browser_evidence.json` records onboarding, margin editing/retirement, carrier parameters, persona separation, HS draft injection, exception drawers and native-control contrast checks. All passed with no JavaScript errors. Admin layouts were measured at 375, 768, 1024, 1280, 1366 and 1440 pixels with zero page-level horizontal overflow. The existing cargo/customs/manifest/mobile browser suite also passed, including its 80% CSS zoom approximation.

`database_evidence.json` records real Supabase sandbox reads, margin changes, cross-tenant rule-move rejection, encrypted carrier creation, idempotent retries, activation and retirement. All configuration test mutations were rolled back. No provider API calls, real payments or messages occurred.

Real Supabase owner/accountant/dispatcher login checks, inactive-user rejection, tenant isolation and concurrent manifest reads passed. Five temporary login identities were deleted. Those customer roles are not platform-owner identities; owner-authorized SQL was tested using an explicit test authentication override inside the rolled-back probe, while JWT owner allowlist checks were tested separately.

## Database and owner setup

Migration `015_admin_management.sql` has already been validated and applied to the configured sandbox. It adds only the audit table/index/grants; existing records are preserved. There is no need to rerun seed data or apply the migration again for this database.

`PLATFORM_ADMIN_USER_IDS` now contains the explicitly authorized Supabase Auth user `117d268d-b034-4a74-ad4d-050813bf67ac`. The Auth admin API confirmed that this user exists, and the local configuration was verified after writing it:

```dotenv
PLATFORM_ADMIN_USER_IDS=["117d268d-b034-4a74-ad4d-050813bf67ac"]
```

The backend has been restarted with this configuration. Health returned HTTP 200 and anonymous access to the admin tenants endpoint returned HTTP 401. Sign out and sign in with that Supabase user's credentials to refresh the active profile. A signed-in request by this specific owner has not yet been tested; no password or login token was requested. The unsigned Super-Admin toggle remains a clearly marked sample control plane until an authorized owner signs in. Login provisioning for newly onboarded clients remains separate from company/wallet creation. No further SQL update is needed for this owner configuration.

EasyPost and the compatible regional adapter are supported. Sendcloud is visibly labelled as requiring an adapter. Live carrier purchases, physical printing, Stripe, Twilio and HubSpot remain outside this verification. This upgrade does not mark every previously deferred UAT case as passed.
