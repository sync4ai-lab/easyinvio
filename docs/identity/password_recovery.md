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
