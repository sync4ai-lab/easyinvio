# Find and verify pickup and delivery addresses

In Speed Quote Matrix / Create shipment, select the pickup country and delivery country. For either UK address, enter a full postcode and click **Find UK address** under that postcode. Select the exact building or flat. EasyInvio fills the street, address line 2, post town and postcode for that side only. Your contact name, phone and email remain yours to enter. The message changes to **Address matched to Royal Mail PAF**. Changing the address clears that confirmation; look it up again. A saved address is not automatically a verified address.

## What the checks mean

A UK postcode is uppercased and spaced, and its format checked on the server for all Address inputs. Formatting does not prove that a postcode exists, that the building belongs to it, or that a carrier supports it. The licensed PAF lookup returns complete Royal Mail delivery points. The server independently matches the street, address line 2 and post town against those delivery points before rating and before a new label purchase; it never trusts a browser verification flag. If a match fails, choose the complete PAF address rather than just changing the postcode. Do not guess the property or use a neighbouring postcode.

## UAT and live operation

The platform administrator configures IDEAL_POSTCODES_API_KEY in the local environment and Vercel environment using a licensed Ideal Postcodes account with PAF access and available lookup credits, then redeploys. No browser API key is exposed. Without that key, TEST can use synthetic addresses but has no PAF delivery-point verification. The lookup button displays an explicit unavailable message. LIVE UK quoting and new purchases are blocked without a lookup key, on provider failure, or when the full address does not match. Existing submitted purchases are reconciled without buying a second label. No migration is required.

WhatsApp already collects UK postcodes, displays numbered PAF premise choices and asks for the contact name. Missing lookup configuration cannot silently generate guessed UK street addresses. Its 15-minute draft expiry and message receipt rules remain unchanged.

## International addresses and carrier acceptance

UK PAF cannot verify foreign addresses. Confirm the destination country, full postal code, building or unit, street, city and any required state with the recipient. Carrier-specific quoting and booking errors must be resolved before dispatch. A valid PAF address does not guarantee delivery: service coverage, parcel dimensions, prohibited goods, customs, contact requirements and the carrier's own acceptance checks still apply. Do not describe a successful postcode format check as carrier approval.

## API and failure handling

POST /api/v1/addresses/uk/lookup accepts {"postcode":"LS1 2EJ"} for an authenticated workspace user with address access. It returns source ROYAL_MAIL_PAF and premise choices; it creates no shipment and purchases no label. Invalid syntax returns 422, unavailable configuration/service returns 503, and a nonexistent postcode returns an empty list. Keys and upstream response bodies are not included in customer errors. Address matching occurs in RatingService and both stored-offer and ordinary fulfilment paths before financial reservation.

References: https://www.royalmail.com/find-a-postcode and https://openapi.ideal-postcodes.co.uk/.
