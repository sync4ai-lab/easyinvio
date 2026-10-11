# EasyInvio-owned aggregator connections

Configure a platform connection once through **Carrier Provider Settings →
provider card → Set Up**. Do not select Harbor or another client. All matching
clients receive an internal tenant-specific carrier reference, but the API key
belongs to EasyInvio and stays encrypted on the backend. Clients retain separate
shipments, prices, wallet checks and permissions.

Migration 020 has been applied to the configured sandbox. It adds the private
`platform_carrier_connections` and credential-free audit tables, plus a guarded
reference on `carrier_accounts`. Existing client-specific accounts are preserved.
Database triggers project master configuration into tenant-owned records for
existing clients and new onboarding, preserving composite shipment foreign keys.
TEST connections serve sandbox tenants; LIVE connections serve non-sandbox
tenants. Suspended workspaces do not have active shared accounts. Retirement and
credential rotation propagate atomically while historical references remain.

The master encrypted envelope is bound to the platform UUID. Tenant projections
carry the ciphertext and matching reference. Rating first checks the requesting
tenant, then validates that credential binding before decryption. Browser roles
cannot read the master table or forge linked carrier records. No public management
response returns plaintext keys or ciphertext. Only authenticated, allowlisted
platform owners can create, edit, rotate or retire the shared connection.

## Set Up forms

- EasyPost: account label, TEST/LIVE environment, private API key, active switch.
  Provider identity and official endpoint are supplied automatically. No client,
  provider or regional-code dropdown is shown.
- Sendcloud: public/secret API keys, environment and active switch. Its endpoint
  and internal adapter identifier are supplied automatically. Pricing still
  requires verified `SENDCLOUD_METHODS`; maps can use the platform connection UUID
  and are inherited by tenant projections. Native label purchase remains disabled.
- LocalRegional: its API key, approved HTTPS endpoint and provider identifier.
  Different regional services actually have different hosts and identifiers.
- Advanced settings remain collapsed by default. A blank key during editing keeps
  the existing key; providing a new key rotates it. Key inputs clear on close/save.

## Original fields explained

| Field | Purpose |
| --- | --- |
| Assigned client | Needed for a client-specific account; removed from platform setup |
| Account name | Your label for this connection, such as EasyInvio EasyPost |
| Provider | Chooses an adapter; now fixed by the card you clicked |
| Environment | TEST or LIVE; must match the server provider mode |
| API endpoint | Provider's server address; fixed automatically for known providers |
| Regional provider code | Identifies a regional adapter; irrelevant to EasyPost |
| Upstream account ID | Optional specific provider-side carrier-account selector; omitted means use the eligible accounts returned by the aggregator |
| Priority | Lower numbers are considered first when provider capacity is limited; not a shipping markup or customer price |
| Timeout seconds | Upper bound for a provider request; conversational/overall deadlines can be shorter |

Rates are still compared concurrently. Tenant-specific margin rules apply after
wholesale rates arrive. Sharing a connection does not share other tenants' orders,
wallets or personal data, and does not give clients access to EasyInvio's token.

## Commercial carrier availability

Your aggregator agreement and configured carrier services determine the available
rates for a particular lane, cargo, currency and package. Possessing a generic API
key does not guarantee every carrier/service is enabled. EasyPost documents a
centralized platform billing model with parent-managed billing/carrier settings;
provider-side child accounts can be an additional layer where your agreement
requires them. This change does not create remote child accounts or sign contracts.
[EasyPost centralized model](https://docs.easypost.com/guides/get-started-with-forge/self-managed-billing-guide).

## Verification

The real Supabase rollback-only probe verified existing-client rollout, new-client
inheritance, retry idempotence, master-key resolution in the existing rating
repository, tenant/envelope mismatch rejection, retirement, and denied browser-role
access to the secret master table. Synthetic changes were rolled back; no provider
call or payment occurred. Existing admin, security, WhatsApp and sandbox regressions
and browser tests passed (87 automated test executions in total). No genuine aggregator credentials have been added
by this change: save EasyInvio's real Test key before requesting actual prices.
