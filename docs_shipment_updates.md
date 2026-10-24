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

The background worker sends email via SendGrid and WhatsApp via an approved Twilio utility template. It commits SENDING before external I/O. ACCEPTED is provider acceptance, not inbox/handset delivery proof. HTTP 429 refusals retry up to three attempts with a one-minute delay. Timeouts, interrupted sends and unclear provider outcomes enter REVIEW_REQUIRED without automatic resend. Definitive rejection is FAILED; disabled channels, missing consent, missing contact, mismatched environments or unapproved test recipients are SKIPPED with a reason.

The authenticated GET /api/v1/shipping/{shipment_id}/sender-notifications endpoint returns only the caller workspace's status records and no recipient addresses. Booking confirmation shows these outcomes. A messaging failure does not cancel a paid shipping label or cause another carrier purchase.

## Enable sender email updates in UAT

1. Apply the complete migrations/047_sender_shipment_notifications.sql to the same isolated test database, after 046.
2. Create/use a SendGrid API key with Mail Send permission and a verified sender. Supabase Auth SMTP alone does not enable these separate shipment emails.
3. Save SHIPMENT_EMAIL_NOTIFICATIONS_ENABLED=true, SHIPMENT_SENDGRID_API_KEY and SHIPMENT_EMAIL_FROM in Vercel and local configuration.
4. Save SHIPMENT_NOTIFICATION_TEST_RECIPIENTS as a JSON list of your own test email addresses and phone numbers, such as ["tester@example.com","+447700900111"]. No TEST message goes to a recipient outside this list.
5. Redeploy. Enter that test email in sender contact details, leave email updates enabled, and book a test shipment. Check the confirmation status and SendGrid activity.

## Enable WhatsApp updates

Use existing TWILIO_ENABLED/account credentials/sender settings. Set SHIPMENT_WHATSAPP_NOTIFICATIONS_ENABLED=true and SHIPMENT_WHATSAPP_CONTENT_SID to an approved utility template Content SID (HX...). The template must accept variables 1=booking reference, 2=milestone message, 3=tracking reference. Confirm sender WhatsApp permission on the shipment form. Template approval, sender access and Sandbox membership restrictions still apply; adding a phone number alone does not authorize messaging. UAT messages carry explicit test wording. Provider/WhatsApp recipient opt-out enforcement must remain enabled for the sender; do not bypass provider opt-out rejections.

Credentials remain server-side. Senders cannot receive real carrier movement in test mode unless the provider emits test events or a controlled test webhook is submitted. The new worker runs in the dedicated logistics daemon or local combined runtime; the Vercel HTTP function does not run continuous notification loops.
