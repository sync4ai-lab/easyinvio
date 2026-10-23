"""Public, authored customer guidance with no account access or external actions."""
from dataclasses import dataclass
from html import escape
from pathlib import Path
import re

import markdown
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse


COMPONENTS = Path(__file__).resolve().parents[1] / 'frontend' / 'components'
HEADERS = {'Cache-Control': 'no-store'}


@dataclass(frozen=True)
class Guide:
    title: str
    category: str
    summary: str
    body: str
    keywords: str
    prepared: bool = True
    source_file: str | None = None
    section_chunks: bool = False


GUIDES = {
    'account-access': Guide(
        'Sign in and find your workspace', 'Start with confidence',
        'Get into the right company workspace, accept an invitation or reset your password.',
        """<h2 id="sign-in">Open your workspace</h2>
        <ol><li>Open EasyInvio and sign in with your work email and password.</li>
        <li>If you received an invitation, use the link in that email to complete account setup. Use the email address the invitation was sent to.</li>
        <li>Check the company shown in your workspace before creating shipments or making a payment.</li></ol>
        <h2 id="access-problems">If you cannot get in</h2>
        <p>Use the password reset option on the sign-in screen. Check your spam folder if the email does not arrive. An expired invitation can be resent by your workspace owner or administrator.</p>
        <p>If you can sign in but have no workspace access, ask your company administrator to check your membership. A new sign-in does not automatically create a shipping account or connect carrier contracts.</p>
        <h2 id="test-mode">Check whether you are practising</h2>
        <p>Example prices and demonstration records are not live bookings. A TEST label, when supported by the connection, is for practice and must not be used to send a real parcel. Ask EasyInvio support to confirm live readiness before dispatching goods.</p>
        <p><a href="/help/team-and-security">Learn about team access</a> or <a href="/help/contact">contact support for account help</a>.</p>""",
        'login log in sign in password reset invitation invite activation workspace sandbox test account'),
    'team-and-security': Guide(
        'Invite your team and protect access', 'Start with confidence',
        'Give colleagues the access they need without sharing passwords or carrier keys.',
        """<h2 id="invite">Add a colleague</h2>
        <ol><li>Ask your workspace owner or administrator to open Workspace Settings.</li>
        <li>Enter the colleague's name and work email, then select Dispatcher or Accountant.</li>
        <li>Send the invitation. The colleague completes setup through their email link.</li></ol>
        <p>A Dispatcher prepares and books shipments. An Accountant uses the financial tools. Workspace owners and administrators manage company settings and team access. If a menu is missing, check your role with your administrator.</p>
        <h2 id="manage">When access changes</h2>
        <p>Your administrator can update supported team roles, disable a member, resend an invitation or send a password reset link from Workspace Settings. Cancelling an invitation stops that invitation from being used.</p>
        <h2 id="security">Keep credentials private</h2>
        <p>Use your own account and a strong password. Do not send passwords, carrier credentials, access tokens or card details to support. Carrier connection credentials are managed through authorised platform administration; ordinary shipment users do not need to set up personal developer keys.</p>
        <p><a href="/help/contact">Ask for help with team permissions</a>.</p>""",
        'roles permissions dispatcher accountant owner admin security keys invite colleagues team'),
    'first-shipment': Guide(
        'Compare prices and create a label', 'Start with confidence',
        'Prepare accurate shipment details, compare eligible services and confirm a booking.',
        """<h2 id="prepare">Measure before you quote</h2>
        <ol><li>Open Speed Quote Matrix and enter the pickup and delivery addresses. Check the country, postcode and contact details.</li>
        <li>Choose the cargo classification. Open Packaging sizes for guidance, then enter the actual packed measurements and gross weight.</li>
        <li>For goods, enter the description, quantity, value per item, net weight per item and country of manufacture. Total goods weight must fit within the packed weight.</li>
        <li>Request prices, then compare the available services and their final displayed prices.</li></ol>
        <p>Packaging examples are shortcuts, not a guarantee that every carrier accepts that size. Freight needs an enabled freight contract. Do not reduce the measured size or weight just to obtain a cheaper quote.</p>
        <h2 id="compare">Choose an option</h2>
        <p>Open the price breakdown before choosing. Available rates depend on the route, package and connected accounts. A missing service is not proof that the carrier can never serve that route.</p>
        <p>Delivery estimates appear when provided. On-time and transit history use measured delivery records in your workspace. When there is not enough verified history, those values stay unavailable rather than showing an invented rating.</p>
        <h2 id="booking">Confirm and create the label</h2>
        <ol><li>Select a service. For an international goods shipment, review the customs description and HS code before continuing.</li>
        <li>Review the final price. If goods quantities, values, weights or origins need changing, close checkout, update the shipment and request a fresh quote.</li>
        <li>Choose wallet payment or the available Stripe card checkout. Wait for a confirmed booking.</li>
        <li>Open Manifest &amp; Labels to download the carrier label. Check the tracking number and label before handing the parcel to the carrier.</li></ol>
        <h2 id="label-problem">No printable label yet?</h2>
        <p>An imported order or a quote is not a booked label. A pending or review message means confirmation is still outstanding. Do not repeatedly buy the same shipment while its outcome is unclear. Give support the booking reference and the message shown.</p>
        <p><a href="/help/booking-payments">Understand booking payments</a> or <a href="/help/contact">get help with a label</a>.</p>""",
        'shipping shipment quotes rates carriers booking book purchase label print missing label dimensions customs history'),
    'wallet-top-ups': Guide(
        'Add credit and check a card payment', 'Understand your money',
        'Top up through Stripe and find out what to do when the balance has not changed.',
        """<h2 id="top-up">Add wallet credit</h2>
        <ol><li>Open Wallet &amp; Billing. Your role must allow financial access.</li>
        <li>Choose Top Up Wallet Credit, select an amount and proceed to secure payment.</li>
        <li>Enter card details on Stripe's checkout page. Return to EasyInvio after payment.</li>
        <li>Check the wallet balance and transaction activity for the verified credit.</li></ol>
        <p>Wallet credit appears only after the payment is confirmed by the payment provider. Opening checkout, closing the payment window or returning to the app does not by itself confirm payment.</p>
        <h2 id="payment-pending">I paid, but the balance is unchanged</h2>
        <ol><li>Return to the same workspace and allow the payment status to update. If asked to sign in, use the same work account.</li>
        <li>Check wallet activity for the amount before starting another top-up.</li>
        <li>If Stripe reports success but EasyInvio still shows pending, contact support with the amount, time and payment reference. Do not pay again just to refresh the balance.</li></ol>
        <p>Support can check the payment confirmation and ensure a successful payment is credited once. Do not send your full card number or card security code.</p>
        <p><a href="/help/contact">Get help with a payment</a>.</p>""",
        'wallet credit balance top up topup stripe card payment paid pending missing money not showing checkout'),
    'booking-payments': Guide(
        'Pay for labels and read wallet activity', 'Understand your money',
        'Understand available credit, temporary holds, confirmed charges and failed bookings.',
        """<h2 id="wallet-charge">When is my wallet charged?</h2>
        <p>Your wallet is charged only after the shipping service confirms the label purchase. When you confirm a booking, EasyInvio first reserves the amount: this lowers your available credit but is not yet a completed charge.</p>
        <p>If the purchase is definitely rejected, the reservation is released. If the outcome is still unclear, the amount remains reserved while support checks the booking. For a multi-box booking, all package labels must be confirmed before the booking cost is deducted.</p>
        <h2 id="payment-options">Two ways to pay</h2>
        <p>Use existing wallet credit when you confirm a prepared shipment, or choose the available Stripe card checkout for that booking or selected basket. Review the total before paying.</p>
        <p>Card checkout first confirms the payment and then attempts the selected bookings. Each label must still be confirmed by the shipping service.</p>
        <h2 id="wallet-activity">What the wallet entries mean</h2>
        <ul><li><strong>Credit added:</strong> a payment has been verified and added to your wallet.</li>
        <li><strong>Credit reserved:</strong> an amount is held for a booking. It reduces available credit while the outcome is checked.</li>
        <li><strong>Label purchased:</strong> the confirmed label cost is deducted from the wallet.</li>
        <li><strong>Reservation released:</strong> an unused hold has been removed. This is not a second credit or a refund to your bank card.</li></ul>
        <h2 id="failed-booking">If the label is rejected or still pending</h2>
        <p>A definite purchase rejection releases the booking hold without charging for a confirmed label. A booking with an unclear outcome stays in review so that the same label is not bought again accidentally.</p>
        <p>If a card payment succeeded but the label was rejected, the verified funds remain in your wallet for a fresh eligible booking. A failed label purchase does not automatically refund that card payment to your bank.</p>
        <p>For a multi-box booking, all package labels must be confirmed before the booking cost is captured. Keep the booking reference and contact support if any package is still pending.</p>
        <p><a href="/help/wallet-top-ups">Check a top-up</a> or <a href="/help/review-a-charge">ask about a charge</a>.</p>""",
        'reserved reserve release deducted charged capture ledger transactions history failed rejection declined refund card basket'),
    'prices-and-currencies': Guide(
        'Prices, currencies and extra charges', 'Understand your money',
        'Read the quote breakdown and keep shipping charges separate from goods value and import costs.',
        """<h2 id="price">Read the total before paying</h2>
        <p>Each eligible service shows its customer price and a breakdown. A fuel surcharge may already be included in the label cost. Shipment protection is not included unless the booking explicitly offers it and you accept its price and terms.</p>
        <p>A quote can change after the carrier checks customs details. Review the final prepared price before you confirm. An expired quote needs fresh rates.</p>
        <h2 id="tax">Taxes and destination charges</h2>
        <p>The shipping subtotal is shown excluding tax. The current shipping checkout does not assess or collect shipping VAT. Applicable carrier taxes, import duties and destination charges may be billed separately.</p>
        <p>If shipment protection is available for your booking, its premium and applicable protection tax are shown separately. Coverage is confirmed only after the policy is confirmed. Do not assume that goods are insured just because a label exists.</p>
        <h2 id="currencies">Check the currency</h2>
        <p>Carrier rates and goods values can use different currencies. Check the currency beside each amount. A booking must meet the wallet and payment currency requirements; EasyInvio does not automatically convert an unsupported rate into wallet currency.</p>
        <p>If no compatible rates are offered, request an available quote currency or ask support to check the connected service. Do not change the goods' actual value or currency just to make a quote pass.</p>
        <h2 id="invoice">Keep the reference</h2>
        <p>A new checkout receives an EINVIO invoice reference. The same reference follows that transaction into its receipt and, when required, its commercial invoice. Reopening the same checkout does not issue a new reference.</p>
        <p><a href="/help/review-a-charge">Review a carrier charge</a>.</p>""",
        'tax vat duties surcharge fuel insurance protection currency currencies conversion exchange invoice receipt reference prices fees'),
    'review-a-charge': Guide(
        'Question about a charge?', 'Understand your money',
        'Find the right reference and ask for a review of a payment or carrier invoice.',
        """<h2 id="identify">Identify the charge</h2>
        <p>Check whether your question is about wallet credit, a label purchase, a bank-card payment or a later carrier invoice. Keep the booking or invoice reference, amount and currency.</p>
        <h2 id="carrier-invoice">Review a later carrier charge</h2>
        <p>Keep the statement and identify the shipment reference on the affected line. Tell support what looks wrong, such as a different billed weight, an unexpected address surcharge or a higher shipping cost.</p>
        <p>Where your financial role has access to the invoice review tools, comparisons can produce a draft review request. A flagged difference is a reason to investigate; it is not a guaranteed refund. Review the evidence before any dispute is submitted.</p>
        <h2 id="lost-damaged">Lost or damaged goods</h2>
        <p>A carrier billing question is different from a loss or damage claim. Keep the tracking number, proof of value and any photographs. Protection claims require confirmed coverage; contact support to check the available claim route and terms.</p>
        <p><a class="button-link" href="/help/contact">Ask support to review a charge</a></p>""",
        'dispute complaint charge surcharge statement invoice refund international lost damaged claim'),
    'package-weight': Guide(
        'Why size affects the price', 'Start with confidence',
        'Understand packed weight and space-based weight before requesting a quote.',
        """<h2 id="measure">Start with the packed parcel</h2>
        <p>Measure the outside of the closed package in centimetres and weigh it in kilograms. Include the box and packing material. Packaging sizes provides useful examples; your actual package measurements still need checking.</p>
        <h2 id="space-weight">Large, light boxes can cost more</h2>
        <p>A carrier may charge for the space a parcel occupies when that is greater than its actual weight. EasyInvio's standard-parcel guidance multiplies length by width by height and divides by 5,000.</p>
        <p>For example, a 40 by 30 by 20 cm box has a space-based weight of 4.8 kg. If it weighs 2 kg on the scales, the guidance uses 4.8 kg as its billable weight. The selected carrier's service rules and rounding determine its actual quoted price.</p>
        <p>Each box is calculated separately for a multi-box shipment. Adding all actual weights first and comparing them with all space-based weights can give the wrong result.</p>
        <h2 id="no-rates">If the package has no eligible service</h2>
        <p>Check that you chose the correct cargo type and entered the packed measurements correctly. Carrier size and weight limits depend on the route and account. A pallet or road-freight shipment needs the right freight connection; changing its category does not create a freight contract.</p>
        <p>If the goods can safely use smaller packaging, repack and measure again. Otherwise ask support for a suitable service. Do not enter smaller numbers than the actual parcel.</p>
        <p><a href="/help/first-shipment">Return to the first-shipment guide</a>.</p>""",
        'volumetric dimensional dimensions girth length width height weight multiplier 5000 packing packaging box profile limits no rates oversized'),
    'connect-shopify': Guide(
        'Connect Shopify and find your orders', 'Start with confidence',
        'Understand store registration, authorised access and order retrieval.',
        """<h2 id="before">Before you start</h2>
        <p>You need a Shopify store administrator to authorise order access. Setup depends on the store and app permissions; there is no guaranteed three-minute installation. Contact EasyInvio support if you need help arranging access.</p>
        <h2 id="connect">Register and connect the store</h2>
        <ol><li>Open Store Integrations, choose Shopify and register the store with a recognisable name.</li>
        <li>Open its Connection settings and enter the store's official myshopify.com address.</li>
        <li>Use the supported authorised connection method shown in the form. Only enter credentials in the app's connection settings; do not send them by email.</li>
        <li>Provide verified product weights where required, then save the connection.</li></ol>
        <p>Registering a store creates its place in your workspace. Saving its name alone does not give EasyInvio permission to retrieve orders.</p>
        <h2 id="orders">Retrieve and prepare orders</h2>
        <ol><li>Choose Retrieve orders on the connected Shopify store, or Sync Marketplace Orders in Marketplace Workspace.</li>
        <li>Review the imported unfulfilled orders in Marketplace Workspace.</li>
        <li>Measure the packed goods, check customs details if required, compare rates and explicitly choose the booking you want.</li></ol>
        <p>Imported orders do not automatically purchase labels. Store fulfilment write-back needs the appropriate authorised connection. Return tracking uses an approved return case and remains separate from the original order's fulfilment.</p>
        <h2 id="no-orders">If orders do not appear</h2>
        <p>Check that the store and connection are enabled, the permission is still valid and the order is eligible for import. Missing verified product weights or a permission problem can require review. Include the store name and an affected order reference when asking for help.</p>
        <p>Store administrators can read <a href="https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens" target="_blank" rel="noopener noreferrer">Shopify's official access guidance</a>. For other platforms, use the How to connect guidance in Store Integrations; some catalogue entries need assisted setup rather than an active order importer.</p>""",
        'shopify store ecommerce e commerce integration connect connection sync retrieve import orders webhook webhooks'),
    'settings-catalogs': Guide(
        'Reuse saved addresses, contacts and products', 'Explore your shipping tools',
        'Prepare shipments faster with your workspace address book and SKU catalog.',
        """<h2 id="save">Save your shipping details</h2>
        <p>Open Settings and choose Addresses, Saved Contacts or Products. Owners, administrators and dispatchers can save and edit records. Accountants can view the catalogs. Company and team administration remains restricted to owners and administrators.</p>
        <p>Use separate sender, return, pickup and invoice address roles. Each role can have one default location. A default is a saved preference; it does not schedule a collection or change a booking.</p>
        <h2 id="reuse">Choose a record in Create a shipment</h2>
        <p>Use Saved addresses beside Pickup name for your sender or pickup location. Use Saved contacts beside Delivery name for a recipient. Check the selected address before requesting rates.</p>
        <p>Enter an exact saved SKU to fill the goods description, net unit weight, value, country of manufacture and saved HS code. Search results also let you choose a product. Use Add another goods item for additional products, all using the same goods currency.</p>
        <h2 id="review">Review measurements and customs</h2>
        <p>Product weight is the weight of one item, not the packed box. Measure your packaging and enter the actual packed weight separately. Catalog values are not automatically converted between currencies.</p>
        <p>A reviewed catalog code is a reusable starting point. The shipper must still check destination requirements and approve each customs declaration. Changing a description or manufacture country clears the prefilled code for review.</p>
        <h2 id="changes">Edit or archive a record</h2>
        <p>Edits apply to future selections. Existing shipment snapshots keep their original details. Archive hides a record from future choices. If someone else updated a record, refresh it before saving your changes.</p>""",
        'settings catalogs warehouse addresses contacts recipients sku products default saved autofill'),
    'features/bulk-dispatch': Guide(
        'Prepare and book several orders', 'Shipping tools',
        'A forthcoming guide to bulk uploads, marketplace preparation and selected-label checkout.',
        '<p>This detailed guide is being prepared. Bulk upload and Marketplace Workspace are existing tools; an imported row is not a purchased label.</p><p>For help today, read <a href="/help/booking-payments">Pay for labels and read wallet activity</a> or <a href="/help/contact">ask support about preparing several orders</a>.</p>',
        'features bulk csv upload batch warehouse multiple multi boxes parcels matrices', False),

}


# These repository-authored sources are maintained once and rendered on their pages.
GUIDES.update({
    'connect-stores': Guide(
        'Choose and connect a sales channel', 'Connect your stores',
        'Supported store import methods and platforms that still need an adapter.',
        '''<h2 id="choose">Choose your platform before connecting</h2><p>EasyInvio currently implements Shopify order notifications/retrieval, WooCommerce signed order webhooks, and Amazon authorised seller order lookup triggered by AWS notifications. A workspace owner or admin manages connections in Store Integrations; dispatchers use the imported orders in Marketplace Workspace.</p>
        <p>eBay, BigCommerce and PrestaShop are catalogue entries for assisted setup. Their order adapters and authorisation onboarding still need implementation; entering credentials does not activate imports. Etsy, Magento, Wix and TikTok are not implemented native order importers in this application.</p>
        <ol><li>Tell us which store platform you use.</li><li>For Shopify, WooCommerce or Amazon, follow that platform's connection guide and save credentials only in its secure connection settings.</li><li>Verify an imported order in Marketplace Workspace, review shipment details and explicitly choose/book a carrier. Store connection never purchases labels automatically.</li></ol>
        <p>For an unsupported platform, use an available manual shipment or CSV preparation workflow while discussing an adapter with support. Do not use Shopify setup instructions for a different platform.</p>''',
        'stores storefront platform connect integration amazon shopify woocommerce ebay bigcommerce prestashop etsy magento wix tiktok'),
    'connect-woocommerce': Guide(
        'Connect WooCommerce with signed order webhooks', 'Connect your stores',
        'Register the store, save a signing secret and verified weights, then configure order webhooks.',
        '''<h2 id="setup">Set up WooCommerce order imports</h2>
        <ol><li>Sign in as a workspace owner or admin. Open Store Integrations, choose WooCommerce and register the store.</li>
        <li>Open Connection settings. Save a strong webhook signing secret of at least 32 characters and verified SKU weights in grams, for example MUG-BLUE = 350.</li>
        <li>In your WooCommerce administration, open Settings, Advanced, Webhooks. Configure an Order created webhook and, if needed, Order updated. Use your public EasyInvio origin plus /api/v1/integration/webhooks/ and this registered store's UUID as the delivery URL.</li>
        <li>Use the same signing secret in WooCommerce and EasyInvio. EasyInvio verifies the x-wc-webhook-signature and supported order.created/order.updated topic before importing.</li>
        <li>Send an eligible order notification. Open Marketplace Workspace to review the imported address, goods, packing and customs, then compare rates and explicitly book. Import does not buy a label or charge a wallet.</li></ol>
        <h2 id="troubleshoot">If an order is missing</h2><p>Check webhook delivery logs, the exact store UUID, signing secret, recipient address, prices and verified SKU weights. Keep the original reference when investigating repeated events. The Shopify Retrieve orders button is not WooCommerce polling; this connector uses signed notifications.</p>''',
        'woocommerce wordpress connect integration setup webhook orders weights'),
    'connect-amazon': Guide(
        'Connect Amazon Marketplace and import orders', 'Connect your stores',
        'Seller authorisation, connection settings, SKU weights, AWS notifications and import troubleshooting.',
        '', 'amazon marketplace sp api seller integration connect setup sqs aws eventbridge order_change',
        source_file='docs_amazon_integration.md', section_chunks=True),
    'status-guide': Guide(
        'Understand statuses and resolve unexpected results', 'Shipping tools',
        'A complete status reference with practical next steps for orders, quotes, tracking, payments, refunds, returns, claims and account access.',
        '', 'status statuses meaning unexpected unwanted stuck failed pending imported unquoted draft quote expired booked manifested tracking delivered exception wallet refund return claim insured support registration invitation sync',
        source_file='docs/status_reference.md', section_chunks=True),
    'features/order-processing': Guide(
        'Import and prepare store orders', 'Shipping tools',
        'Shopify and Amazon intake, validation recovery and the limits of order defaults.',
        '', 'orders shopify amazon inbound ingestion webhook sync defaults validation postal city sku',
        source_file='docs_order_processing.md'),
    'features/pricing': Guide(
        'Understand pricing rules and carrier choices', 'Shipping tools',
        'An administrator guide to rule priorities, margins and customer service choices.',
        '', 'rules routing priority margins markup profit weekend holiday pricing admin',
        source_file='docs_routing_rules.md'),
    'features/labels-and-tracking': Guide(
        'Follow tracking updates and understand delivery history', 'Shipping tools',
        'Accepted carrier events, measured 90-day history and current branding limits.',
        '', 'tracking branding webhooks history transit on time scores weekend holidays photo signature',
        source_file='docs_tracking_branding.md'),
    'features/returns': Guide(
        'Prepare a return without changing the original sale', 'Shipping tools',
        'Supported reverse preparation, Shopify return references and reviewed customs documents.',
        '', 'return reverse logistics shopify amazon customs cn22 cn23 brexit inspection',
        source_file='docs_returns_lifecycle.md'),
    'features/carrier-pickups': Guide(
        'Get shipments ready for an externally arranged collection', 'Shipping tools',
        'Prepare confirmed parcels while arranging pickup outside EasyInvio; scheduling is not yet built.',
        '', 'pickup pickups courier collection schedule scheduling manifest closeout driver capacity',
        source_file='docs_carrier_pickups.md'),
})


def guide_source(guide):
    # No client-supplied filename or uploaded Markdown is accepted here.
    if not guide.source_file:
        raise HTTPException(404, 'A Markdown source is not available for this guide')
    path = Path(__file__).resolve().parents[1] / guide.source_file
    if not path.is_file():
        raise HTTPException(503, 'This guide is temporarily unavailable')
    return path


def rendered_guide(guide):
    source = guide_source(guide).read_text(encoding='utf-8')
    lines = source.splitlines()
    if not lines or lines[0] != '# ' + guide.title:
        raise ValueError('Guide title must match its published catalogue entry')
    converter = markdown.Markdown(extensions=['toc', 'sane_lists'],
        extension_configs={'toc': {'toc_depth': 2 if guide.section_chunks else 6}}, output_format='html')
    body = converter.convert('\n'.join(lines[1:]))
    return body, converter.toc


CONTACT_BODY = """<p class="article-intro">Tell us what you expected and what happened. We can help with account access, payments, store connections and shipments.</p>
<p class="contact-address"><a href="mailto:support@easyinvio.com">support@easyinvio.com</a></p>
<form id="help-contact-form">
  <label class="form-field"><span>What do you need help with?</span><select name="topic" required>
    <option>Account or team access</option><option>Quotes or package sizes</option><option>Label or booking</option>
    <option>Wallet or card payment</option><option>Invoice or charge review</option><option>Store connection or orders</option>
    <option>Tracking, return or protection claim</option><option>Something else</option>
  </select></label>
  <label class="form-field"><span>Booking, order or payment reference (optional)</span><input name="reference" maxlength="100" autocomplete="off"></label>
  <label class="form-field"><span>What happened?</span><textarea name="message" rows="7" minlength="10" maxlength="1800" required placeholder="Describe the problem, the step you tried and the message shown."></textarea></label>
  <p>Do not include passwords, API keys, full card details or customer addresses. You can attach a suitably redacted screenshot in your email app.</p>
  <button class="primary-button" type="submit">Prepare email draft</button>
  <p id="help-contact-status" role="status" aria-live="polite">This opens your email app. Review and send the email there. No support request is sent automatically.</p>
</form>
<noscript><p>Email support@easyinvio.com directly and include the topic and reference.</p></noscript>"""


def render_page(title, category, summary, body, *, prepared=True, contents="", source_url=None):
    status = '' if prepared else '<div class="notice"><strong>Guide being prepared</strong><br>This guide is not ready yet. Use the links below for help with the existing tool.</div>'
    navigation = '<nav class="guide-contents" aria-label="In this guide"><h2>In this guide</h2>'+contents+'</nav>' if contents else ''
    download = '<p><a href="'+escape(source_url, quote=True)+'">Download this guide as Markdown</a></p>' if source_url else ''
    related = '\n'.join(f'<a href="/help/{escape(slug, quote=True)}">{escape(guide.title)}</a>'
                        for slug, guide in GUIDES.items() if guide.category == category and guide.title != title)
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>{escape(title)} | EasyInvio Help Centre</title>
  <meta name="description" content="{escape(summary, quote=True)}">
  <link rel="stylesheet" href="/help/assets/support.css">
  <script src="/help/assets/support.js" defer></script>
</head>
<body class="bg-slate-900">
  <a class="skip-link" href="#help-main">Skip to guide</a>
  <header class="help-header bg-slate-950 border-slate-800">
    <div class="header-inner">
      <a class="brand" href="/help">EasyInvio<em>.com</em><small>Help Centre</small></a>
      <nav class="header-actions" aria-label="Help navigation"><a href="/help/contact">Contact support</a><a href="/">Back to EasyInvio</a></nav>
    </div>
  </header>
  <main class="help-shell" id="help-main">
    <nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/help">Help Centre</a><span aria-hidden="true">/</span><span>{escape(category)}</span></nav>
    <div class="article-layout">
      <article class="help-article bg-slate-950 border border-slate-800">
        <span class="eyebrow">{escape(category)}</span>
        <h1>{escape(title)}</h1>
        <p class="article-intro">{escape(summary)}</p>
        {status}
        {navigation}
        {body}
        {download}
      </article>
      <aside class="article-sidebar" aria-label="More help">
        <h2>Keep going</h2>
        {related}
        <a href="/help">Browse all help topics</a>
        <a href="/help/contact">Contact EasyInvio support</a>
      </aside>
    </div>
  </main>
  <footer class="help-footer"><span>EasyInvio.com Help Centre</span><a href="/">Return to your workspace</a></footer>
</body>
</html>'''


router = APIRouter(tags=['Help Centre'])


@router.get('/help', include_in_schema=False)
@router.get('/help/', include_in_schema=False)
async def support_hub():
    return FileResponse(COMPONENTS / 'SupportHub.html', media_type='text/html', headers=HEADERS)


@router.get('/help/assets/{asset}', include_in_schema=False)
async def support_asset(asset: str):
    media = {'support.css': 'text/css', 'support.js': 'application/javascript'}
    if asset not in media:
        raise HTTPException(404, 'Help asset not found')
    return FileResponse(COMPONENTS / asset, media_type=media[asset], headers=HEADERS)


@router.get('/help/search-index.json', include_in_schema=False)
async def support_search_index():
    def keywords(guide):
        if guide.section_chunks:
            headings = re.findall(r'^### (.+)$', guide_source(guide).read_text(encoding='utf-8'), re.MULTILINE)
            return guide.keywords + ' ' + ' '.join(headings)
        return guide.keywords
    return {'guides': [{'title': guide.title, 'category': guide.category, 'summary': guide.summary,
                        'keywords': keywords(guide), 'prepared': guide.prepared, 'url': '/help/' + slug}
                       for slug, guide in GUIDES.items()]}


@router.get('/help/contact', response_class=HTMLResponse, include_in_schema=False)
async def support_contact():
    return HTMLResponse(render_page('Contact EasyInvio support', 'Support',
                                    'Open an email draft for the EasyInvio support team.', CONTACT_BODY), headers=HEADERS)


@router.get('/help/source/{slug:path}', include_in_schema=False)
async def support_source(slug: str):
    guide = GUIDES.get(slug)
    if guide is None:
        raise HTTPException(404, 'Guide source not found')
    path = guide_source(guide)
    return FileResponse(path, media_type='text/markdown', filename=path.name, headers=HEADERS)


@router.get('/help/{slug:path}', response_class=HTMLResponse, include_in_schema=False)
async def support_guide(slug: str):
    guide = GUIDES.get(slug)
    if guide is None:
        return HTMLResponse(render_page('We could not find that guide', 'Help Centre',
            'The link may have changed. Browse help topics or contact EasyInvio support.',
            '<p><a class="button-link" href="/help">Browse the Help Centre</a></p>'), status_code=404, headers=HEADERS)
    if guide.source_file:
        try:
            body, contents = rendered_guide(guide)
        except (OSError, ValueError):
            raise HTTPException(503, 'This guide is temporarily unavailable') from None
        return HTMLResponse(render_page(guide.title, guide.category, guide.summary, body,
            contents=contents, source_url='/help/source/' + slug), headers=HEADERS)
    return HTMLResponse(render_page(guide.title, guide.category, guide.summary, guide.body,
                                    prepared=guide.prepared), headers=HEADERS)
