# Login and user identity gateway

The app now opens an exclusive dark-slate login page. Main navigation and sample
dashboards are hidden until the saved session is validated by the backend.

Sign in with your **Supabase Auth email/password**. The database connection
password in `.env` is not an application login password. The requested
`satyakishore.mavuri@gmail.com` identity was found in Supabase and its UUID is
already in the platform-owner allowlist. No role was granted merely by matching
an email address, and no existing password was changed.

## Controllers

| Route | Behavior |
| --- | --- |
| POST /api/v1/auth/token | Verifies credentials through Supabase Auth, checks active database registration, issues a 15-minute HS256 app token |
| GET /api/v1/auth/me | Returns the caller's verified email, role, name and contact phone |
| PATCH /api/v1/auth/me | Saves the caller's name/phone; role, email, tenant and user IDs are not editable |
| POST /api/v1/auth/logout | Revokes the current app session in the database |

The frontend `process_user_login()` is a JavaScript async function. It stores the
short-lived app access token in localStorage as requested, validates the profile,
restores it after reload, and arms an expiry timer. No password, provider refresh
token or Supabase access token is persisted in browser storage. Log Out clears
storage/memory and hides the dashboard immediately, then requests server
revocation. If the network fails, the app reports that server revocation could not
be confirmed; the remaining server token expires within its short lifetime.

The new **User Profile** sidebar entry is available to all verified personas.
The header avatar uses the first letter of the server-verified email; clicking it
opens Profile. The role badge comes from backend authorization. Editing a contact
phone does not alter verified WhatsApp bindings or support-notification consent.

## Security boundaries

- Supabase Auth verifies the password. Application tables do not store or compare
  plaintext passwords. Unknown/unregistered users cannot gain a workspace.
- The HS256 issuer/audience and signing key are separate from Supabase's ES256
  signing keys. Existing API authentication resolves the encrypted provider token,
  validates its original Supabase signature, and rechecks database permissions.
- Session UUID, auth user and tenant bindings are verified; the provider subject
  must match the app session subject. Tenantless allowlisted owners may bootstrap
  the first workspace. Client membership remains mandatory and authoritative.
- Server-side encrypted session records make logout revocation effective beyond
  simply deleting local browser state. Banned/deleted identities lose resolution.
- Profile writes are caller-scoped and update member display names atomically.
  The session/profile/rate-limit tables are unavailable to browser database roles.
- Login attempts are throttled by hashed email and client IP. Database failures
  return a clean 503; validation responses omit submitted credential values.
  Identity responses use `Cache-Control: no-store`.
- localStorage is readable by JavaScript on this origin. Short expiry/revocation
  reduce exposure, but do not make it immune to XSS. Public production still needs
  deployment hardening and the earlier provider readiness work.

## Applied setup and verification

Migration **021_identity_sessions.sql** is applied to the sandbox. A private random
`AUTH_JWT_SECRET` was generated in `.env`; it is never committed. Existing accounts,
roles, passwords, provider credentials and financial records were preserved.

Verification included 62 focused automated test executions, a real Supabase
rollback-only encrypted-session/revocation/private-grants probe, browser checks
for responsive login, role badges, profile editing, reload restoration and logout,
and existing enterprise navigation checks. Browser login tests use controlled API
responses; no real user password was requested or used. A genuine password login
must be performed by the account holder in the app.

The visually reviewed login screenshot is `login.png`. Browser tests inspect
anonymous sample renderers only through an explicit test-harness override; this
does not introduce a production preview bypass in the application.
