# Sender shipment updates and checkout

## Address and contact selection

Saved pickup/delivery addresses are displayed as readable lines. They fill only the selected side. Choose the correct country and click **Validate UK address / find building**, next to the country selector, then choose the exact PAF building or flat. The control remains visible if a saved address fills the country programmatically. UK PAF does not verify foreign addresses.

Contact shortcuts copy name, company, phone and email between pickup and delivery; they do not replace the street, town, postcode or country. Sender email updates use the pickup/sender email, not the recipient email or the workspace billing email. WhatsApp updates require an international sender phone number and explicit permission on the shipment form.

## Domestic checkout and quote expiry

Routes for which the backend says customs are not required go directly to booking confirmation. They do not show an unnecessary export-document question. Export goods that need a declaration must still supply accurate carrier customs information, even if the customer already owns an invoice; a handwritten invoice does not bypass the carrier data requirement.

QUOTE_TTL_SECONDS defaults to 300 seconds (five minutes), allowed 30 through 900. Expiry starts at quote generation; selecting a service does not extend it. Checkout displays the actual expiry. A preparation that returns a fresh quote has its own expiry. A payment page is not an indefinite shipping-price guarantee. If payment succeeds after the shipping offer expires, unused verified funds remain in the wallet and the existing reconciliation flow tells the user to obtain fresh rates rather than paying twice.

## Test tracking and paperless drop-off

EasyInvio preserves the tracking reference returned by the provider; it never invents a real tracking number. Test providers may supply dummy/all-zero references and labels that must not be dispatched. The completion screen identifies TEST bookings. Live financial settlement rejects an all-zero placeholder and leaves the outcome for reconciliation rather than capturing a fictitious dispatch.

The confirmation screen offers **View carrier drop-off QR code** only when the purchased carrier service actually provides a QR asset. PDF labels remain available. If no carrier QR was returned, the screen explains that the printed carrier label is required. A QR invented from an ordinary tracking number is not a carrier-approved paperless label. Paperless support depends on provider, service and drop-off location; supported returns retain their existing QR workflow.

## Sender milestones

Migration 047 adds the private shipment_sender_notifications outbox. Triggers enqueue BOOKED, MANIFESTED, DISPATCHED, IN_TRANSIT, OUT_FOR_DELIVERY, AVAILABLE_FOR_PICKUP, DELIVERED, EXCEPTION, RETURNED_TO_SENDER and CANCELLED when corresponding confirmed facts arrive. Booking means label creation, manifested means handover preparation, and delivered means a carrier delivery event; these meanings are kept distinct in the messages.

A message is queued once per shipment/category/channel, within the same database transaction as the event. Replayed scans, stale unapplied events and incomplete multi-piece delivery do not create duplicate or premature delivered notices. There is no backfill of shipments that existed before migration 047. Tracking visibility/in-app preferences remain separate from these sender delivery preferences.

The background worker sends email through Hostinger SMTP from support@easyinvio.com and WhatsApp via an approved Twilio utility template. The shared backend/email_delivery.py transport uses certificate-verified SSL on port 465, or mandatory STARTTLS on port 587, and runs blocking SMTP work off the asynchronous event loop. SendGrid is available only when explicitly selected; there is no automatic failover or SendGrid charge from a Hostinger SMTP send. It commits SENDING before external I/O. ACCEPTED is provider acceptance, not inbox/handset delivery proof. Explicit SMTP temporary refusals (4xx), connection failures before submitting a message, and HTTP 429 refusals retry up to three attempts with a one-minute delay in the sender outbox. Permanent SMTP rejection fails without retry. A lost connection during message submission is uncertain and is never automatically retried. A failed SMTP QUIT after message acceptance does not resend the accepted message. Timeouts, interrupted sends and unclear provider outcomes enter REVIEW_REQUIRED without automatic resend. Definitive rejection is FAILED; disabled channels, missing consent, missing contact, mismatched environments or unapproved test recipients are SKIPPED with a reason.

The authenticated GET /api/v1/shipping/{shipment_id}/sender-notifications endpoint returns only the caller workspace's status records and no recipient addresses. Booking confirmation shows these outcomes. A messaging failure does not cancel a paid shipping label or cause another carrier purchase.

## Enable sender email updates in UAT

1. Apply the complete migrations/047_sender_shipment_notifications.sql to the same isolated test database, after 046.
2. In Hostinger hPanel, open Emails, choose easyinvio.com, and create or confirm the support@easyinvio.com mailbox. Use its mailbox password, not your Hostinger account password. Confirm domain email DNS is configured in Hostinger.
3. Save these values in local .env and Vercel Environment Variables for the deployed environment. Do not put passwords in Git or chat:

   ```dotenv
   EMAIL_DELIVERY_PROVIDER=HOSTINGER_SMTP
   SMTP_HOST=smtp.hostinger.com
   SMTP_PORT=465
   SMTP_USERNAME=support@easyinvio.com
   SMTP_PASSWORD=your-private-mailbox-password
   SMTP_TIMEOUT_SECONDS=10
   SHIPMENT_EMAIL_NOTIFICATIONS_ENABLED=true
   SHIPMENT_EMAIL_FROM=support@easyinvio.com
   RETURN_EMAIL_ENABLED=true
   RETURN_EMAIL_FROM=support@easyinvio.com
   ```

   The SMTP login and From address must match. Use a real mailbox with its own password; a Hostinger alias has no separate SMTP login. The deployed mailbox is support@easyinvio.com. Port 587 is an alternative with mandatory STARTTLS; plaintext SMTP is not supported. Legacy SendGrid API keys are not required and are ignored while Hostinger is selected. Each email channel remains disabled until its enable flag is true and valid credentials exist.
4. Save SHIPMENT_NOTIFICATION_TEST_RECIPIENTS as a JSON list of your own test email addresses and phone numbers, such as ["tester@example.com","+447700900111"]. No TEST sender milestone message goes to a recipient outside this list. Return notices use their existing customer permission and contact checks; use only your own test customer contacts in UAT.
5. Redeploy the web application and logistics worker. Enter your allowed test email in sender contact details, leave email updates enabled, and book a test shipment. Check the notification receipt on confirmation and verify the actual inbox. Test a paid return separately with customer delivery permission enabled. ACCEPTED means the SMTP server accepted the message, not that the recipient inbox delivered it.

## Return emails and other communications

Shipment and return workers share the Hostinger transport but retain separate enable flags, consent and outboxes. Customer-paid returns send a payment link first; signed label links are released only after verified payment and carrier booking. The existing return outbox does not automatically retry refusals: definitive refusal is FAILED and an uncertain submission is REVIEW_REQUIRED. No new database migration is required for the SMTP transport; migrations 046 and 047 remain required for their respective queues.

Supabase Auth login, OTP and password-reset mail uses its own SMTP configuration in the Supabase dashboard. Changing this application transport does not change Supabase Auth or cancel any SendGrid subscription. Carrier events arrive through configured tracking webhooks or supported polling, independently of outbound email. This worker does not read the Hostinger inbox or ingest email bounce/delivery notifications. WhatsApp remains on Twilio.

SendGrid can be deliberately selected later with EMAIL_DELIVERY_PROVIDER=SENDGRID and the corresponding SHIPMENT_SENDGRID_API_KEY / RETURN_SENDGRID_API_KEY plus a verified From address. A missing Hostinger password never silently switches providers.

## Enable WhatsApp updates

Use existing TWILIO_ENABLED/account credentials/sender settings. Set SHIPMENT_WHATSAPP_NOTIFICATIONS_ENABLED=true and SHIPMENT_WHATSAPP_CONTENT_SID to an approved utility template Content SID (HX...). The template must accept variables 1=booking reference, 2=milestone message, 3=tracking reference. Confirm sender WhatsApp permission on the shipment form. Template approval, sender access and Sandbox membership restrictions still apply; adding a phone number alone does not authorize messaging. UAT messages carry explicit test wording. Provider/WhatsApp recipient opt-out enforcement must remain enabled for the sender; do not bypass provider opt-out rejections.

Credentials remain server-side. Senders cannot receive real carrier movement in test mode unless the provider emits test events or a controlled test webhook is submitted. The new worker runs in the dedicated logistics daemon or local combined runtime; the Vercel HTTP function does not run continuous notification loops.
