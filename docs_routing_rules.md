# Understand pricing rules and carrier choices

This guide explains EasyInvio.com's pricing evaluator. Configuration steps are for authorised platform administrators. A workspace owner can review shipping prices, but a workspace owner role alone does not grant access to platform pricing administration.

## Current availability

Connected, enabled providers are queried in parallel where their adapters support the request. EasyInvio calculates a customer price for each eligible service. The quote screen presents available choices in customer-price order.

Pricing rules set the markup applied to a rate. They do not hide every service except the one with the greatest platform profit. Automatic highest-profit carrier selection is not implemented.

## How a rule matches

The evaluator checks the workspace, quote currency, active state and validity dates. Additional criteria can include:

- A carrier connection, carrier or service.
- Pickup and delivery countries.
- Minimum or maximum billable weight.
- Minimum or maximum underlying shipping cost.
- Workspace billing plan or cargo classification.
- Minimum or maximum cargo volume.

A blank optional criterion means the rule does not restrict that attribute. A rule needing information unavailable in the pricing context cannot match that missing information.

Minimum weight, cost and volume boundaries are included; maximum boundaries are excluded. A band starting at 5 kg and ending at 10 kg includes 5 kg but not exactly 10 kg. Adjacent bands can therefore meet without both applying at the boundary.

For standard parcels, the quote pricing context uses billable weight, including per-box calculations for multi-piece cargo. This is not necessarily goods net weight or scale weight.

## Which matching rule wins

1. Lowest numeric priority.
2. At equal priority, more specific selectors.
3. At equal priority and specificity, older creation time.
4. If still tied, the stable rule identifier.

Priority 10 outranks priority 100. The rule name does not determine priority. Overlapping rules do not add their markups together: one matching rule is selected for each rate.

If no rule matches, the current implementation applies its established 20% default markup. Administrators should review this fallback before enabling a new workspace. Clients should use the displayed final price rather than reconstructing it from an internal rule.

## Fixed and percentage markups

A fixed rule adds a configured currency amount. A percentage rule applies a configured percentage to the underlying cost. Configured minimum and maximum markup amounts constrain the result.

For illustration, a GBP 20.00 underlying cost with a fixed GBP 3.00 markup produces a GBP 23.00 subtotal. A 10% rule produces GBP 22.00 before any other applicable price or tax treatment. These are calculation examples, not live rates.

Markup is not realised net profit. Taxes, protection costs, refunds, later surcharges and other business expenses can affect the outcome. See [Prices, currencies and extra charges](/help/prices-and-currencies).

## Configure a rule as a platform administrator

1. Sign in using an authorised platform administrator account.
2. Open Dynamic Margin Matrix and select the client workspace.
3. Add a descriptive name, currency, formula and priority.
4. Set only the lane, carrier, plan, cargo and boundary restrictions actually required.
5. Set validity dates, active state and minimum/maximum markup if needed.
6. Save and request fresh quotes for representative shipments.
7. Test below, at and above a boundary, plus an unrelated route to check the fallback.
8. Compare the customer total with the expected calculation before regular use.

Accepted booking snapshots retain their agreed price history. Changing or retiring a rule does not rewrite an already purchased label's price.

## Provider comparison and booking decisions

EasyPost, Sendcloud and Shippo can return different carriers and services. Three connected aggregators do not guarantee three eligible quotes. The same carrier can appear through multiple connections.

The normal quote experience lets customers choose among eligible services. Automated order processing initially proposes the lowest customer price, with stable tie-breaks. Prepared order review can expose alternatives for explicit selection.

No supported rule automatically chooses the greatest absolute platform margin. Such a strategy needs a separate product decision covering quality, customer choice, disclosure and booking consent.

## What clients see

Normal client responses show carrier/service names, customer totals and an opaque booking offer reference. Internal aggregator identity, upstream rate IDs, connection IDs and execution details are removed from the standard public projection.

This protects routing details without hiding the amount payable. Supplier-issued documents and external tracking sites can still contain their own branding. See [Tracking and delivery history](/help/features/labels-and-tracking).

## Weekends, holidays and service history

Pricing rules have validity dates, but the product has no general recurring holiday/weekend pricing calendar.

Recorded on-time comparisons exclude weekends when comparing delivery with a saved business-day estimate. They do not adjust for public holidays or country-specific calendars. Average transit uses elapsed calendar days, including weekends. These are different measurements.

History explains recorded outcomes; it does not automatically override every customer's service choice. [Read how delivery history is measured](/help/features/labels-and-tracking#how-delivery-history-is-measured).

## Ask for a pricing review

Clients should provide the quote or booking reference, route, displayed amount and currency. Administrators should also identify the applicable rule and boundary values. Never send carrier credentials with a pricing request.

[Contact EasyInvio support](/help/contact) or [return to the Help Centre](/help).
