# Direct aggregator setup and safe Disable

**Add New Aggregator** now opens the complete setup form immediately. Enter the account name, environment, API endpoint and credentials in that form. Official EasyPost, Sendcloud and Shippo endpoints are detected automatically; Sendcloud exposes its public/secret key pair. The API integration format can also be selected inside the form. The separate picker dialog has been removed.

For supported providers, saving an enabled connection distributes it to eligible tenants and includes it in the existing concurrent rating, pricing-rule and carrier-consolidation engine. Keys remain encrypted on the server and are not returned to clients. Multiple connections using an existing supported API format require configuration, not another code change.

An arbitrary new API cannot be inferred from its name, URL and secret: authentication, rating, label purchase, customs, refunds and return schemas differ. A new native provider requires a reviewed adapter once. APIs implementing the approved EasyInvio `/rates` contract can use the custom format for quoting; their HTTPS origin must already be approved in server configuration. The form does not claim those connections can buy labels through an unknown protocol.

## Disable behavior

The row action is now **Disable**, using an authenticated POST endpoint. Disabled rows remain visible with a DISABLED status and editable settings. Enable them again through Edit Settings. Existing deprecated DELETE endpoints retain compatibility and perform the same safe disable rather than physically deleting records.

| Operation after disabling | Behavior |
| --- | --- |
| New outbound quote requests | Disabled connections are excluded by the active-account filter. |
| An unsubmitted outbound offer quoted earlier | Booking is rejected because the connection is disabled. |
| An already-submitted booking | Original credentials remain available for native reconciliation and once-only settlement; it does not issue another buy. |
| Return preparation and purchase | The server verifies an original outbound shipment in the requesting tenant, checks reversed addresses and obtains a fresh quote through its original connection, even when disabled. Existing wallet, customs, TEST/LIVE and provider capability guards still apply. |
| Cancellation/refund | Original connection and credentials remain available; credit requires confirmed cancellation and is applied only once. |
| Tracking, document access and fulfillment of existing paid shipments | Historical references and signing configuration remain intact. |

Historical return access cannot be selected by merely setting a client-controlled account ID. Both return quoting and booking verify the tenant-owned parent and its actual original carrier account. Arbitrary forward addresses cannot use the disabled-provider return exception.

## Verification

- **267 automated tests passed**, including new owner-authentication, active-account filtering, authenticated return-parent and historical return-rating checks.
- Administrator browser checks passed: the new form opens directly, detects the Shippo endpoint, preserves the account name, retains disabled rows and has no horizontal overflow at 375–1440px. Existing native settings browser checks also passed.
- [Actual sandbox database probe](database_probe.json) passed disable propagation to all mirrored accounts, preservation of ciphertext, outbound/stale-offer exclusion, in-flight reconciliation without a second purchase, return quote and booking, and once-only refund credit. Provider responses were controlled with MockTransport. All probe SQL writes were rolled back; no external carrier purchase or message was sent.

**No new database migration is required.** The implementation uses the existing connection is_active flag, retirement field and shipment/lifecycle tables through migration 024. No existing connection was permanently disabled during testing.
