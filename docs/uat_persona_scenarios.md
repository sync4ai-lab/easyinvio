# MKR enterprises UAT persona test pack

The private setup SQL and account report are in output/mkr-uat. They contain the user-requested account details and are deliberately excluded from Git synchronization. The reusable read-only query pack is docs/uat_persona_scenarios.sql. It is scoped to the marked MKR sandbox workspace. Running it in SQL Editor does not exercise application permissions because SQL Editor uses an administrator connection.

The two requested support accounts are EasyInvio platform Agents, not members of the sample customer business. Migration 048 introduces the server-only staff registry. Their original Auth UUIDs and profiles are retained; the mistaken active MKR tenant memberships are disabled and previous app sessions revoked. They must sign in again to see the platform support console. The sample MKR workspace, addresses, products and historical references remain intact. To operate within it, an Agent must select it through audited client assistance.

The role and capability reference is /help/team-and-security (source docs_team_roles.md). Platform Admin means the configured SUPER_ADMIN, while legacy tenant ADMIN is a separate customer role that grants no platform privilege.

Use Forgot password in the application to set each new password. Initial random passwords were discarded. No invitation or recovery email was sent during setup. The shared phone number is profile contact data; it is not two verified WhatsApp identities. Bind it to only one chosen account through the normal verification flow.

The public-address examples are for formatting only and do not assert that MKR occupies the premises. Validate through PAF before quoting and never physically dispatch to these example addresses. No company registration number or legal ownership verification was fabricated. The two suggested product HS codes remain unreviewed and need customs classification review. The wallet starts at zero. Use the Stripe TEST top-up flow; do not insert artificial ledger credits.

| Persona | Scenario | Expected result |
|---|---|---|
| OWNER / assisted client | View MKR company, both members, four saved address roles, customer and products | All records are within MKR UAT; support identities have no active customer membership. |
| OWNER | Test owner-only team or billing settings using a separately authorized OWNER membership | Ownership is checked by backend role; ADMIN setup does not silently create an owner. |
| DISPATCHER | Prepare a parcel from a saved pickup address; choose a distinct saved recipient; validate UK addresses | Each side remains independent; no label is purchased by address lookup or quote generation. |
| DISPATCHER | Enter goods total 0.50kg with packed weight 0.40kg | Packaging validation blocks comparison and explains the mismatch. |
| DISPATCHER | Use the two saved products and enter measured outer dimensions | Quote only after valid packing; suggested HS classification does not count as reviewed customs. |
| DISPATCHER | Attempt arbitrary wallet funding or billing setup with a DISPATCHER session | Backend rejects unauthorized operations; hiding a button is not the only protection. |
| ACCOUNTANT | View wallet/ledger and permitted financial reports; attempt shipment purchase | Financial visibility follows backend permissions; unauthorized label purchases are rejected. |
| OWNER / assisted client | Start with zero balance and attempt wallet-funded booking | No invented credit; insufficient-funds response and no carrier purchase. |
| OWNER / assisted client | Fund through Stripe TEST, compare rates, select a carrier, pay by card | One verified payment and at most one label; refresh/retry does not purchase twice. |
| OWNER / assisted client | Let a quote expire, then use Requote | Original shipment details restored; fresh rates required before purchase. |
| Tracking user | View booked label before a carrier scan | Booked is not delivered; POD stays unavailable without evidence. |
| OWNER / assisted client | Try a return before delivery, then after a genuine TEST delivered event | Eligibility and original/child links enforced; customer-paid label withheld until verified payment. |
| Claims/support user | Open a missing/damaged parcel support case without purchased insurance | Support ticket is distinct from an insurer claim or settlement. |
| Any persona | Try another tenant's shipment UUID | Access denied or not found; no cross-tenant data or documents. |
| Platform administrator | Inspect MKR through existing authorized platform support view | Agents use the staff registry; do not add them to PLATFORM_ADMIN_USER_IDS. |
| Sender communications | Book with an allowed test sender email and explicit WhatsApp consent if configured | Outbox explains READY, SKIPPED, FAILED, REVIEW_REQUIRED or ACCEPTED; no automatic replay of uncertain sends. |

To exercise customer personas, use separate customer identities and the Owner's supported team invitation workflow. Do not convert support Agents into customer employees or restore the obsolete ADMIN seed setup. A staff user tests Owner operations through assistance; actual Dispatcher/Accountant authorization must also be tested with separate customer accounts. Invitations offer Dispatcher and Accountant only.

Tracking, delivered, refund, return-payment and insurer outcomes must come through their existing test integrations and signed events. This pack does not fake paid labels, refunds, delivered scans, insurance cover or settlements. Empty result sets before exercising those workflows are expected.

## Import examples and expected results

The private local pack also includes sample_orders.csv and invalid_orders.csv. Both use the application's extended CSV headers and were checked by the real parser without calling any carrier or importing any shipment. The positive file has one domestic parcel (0.750kg, 30x20x10cm), one document letter (0.100kg), one non-stackable pallet (150kg, 120x80x100cm), and one France export deliberately awaiting customs classification, origin/net-weight and signer review. Use the existing CSV order-import screen to exercise its real persistence and quoting workflow.

The negative file contains a zero-length parcel, an invalid recipient phone, and a 0.600kg letter. All three are rejected by the parser. Do not combine expected failures with a production customer import. No order rows, paid labels, shipments, carrier accounts or tracking events were inserted by the setup itself.

The supplied shared profile phone was already bound to another account for WhatsApp. That existing identity/binding was preserved. The two new accounts are ready for web sign-in after password recovery; their contact phone is not permission to take over the existing WhatsApp identity. Notification UAT allowlists also remain unchanged.
