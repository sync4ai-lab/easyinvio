# Assist a client workspace

Platform Super Admins can open a client's workspace to investigate problems and complete normal client operations. The operator keeps their own identity; no client password, replacement client token or active client membership is required. The session supplies workspace-owner access, while existing wallet solvency, provider, booking idempotency and payment verification controls continue to apply.

## Setup

Apply [migration 037](../migrations/037_admin_client_assistance.sql) after migration 036 in the Supabase SQL Editor, then restart the backend and refresh the page. Platform access uses the existing `PLATFORM_ADMIN_USER_IDS` configuration and normal authenticated sign-in. No additional secret is needed. Applying this migration creates private session/audit tables; it does not buy labels, send messages or change client balances.

## Open a client

1. Sign in as a platform Super Admin and click **Switch to Client SME View**.
2. Search by company, workspace name, billing email or full Client ID. Results include the workspace status and whether it is Sandbox or Production.
3. Select the client and enter a support reason of at least ten characters. Use a case reference where available; do not paste passwords or API keys into the reason.
4. Click **Open client workspace**. The banner identifies the client, environment, access level and expiry. Client screens now use that workspace's records, wallet, rates, settings and catalog.
5. Use the normal transaction flows when needed. A booking or payment confirmation is a real operation in that client's environment, not a simulation introduced by assistance mode.
6. Click **Return to Super Admin** in the banner or the top switch. The server revokes the session and the browser clears quotes, selections and displayed client data before restoring the admin workspace.

Use the client switch again to choose another workspace. A new workspace starts with cleared local transaction state. Completed bookings and stored records remain with their original client. An already-running request may finish after a switch; its audit session still identifies the original workspace and operator.

Sessions last at most 30 minutes and never outlive the admin authentication token used to start them. The selection is held in browser memory, not in a URL or reusable customer token. Reloading the page returns to the normal admin sign-in/workspace flow. Expired or revoked assistance sessions cannot authorize more client requests. Returning remains possible after local expiry; if server revocation cannot be confirmed during a network failure, the browser drops the local client context and the server session expires normally.

## Audit records

The Super Admin overview includes **Client assistance audit**. It shows access starts and ends, client, actual admin auth-user ID, timestamp, support reason, request method/path and HTTP outcome. **Requested changes** expands the redacted JSON request when available. The table defaults to access and mutation events so periodic dashboard refreshes do not hide important actions. The owner-only API can include reads with `GET /api/v1/admin/client-assistance/events?include_reads=true`, and filter by `tenant_id`.

Before each assisted HTTP request executes, the server commits a `REQUEST_STARTED` event. If this initial audit write fails, the request is blocked. Completion appends a separate `REQUEST_FINISHED` event. Database triggers reject updates and deletes of audit events; browser roles have no direct table grants. Events have foreign keys to both the selected workspace/session and its real admin actor.

Small JSON request bodies are recorded with credential/password/token fields redacted. Large bodies, CSV, image evidence and other uploads are not copied into the audit table. Completion records include a digest and count of consumed request bytes. Read events are retained as well. Support reason text is operator-provided, so keep credentials out of it.

An HTTP outcome is not a database before/after diff, a confirmed label purchase, a bank receipt or proof that a background job completed. Existing shipments, wallet ledger, payment records and provider reconciliation remain the sources for those outcomes. If a finish event is missing, the durable start event remains: investigate the operation and its normal reconciliation records before retrying. The audit does not claim that external effects and its own outcome append form one distributed transaction.

Shipment preparation requires a `public.users` operator FK. Starting assistance creates an **inactive** support membership for the actual admin when one does not already exist. It supplies that audit reference without granting an active ordinary client login or pretending that a client employee performed the action. It may appear as an inactive platform-support entry in the client's team records; existing active memberships are not changed. Auth-user-based `created_by`/`updated_by` fields continue to identify the admin.

## Authorization boundaries

The server revalidates platform-owner authentication on assisted requests and binds each session to the admin, the original bearer-token fingerprint and one tenant. Another user or another sign-in token cannot reuse the session ID. A conflicting `tenant_id` query is rejected. Existing RLS policies and the deterministic finance engine are unchanged. Client requests cannot become platform-management or identity-management requests by supplying an assistance header; those operations use the separate Super Admin context.

Client workspace-owner access is intentional. Assistance does not reproduce a particular employee's narrower dispatcher/accountant role, impersonate their personal profile or bypass an inactive/suspended account's existing transaction rules. The personal User Profile remains the admin's own identity. WebSocket tracking uses the same selected session and revalidates it during updates. No external notifications are sent merely by opening a workspace.

## Verification

- `tests/test_client_assistance.py` checks operator attribution, tenant mismatch rejection, invalid sessions, unauthorized operators, write-ahead audit failure, outcome-write failure and credential redaction.
- `tests/client_assistance_database_probe.py` applies migration 037 twice inside an outer SANDBOX transaction, verifies parent keys, private access, immutable events and revocation, then rolls back all schema/data changes.
- `tests/client_assistance_browser.py` uses synthetic API responses to verify search, selection, return, cross-client data clearing, the mobile banner and the admin audit panel. It makes no provider purchases or database writes.

The database probe validates the migration but does not install it permanently. The migration must be applied before the new live assistance controls can be used.
