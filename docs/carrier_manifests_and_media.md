# Carrier manifests and paperless WhatsApp media

Implementation reference: 21 October 2026, migration 044 after 043. This change adds deterministic carrier close-out preparation and private image publication; it does not apply migrations, upload real assets, buy labels, schedule pickups or send messages during development verification.

## Activation

1. Install the updated requirements. PyMuPDF is used to rasterize actual single-page carrier SVG/PDF assets; Pillow validates/re-encodes PNG/JPEG. Existing ReportLab generates the internal handover sheet.
2. Apply the complete `migrations/044_carrier_manifests_and_media.sql` script without wrapping it in another transaction. Its first explicit transaction commits any shipment enum addition before the next transaction uses MANIFESTED. Existing status CHECK constraints are extended without dropping their prior permitted values.
3. On Supabase the migration creates the **private** `easyinvio-logistics` image bucket when Storage is present. The default bucket is protected by a restrictive anon/authenticated object policy; browser clients do not receive write or direct read access. If using a custom `LOGISTICS_MEDIA_BUCKET`, provision equivalent private policies separately. The runtime refuses an accidentally public bucket.
4. Retain the normal server-only Supabase service key, approved `PARTNER_DOCUMENT_ALLOWED_HOSTS`, Fernet key ring and Twilio settings. Configure `BOOKING_PAGE_URL` to this application's public HTTPS origin and a strong `QUOTE_LINK_SECRET`. Signed document links cannot work from a remote phone if they point to localhost.
5. Restart using `python -m uvicorn main:app --host 127.0.0.1 --port 8000` in the existing virtual environment. Twilio-enabled startup requires migration 044 and its outbox columns. The local Twilio-only tunnel forwards the new outbound-status callback path automatically; do not expose a general application proxy.

No additional storage key is exposed to a browser. Object paths are immutable `<tenant UUID>/<shipment UUID>/<SHA-256>.png`; signed read access lasts 24 hours. This is a private bucket with expiring capabilities, not a globally public bucket described as “signed.” Lifecycle/retention deletion for expired media and stored PDFs must be configured by the operator; unresolved shipment/manifest evidence must not be deleted as a retry workaround.

## Paperless document pipeline

The existing native booking/return services remain authoritative. A confirmed label with a real QR asset may contain a provider HTTPS URL, an inline SVG or a Base64 image. The adapter retains supported optional QR fields without invalidating a separately confirmed label. No QR is synthesized from a tracking number or an ordinary URL.

`carrier_document(..., 'return-qr', ...)` resolves tenant-bound confirmed shipment metadata. External URLs must match an approved document host; historical carrier authentication remains server-side, downloads are bounded and redirects are disabled. Inline SVG rejects scripts, external resources, document types and unsupported active elements. Single-page SVG/PDF is rasterized with bounded page/pixel limits. PNG/JPEG is decoded and re-encoded, metadata removed and transparency placed on a white background. Unsupported/oversized assets fall back to the existing viewing/document workflow.

`QRMediaService` verifies the private bucket, uploads the image once under its tenant/shipment/content digest, records `logistics_media_assets`, and requests a 24-hour read URL from Supabase Storage. Native booking/return results include `media_urls`, `media_view_url`, expiry and media status when publication succeeds. A publication/signing failure retains BOOKED, the purchased label and the secure viewing link; it cannot release/refund/capture funds or purchase a replacement label.

The conversational message/outbox schemas support media URLs. User-supplied chat URLs are not permission to fetch or forward arbitrary content. The WhatsApp worker admits only the server's scoped return-document proxy or that tenant/shipment's signed Storage namespace, and calls Twilio REST with `media_url=[url]`. A QR is usable only at the selected carrier/service's participating locations; the application does not claim universal Royal Mail, Evri, InPost or other carrier paperless support.

### Delivery fallback and callbacks

An immediate, definite media rejection (400/415/422) stages one new **text-only** fallback part containing the secure viewing link. A transport timeout or ambiguous server outcome does not automatically send another message. Original receipts and action outcomes remain unchanged.

Media sends set `status_callback` to `/api/v1/integrations/whatsapp/outbound-status/{part_id}` on the configured canonical public webhook origin. The callback verifies the Twilio signature over every form field, account, outbound MessageSid and From/To numbers. A signed failed/undelivered status stages the same unique fallback. `fallback_for` uniqueness prevents duplicate callbacks from generating duplicate fallback parts. The callback may positively reconcile an uncertain REST acceptance, but READY resumes only delivery parts; it never executes the original logistics action again.

REST acceptance is not device delivery. Twilio account permissions, public reachability, media/content limits and actual device delivery need sandbox/live acceptance. If even the text fallback is rejected, record/inspect the failure through Twilio and support; do not loop sends or reset an uncertain action receipt. Free-form service-window rules still apply to queued fallback messages.

## Manifest APIs

All workspace operations require an active OWNER, ADMIN or DISPATCHER. Current role/workspace/environment is checked before close-out; an active audited platform assistance session can supply the support owner context. Request tenant parameters cannot switch workspaces.

| Method | Endpoint | Contract |
| --- | --- | --- |
| POST | `/api/v1/dispatch/manifests/preview` | Optional `warehouse_id`; exact counts/packed weights grouped by account, physical carrier and pickup origin |
| POST | `/api/v1/dispatch/manifests/close` | Required stable `request_id` and `carrier_account_id`; optional `carrier_code`, `warehouse_id` |
| GET | `/api/v1/dispatch/manifests/{id}` | Tenant-authorized status; read-only recovery of a known native ScanForm reference |
| GET | `/api/v1/dispatch/manifests/{id}/document` | Authenticated completed PDF download |
| GET | `/api/v1/dispatch/manifests/{id}/download?token=...` | Expiring signed capability for precisely that tenant/manifest PDF; no workspace access |

Only BOOKED, unmanifested, non-cancelling shipments in the configured environment are selected. Warehouse filters use the existing `tenant_catalog_addresses` PICKUP/SENDER records and the physical origin snapshot, excluding contact-name differences. A manifest cannot mix physical carriers or pickup premises. Existing unsupported/missing multi-piece purchase references require reconciliation instead of inventing parcel membership.

Each close processes at most 1,000 selected shipments, matching the bounded native ScanForm workflow. Preview counts include all eligible rows. The result explicitly identifies the 1,000-shipment limit when reached; preview/close remaining batches with new request IDs. A replay of the original key observes the original batch, including after new shipments arrive. It never consumes those new shipments.

## Provider contracts and internal sheets

EasyPost uses the documented `POST /v2/scan_forms` with a top-level `shipments` array of actual purchased shipment IDs. Same carrier account/origin, valid label dates and carrier support remain upstream requirements. The returned ScanForm ID is stored before document retrieval. Only a created form with matching tracking membership and a valid PDF from an approved host can complete. Pending/uncertain submissions remain fenced; later status requests GET the existing ScanForm rather than POST again. A carrier-returned failure is recorded without reassigning those shipments to a new submission.

**No generic Sendcloud `/api/v2/manifests` API is assumed.** The current public Sendcloud catalog does not establish that contract. Sendcloud and other regional/direct connections receive an `INTERNAL_HANDOVER` ReportLab PDF when a verified native close-out contract is unavailable. Its Code128 `EI-...` identifier is an internal handover ID, not a carrier tracking number. The sheet includes tracking references, destination postcodes, exact packed weights, totals, page numbers and blank driver/signature/time fields. It explicitly states that it is not a carrier-issued acceptance ScanForm. `carrier_closed=false` remains visible in the result.

Carriers requiring official Royal Mail/other close-out paperwork must still use the verified provider panel/contract-specific process until its exact API is implemented. A generated internal PDF is not a substitute for mandatory carrier paperwork and does not schedule collection, prove pickup or invent a tracking milestone. See [EasyPost ScanForm](https://docs.easypost.com/docs/scan-form) and Sendcloud's [documented Royal Mail guidance](https://support.sendcloud.com/hc/en-gb/sections/4405630539540-Royal-Mail).

## Locking, state and finance

The database stores `carrier_manifests`, immutable `carrier_manifest_events` and a tenant/account-consistent `shipments.manifest_id`. The service takes the tenant/account advisory transaction lock, then the existing per-shipment cancellation lock namespace and row locks. It rechecks BOOKED status and cancellation absence, commits the SUBMITTED record and exact shipment snapshot, and releases the transaction before any provider request or PDF rendering. Concurrent close requests cannot claim the same shipment. Cancellation refuses a claimed manifest shipment before any provider void/refund request.

Completion persists the actual carrier PDF or internal PDF bytes privately in PostgreSQL, appends the audit event and moves only still-BOOKED selected rows to MANIFESTED. An intervening carrier transit/delivery update is not regressed. The existing commit-time dispatch event trigger updates warehouse monitors. MANIFESTED is recognized by label/document access, tracking, protection/claims, reporting and booking replay; it cannot authorize a second purchase. The new service does not mutate wallets or financial ledger balances.

SUBMITTED with no provider reference after an interruption requires operator reconciliation against carrier records. A known reference supports GET-only recovery. Do not blindly retry a carrier POST, clear shipment claims, or label a failed/pending batch as carrier-accepted. FAILED batches retain membership claims for reviewed remediation. Actual carrier acceptance and handover are separate from document preparation.

## Verification

The full scoped `tests` suite passed **945 tests, one skipped and 14 subtests**, with two existing collection warnings. Tests cover role/tenant boundaries, exact weights, same-key replay, competing closes, 1,005 shipments split into bounded batches, native membership/document checks, timeout fences, private Storage signing, image sanitization, forged/repeated delivery callbacks, immediate/async media fallback and existing financial/shipment workflows. A synthetic 60-shipment, three-page handover PDF was rendered and visually inspected.

No migration, real Storage upload, live carrier close-out, payment or Twilio message was executed. Actual PostgreSQL contention/migration application, provider-contract eligibility, private bucket policies, licence/dependency deployment, document-host approval and real phone delivery remain staging acceptance gates.
