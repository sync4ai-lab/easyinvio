# Password recovery setup

The login card includes **Forgot password?**, an email request form and a new-password confirmation screen. Passwords are changed by Supabase Auth, never by directly editing database hashes. Recovery requires a single-use `type=recovery` token hash verified by Supabase before any password update. Existing app sessions are revoked, and global provider sign-out is requested. No auto-login is granted after recovery.

## Required Supabase configuration

In **Authentication → URL Configuration**, add this exact additional redirect URL for local testing:

```
http://127.0.0.1:8000/
```

In **Authentication → Email Templates → Reset Password**, replace the reset action hyperlink with:

```html
<a href="{{ .RedirectTo }}#token_hash={{ .TokenHash }}&amp;type=recovery">Reset your EasyInvio password</a>
```

Keep other email branding/text as desired. This custom template is required: the default template returns a provider access token rather than the token hash accepted by this app. The fragment keeps the recovery credential out of server URL/access logs. The browser immediately clears it from the address bar and holds it only in memory until submission or cancellation. Do not reload the reset page before submitting; request another link if needed. Email scanners visiting a link do not consume it, because verification happens only when the new-password form is submitted.

`AUTH_RECOVERY_REDIRECT_URL` defaults to `http://127.0.0.1:8000/`. For hosted production, set it to the real HTTPS application URL and add that exact URL to Supabase's allowlist. A local link works only on the computer running the app. The restricted Twilio ngrok ingress is not an app-hosting URL.

Configure **Authentication → Email → SMTP Settings** with a verified sender for production email delivery. Supabase's built-in email service has testing restrictions and rate limits; do not assume it can deliver to every client. Configure password strength, leaked-password protection where supported, and recovery expiry in Supabase Auth. Application minimum password length is 12 characters.

## Verification and limits

Automated tests cover generic account-safe responses, valid recovery verification, expired-link rejection, password validation without input leakage and rejection of insecure redirect URLs. Browser checks cover the recovery forms, matching-password validation, removal of the fragment and successful return to login. No real email or password change is triggered by these tests. Finish by requesting a link for your own registered email after saving the Supabase template and redirect settings.

No additional SQL migration is needed; migration 021's private rate-limit and revocable-session tables are reused. Per-IP recovery requests are limited to ten attempts per 15 minutes, in addition to Supabase's provider limits. Unknown-email responses are generic. Unexpected provider or database failures do not expose credentials. If the password changes but provider sign-out fails, the UI explicitly reports partial completion instead of claiming everything succeeded.

Official reference: [Supabase password-based authentication](https://supabase.com/docs/guides/auth/passwords).


## SendGrid-backed WhatsApp onboarding

The production path is `ConversationalSignupManager.advance(PENDING_EMAIL)` ?
`send_codes` ? `SupabaseSignupProvider.send_code` ? Supabase Auth `/otp` ? the
project's custom SendGrid SMTP relay. This is a real asynchronous Auth request,
not a mock in application code. Auth creates the provisional identity; the app
records registration intent in migration 039's private queue. No direct insert
into `auth.users` or independently generated email OTP is used.

Configure Supabase Authentication's custom SMTP settings as follows:

| Setting | Value |
| --- | --- |
| Sender email | `operations@easyinvio.com` |
| Sender name | `EasyInvio Operations` |
| Host | `smtp.sendgrid.net` |
| Port | `587` (STARTTLS) |
| Username | `apikey` (the literal word) |
| Password | Your private SendGrid API key with Mail Send permission |

Verify the sender/domain in SendGrid first. Store the API key in Supabase's SMTP
configuration, not browser code or a committed environment file. The application
cannot enforce or inspect remote SMTP settings through its normal public Auth
key. Domain DNS verification alone does not configure Supabase's SMTP relay.
Disable SendGrid click tracking for authentication mail so recovery links are
not rewritten. Review provider and Supabase rate limits before client rollout.

Copy the complete [verification email template](email_templates/verification_otp.html)
into Supabase's **Magic Link** template and **Confirm signup** template, covering
both existing and newly created Auth identities. Use subject `Your EasyInvio
verification code`. Configure email OTP length to **6 digits** and expiry to
**900 seconds**. Supabase substitutes `{{ .Token }}`; our application generates
only the separate WhatsApp challenge. Codes are never sent to an LLM.

Copy the complete [password email template](email_templates/reset_password.html)
into **Reset Password**, with subject `Set your EasyInvio password`. After both
codes verify and the customer sends Continue, the existing provisioning
transaction commits before `/recover` requests a password-setup email. Its
single-use recovery token is issued by Supabase and delivered through SMTP;
the application never puts the credential in the WhatsApp reply or queue.
An unconfirmed email request does not roll back an already created workspace;
the reply points to Forgot password instead. The bounded request establishes
provider acceptance, not guaranteed inbox arrival.

### Recovery destination examples

`/set-password` now serves the same single-page frontend as `/`. Its existing
fragment handler opens the password form and clears the URL credential. Set
exactly one destination in the backend environment and the same exact value in
Supabase Auth's allowed redirect URLs:

- Current local backend: `AUTH_RECOVERY_REDIRECT_URL=http://127.0.0.1:8000/set-password`
- Local port 5000: `AUTH_RECOVERY_REDIRECT_URL=http://localhost:5000/set-password`
- Production: `AUTH_RECOVERY_REDIRECT_URL=https://easyinvio.com/set-password`

The chosen address must actually serve this application. For local port 5000,
start it with `.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 5000`.
Production reverse proxies must route `/set-password` to the application, not
an unrelated marketing website. Localhost links work only on the computer
hosting the app. Keep the existing local root redirect if it already works.

The email template produces the actual link in this form:
`https://easyinvio.com/set-password#token_hash=<Supabase-issued-hash>&type=recovery`.
Do not concatenate a token directly after the hostname, put it in a URL path,
or use a fabricated `password_reset_token` field. The hash is verified by
Supabase when the recipient submits a new password; simply visiting the link
is insufficient. No automatic web login follows password setup.

Save the SMTP/template/redirect settings, restart the backend after environment
changes, then run an authorized acceptance signup with your own phone and inbox.
Check the From address, six-digit email code, separate phone code, successful
activation, password form and one-time/expired-link behavior. Automated tests
use HTTP mocks and do not verify the remote SMTP account or send live email.
No new SQL migration is required for this refinement; migration 039 must
already be installed.

References: [Supabase custom SMTP](https://supabase.com/docs/guides/auth/auth-smtp),
[Supabase email templates](https://supabase.com/docs/guides/auth/auth-email-templates),
[SendGrid SMTP integration](https://www.twilio.com/docs/sendgrid/for-developers/sending-email/integrating-with-the-smtp-api).
