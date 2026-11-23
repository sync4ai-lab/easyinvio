# Local simulated carrier and insurer testing

The Provider Lab lets us build and test the shipping and claims journeys before Royal Mail, Evri and Cover Genius issue their onboarding packs. It runs separately from the normal EasyInvio app and uses fictional accounts, prices, documents, policies and balances. No database, carrier API, insurer API, payment service, model or WhatsApp transport is used.

## Start and open the lab

In PowerShell:

```powershell
cd C:\Projects\easyinvio\tmp\local-development
.\.venv\Scripts\python.exe scripts/provider_lab.py
```

Open **http://127.0.0.1:8010/**. Your normal app can keep running on port 8000. If the lab is already running, open the URL without starting a second copy. Close its terminal with Ctrl+C to stop it. All dummy data disappears when that process restarts.

For a phone on the same trusted Wi-Fi, restart the lab with:

```powershell
.\.venv\Scripts\python.exe scripts/provider_lab.py --lan
```

Run `ipconfig` on your laptop, find its Wi-Fi IPv4 address, and open `http://THAT-IP:8010/` on the phone. `0.0.0.0` is a listening address, not the phone's destination URL. Windows may need permission for Python on your private network. Use fictional data only; these two demo workspaces are rehearsal identities, not real authenticated accounts.

## Dummy settings

The launcher reads **`.env.providers-demo.example` only** by default. Its three values are deliberately fake:

```dotenv
PROVIDER_LAB_ENVIRONMENT=SIMULATED
PROVIDER_LAB_ACCOUNT=DEMO-EASYINVIO
PROVIDER_LAB_EVENT_SECRET=DEMO-ONLY-DO-NOT-USE-IN-PRODUCTION
```

The runner rejects LIVE/TEST mode, non-demo account/secret values and unrelated configuration keys. Do not pass `.env.local`, put real keys into this file or import it into Vercel. No real provider flags are enabled. The normal `.env`, `.env.local`, `.env.uat` and provider registries remain unchanged.

## What to test

| Step | Action | Expected result |
|---|---|---|
| 1 | Keep Merchant A selected and request rates | Two explicitly simulated Royal Mail/Evri offers, sorted by dummy price. Postcode syntax and parcel bounds are checked without PAF/network lookup |
| 2 | Choose PLATFORM, then TENANT connection mode in separate quotes | Platform account IDs are shared; tenant account IDs differ by dummy workspace. Offers remain scoped to the requesting workspace |
| 3 | Confirm a dummy booking without protection | Label PDF marked SIMULATED; no insurance policy. Only the in-memory dummy balance changes |
| 4 | Request another quote; select demo protection and accept demo terms before booking | Dummy premium GBP1.20 and goods value GBP25; a DEMO-POLICY reference appears. No real policy exists |
| 5 | Select Carrier rejects request | Explicit rejection, no label or debit. Change the scenario or request another quote to retry |
| 6 | Select Timeout after carrier acceptance | Click Reconcile last uncertain booking. The accepted booking is recovered without a second label/debit. A repeated identical request is also idempotent |
| 7 | Manifest booked parcels for one carrier | Exact selected membership, a simulated PDF and MANIFESTED state. `carrier_closed=false`; no carrier has accepted the paperwork |
| 8 | Simulate in transit, then delivered | Deterministic scan history. Invalid/terminal transitions are refused |
| 9 | Cancel a separate unmanifested booking | Dummy debit reversed once. Cancellation after manifesting or opening a claim is held for review |
| 10 | Prepare a return for a delivered parcel | Marked dummy PDF and QR downloads. The QR encodes a demo-only string, not a usable carrier barcode. No postage is purchased |
| 11 | Open a damage claim | Description/value required. Submission waits for a valid PNG/JPEG photo. Duplicate photos are deduplicated |
| 12 | Submit a protected parcel's complete claim | Simulated XClaim route and SUBMITTED state. No real insurer submission or payout |
| 13 | Simulate insurer approval | APPROVED status only; no dummy or real credit yet |
| 14 | Simulate confirmed receipt | Matching approved amount and confirmed demo master-payee receipt add one in-memory DEMO_SETTLEMENT entry. No real wallet credit occurs |
| 15 | Open a claim for an unprotected parcel | Remains in MERCHANT_CARRIER_REVIEW; no invented insurer coverage |
| 16 | Switch to Merchant B | Merchant A's offers, shipments, claims and documents are inaccessible through Merchant B. This tests data scoping, not production authentication |

All displayed prices and transit days are arbitrary test fixtures, not market estimates or negotiated provider tariffs. The dummy wallet starts at GBP100 per workspace; restarting resets it. Documents are clearly marked and cannot be used to post a parcel. The lab's combined booking/cancellation examples rehearse a desired journey; they do not establish provider-specific cancellation or protection refund rights.

## Free chat rehearsal

The lab's chat box accepts:

```text
Hello
Quote 2kg from LS12 6EJ to B69 3EB 25x20x15
Book 1 insured
Track <demo shipment UUID>
Return <demo shipment UUID>
Claim <demo shipment UUID> damaged
```

Use the panels for manifests, scans, evidence and insurer events. The chat parser is deterministic and makes no AI calls. It is not connected to your phone's WhatsApp account. Messages sent through the real Gupshup number still use the existing integration and may be charged. There is no change to that callback or consumer in this work.

## Implementation boundaries and replacement plan

`backend/provider_simulation.py` supplies a fake `DirectCarrierContract` and exercises the existing `RoyalMailStrategy`/`EvriStrategy` quote validation. It adds an isolated state machine for booking, cancellation, manifests, scans, returns, protection, evidence and insurer decisions. `backend/provider_lab.py` exposes these only in a separate development app. The normal FastAPI app does not mount these routes; the dummy implementations are never registered as real providers.

The simulated insurance/claims controller is not a new XCover wire protocol. The existing real integration remains in `shipment_protection.py` and `xcover_claims.py`, with its actual permission, product, settlement and payment guards. Dummy photo checks reuse the actual evidence image validator. The lab does not certify PAF addresses, apply real tax/pricing, enforce a merchant's real return policy, submit real claims or approve compensation.

When the onboarding packs arrive, replacing `.env` values alone will **not** complete Royal Mail/Evri. We still need their issued HTTP authentication/paths, rates or tariffs, service eligibility and lifecycle mappings, then sandbox certification before registering transports in the main application. For XCover/XClaim, we need the issued credentials, approved product/terms/pricing, real FNOL field bindings and payment/settlement mapping. Its cancellation/amendment flow remains pending provider specifications. [Provider onboarding](provider_onboarding.md) lists exactly what to request tomorrow.

The next integration step is to connect approved provider transports to the existing main-app wallet, tenant permissions, entitlements, persisted idempotency, tracking and return/claim services. An in-memory rehearsal is not evidence that those live provider contracts have been implemented or certified.

## Offline verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_provider_simulation.py -q
```

`tests/provider_lab_browser.py` runs the mobile browser journey against a separately running lab on port8010 and asserts no external requests. It creates dummy records; restart the lab afterward for an empty workspace. Set `BROWSER_CHANNEL=msedge` if needed. The tests exercise consent, duplicate requests, uncertain acceptance, expired offers, cross-workspace denial, manifest/return transitions, photos, forged events and exactly-once dummy settlement.
