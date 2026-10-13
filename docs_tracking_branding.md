# Follow tracking updates and understand delivery history

This guide is for dispatch teams and customers comparing services. EasyInvio.com separates recorded milestones and measured history from carrier estimates and demonstration data.

## Current availability

EasyInvio parses tracking notifications from EasyPost, Sendcloud and Shippo. Notifications must arrive through the configured, authenticated provider connection and match a shipment in the correct workspace.

A confirmed label does not guarantee every tracking scan, photograph or signature will be supplied. The carrier and aggregator control which events and evidence are available for a service.

## How a tracking update is accepted

The shared native endpoint is `POST /api/v1/shipping/tracking-webhooks`. Platform administrators configure the provider source and required authentication. Clients cannot simply post a new delivery status to this public route.

The receiver checks the source, request format and authentication. Provider-specific signatures or supported token/source restrictions apply. A customer sign-in token does not replace provider webhook authentication.

The tracking reference must match the connected account and shipment. Invalid authentication, unmatched tracking and ambiguous references are rejected or require review. Repeated accepted event identities do not apply the same update twice.

A public HTTPS receiver is needed for genuine provider delivery. Local-only development can test controlled events but cannot establish that internet providers have delivered real notifications.

## Milestones in the workspace

Native events map into EasyInvio shipment states. In-transit, out-for-delivery and related movement can be represented by IN_TRANSIT; exceptional events become EXCEPTION; final delivery becomes DELIVERED.

Manifest & Labels shows recorded shipments and confirmed documents. Refresh when necessary. A missing scan can mean that the carrier has not scanned the parcel, the provider has not supplied that milestone, or the integration needs investigation.

For a multi-box shipment, each package has its own label and tracking reference. The group becomes delivered only when all deliveries are confirmed. Box 1 arriving does not close the entire group.

Older events cannot ordinarily move a delivered parcel back into transit. A late proof-of-delivery update can add permitted evidence without creating another label purchase.

## Delivery exceptions and support

A carrier exception creates a support review trail and can update the shipment's exception state. Approved, configured messaging can be staged for eligible recipients. WhatsApp requires verified contact binding, consent, provider configuration and a permitted template; delivery is not guaranteed for every scan.

Internal label-preparation and purchase failures are separate support issues. They do not establish a delay for a parcel already in the carrier network. EasyInvio administrators review internal processing failures.

Verified final delivery can resolve tracking-related support cases. Insurance claims and unrelated reviews have separate handling and are not automatically resolved as the same exception.

## Branding, links and delivery evidence

The workspace uses EasyInvio identity and carrier names. Standard client quote responses suppress internal supplier identifiers. Authorised label/document downloads use application routes rather than exposing private execution details directly.

These controls do not provide a configurable public recipient tracking site with each merchant's logo, domain, colours and message templates. That branding product is not implemented.

External carrier or aggregator tracking pages and supplier documents may display their own branding. EasyInvio cannot guarantee removal of every downstream reference from those external pages.

A permitted photo or signature link can be stored when a verified event supplies it. There is no universal automatic photo-notification service. A missing photo is not proof of failed delivery.

## How delivery history is measured

Measured history is workspace-specific and uses a rolling 90-day window. Standard route comparisons can filter pickup and delivery countries; service-level comparisons distinguish the service where data exists. A destination-only summary is broader than a complete origin-and-destination service lane.

TEST shipments and identified synthetic fixtures are excluded from real performance. Connecting an aggregator does not import a global carrier reputation score.

Average transit uses completed deliveries with a recorded dispatch time or first accepted in-transit event and a delivery time. Booking time never substitutes for missing dispatch data. The mean is expressed in elapsed calendar days.

On-time percentage uses qualified delivered shipments with a saved numeric business-day estimate. It compares elapsed weekdays with that estimate. Weekends are excluded; public holidays are not adjusted. The on-time sample can therefore be smaller than the transit sample.

Without qualifying deliveries or saved estimates, the corresponding metric remains unavailable. A missing score is not zero. An absence of reported exceptions does not prove excellent service without meaningful history.

## Use the figures when choosing a service

Check sample count, service, route and measurement method alongside price. One measured delivery is less informative than a larger record. A historical average is not a guaranteed arrival date.

Risk indicators reflect recorded active exceptions and measured results. They are observed-history indicators, not independent carrier certification or a promise of future reliability. EasyInvio does not automatically replace your choice with the highest rated carrier for every order.

## Missing tracking or history: what to check

1. Confirm the booking has a carrier label and tracking number.
2. Check whether it used TEST or LIVE facilities.
3. Look for the reference on the carrier tracking page.
4. If that page has updates missing from EasyInvio, ask support to check receiver reachability, source configuration, authentication and accepted events.
5. For history, check that qualifying LIVE deliveries and saved estimates exist for the route/service being compared.

Provide the booking reference, tracking number, time and expected milestone. Do not send webhook signing secrets or access tokens.

[Contact EasyInvio support](/help/contact), [read about booking payments](/help/booking-payments), or [return to the Help Centre](/help).
