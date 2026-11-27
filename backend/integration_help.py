"""Authored merchant quickstart and executable, server-side signing examples."""
from __future__ import annotations

from html import escape
import json

ORDER = {"id": "WEB-1042", "name": "#1042", "currency": "GBP", "shipping_address": {"name": "Demo Recipient", "address1": "1 Example Street", "city": "Leeds", "zip": "LS12 6EJ", "country_code": "GB"}, "line_items": [{"title": "Cotton shirt", "quantity": 2, "grams": "200", "unit_value": "12.00", "origin_country": "GB"}]}
RATE = {"weight_kg": "2.000", "length_cm": "25", "width_cm": "20", "height_cm": "15", "currency": "GBP", "destination": {"name": "Demo Recipient", "line1": "1 Example Street", "city": "Leeds", "postal_code": "LS12 6EJ", "country_code": "GB"}}


def request_examples(path: str) -> dict[str, str]:
    python = '''import hashlib, hmac, json, os, time, urllib.request

# Set these in your server's private environment; never browser JavaScript.
origin = os.environ["EASYINVIO_ORIGIN"].rstrip("/")
store = os.environ["EASYINVIO_STORE_ID"]
key = os.environ["EASYINVIO_KEY_ID"]
secret = os.environ["EASYINVIO_SIGNING_SECRET"]
path = "PATH"
with open("payload.json", encoding="utf-8") as source:
    raw = json.dumps(json.load(source), separators=(",", ":"), ensure_ascii=False).encode()
stamp = str(int(time.time()))
canonical = ".".join((stamp, "POST", path, store, hashlib.sha256(raw).hexdigest()))
signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
request = urllib.request.Request(origin + path, data=raw, method="POST", headers={
    "Content-Type": "application/json", "X-EasyInvio-Store-Id": store,
    "X-EasyInvio-Key-Id": key, "X-EasyInvio-Timestamp": stamp,
    "X-EasyInvio-Signature": signature})
with urllib.request.urlopen(request, timeout=20) as response:
    print(response.status, response.read().decode())
'''.replace('"PATH"', '"' + path + '"')
    node = '''// Node.js 20+, saved as send.mjs. Run only on your server.
import {createHash, createHmac} from 'node:crypto';
import {readFile} from 'node:fs/promises';
const required = name => { if (!process.env[name]) throw Error(name + ' is required'); return process.env[name]; };
const origin = required('EASYINVIO_ORIGIN').replace(/\\/$/, '');
const store = required('EASYINVIO_STORE_ID');
const key = required('EASYINVIO_KEY_ID');
const secret = required('EASYINVIO_SIGNING_SECRET');
const path = 'PATH';
const raw = Buffer.from(JSON.stringify(JSON.parse(await readFile('payload.json', 'utf8'))));
const stamp = String(Math.floor(Date.now()/1000));
const canonical = [stamp, 'POST', path, store, createHash('sha256').update(raw).digest('hex')].join('.');
const signature = createHmac('sha256', secret).update(canonical).digest('hex');
const response = await fetch(origin + path, {method: 'POST', body: raw, redirect: 'error',
  signal: AbortSignal.timeout(20000), headers: {'Content-Type': 'application/json',
  'X-EasyInvio-Store-Id': store, 'X-EasyInvio-Key-Id': key,
  'X-EasyInvio-Timestamp': stamp, 'X-EasyInvio-Signature': signature}});
console.log(response.status, await response.text());
'''.replace("'PATH'", "'" + path + "'")
    curl = '''# Bash + Python 3 + cURL. Save the JSON request below as payload.json.
# Export EASYINVIO_ORIGIN, EASYINVIO_STORE_ID, EASYINVIO_KEY_ID and
# EASYINVIO_SIGNING_SECRET through your server's private configuration.
set -eu
: "${EASYINVIO_ORIGIN:?}" "${EASYINVIO_STORE_ID:?}" "${EASYINVIO_KEY_ID:?}" "${EASYINVIO_SIGNING_SECRET:?}"
export EASYINVIO_API_PATH='PATH'
stamp=$(python3 -c 'import time; print(int(time.time()))')
export EASYINVIO_TIMESTAMP="$stamp"
signature=$(python3 - <<'PY'
import hashlib, hmac, os
raw = open("payload.json", "rb").read()
parts = [os.environ["EASYINVIO_TIMESTAMP"], "POST", os.environ["EASYINVIO_API_PATH"],
         os.environ["EASYINVIO_STORE_ID"], hashlib.sha256(raw).hexdigest()]
print(hmac.new(os.environ["EASYINVIO_SIGNING_SECRET"].encode(), ".".join(parts).encode(), hashlib.sha256).hexdigest())
PY
)
curl --fail-with-body --max-time 20 -X POST "${EASYINVIO_ORIGIN%/}${EASYINVIO_API_PATH}" \\
  -H 'Content-Type: application/json' \\
  -H "X-EasyInvio-Store-Id: $EASYINVIO_STORE_ID" \\
  -H "X-EasyInvio-Key-Id: $EASYINVIO_KEY_ID" \\
  -H "X-EasyInvio-Timestamp: $stamp" \\
  -H "X-EasyInvio-Signature: $signature" --data-binary @payload.json
'''.replace("'PATH'", "'" + path + "'")
    return {'cURL': curl, 'Python': python, 'Node.js': node}


def callback_examples() -> dict[str, str]:
    return {
        'Python': '''# Call in your HTTPS handler BEFORE JSON middleware; read original body bytes.
import hashlib, hmac, json, os, time
def verify_callback(raw: bytes, headers, path: str):
    store = os.environ["EASYINVIO_STORE_ID"]
    if headers.get("X-EasyInvio-Store-Id") != store or headers.get("X-EasyInvio-Key-Id") != os.environ["EASYINVIO_KEY_ID"]:
        raise ValueError("Unrecognized store/key")
    stamp = headers.get("X-EasyInvio-Timestamp", "")
    if not stamp.isascii() or not stamp.isdigit() or len(stamp) > 12 or abs(time.time()-int(stamp)) > 300:
        raise ValueError("Expired signature")
    canonical = ".".join((stamp, "POST", path, store, hashlib.sha256(raw).hexdigest()))
    expected = hmac.new(os.environ["EASYINVIO_SIGNING_SECRET"].encode(), canonical.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(headers.get("X-EasyInvio-Signature", ""), expected):
        raise ValueError("Invalid signature")
    return json.loads(raw)
# Durably deduplicate by event_id and enqueue processing before returning 200.
# Return 401 on verification failure. Never log secrets or raw customer bodies.
''',
        'Node.js': '''import {createHash, createHmac, timingSafeEqual} from 'node:crypto';
export function verifyCallback(raw, headers, path) {
  const store = process.env.EASYINVIO_STORE_ID;
  const key = process.env.EASYINVIO_KEY_ID;
  const secret = process.env.EASYINVIO_SIGNING_SECRET;
  if (!store || !key || !secret) throw Error('Missing server credentials');
  if (headers.get('X-EasyInvio-Store-Id') !== store || headers.get('X-EasyInvio-Key-Id') !== key) throw Error('Unrecognized store/key');
  const stamp = headers.get('X-EasyInvio-Timestamp') || '';
  const signature = headers.get('X-EasyInvio-Signature') || '';
  if (!/^\\d{1,12}$/.test(stamp) || Math.abs(Date.now()/1000-Number(stamp)) > 300 || !/^[a-f0-9]{64}$/.test(signature)) throw Error('Invalid signature');
  const canonical = [stamp, 'POST', path, store, createHash('sha256').update(raw).digest('hex')].join('.');
  const expected = createHmac('sha256', secret).update(canonical).digest();
  if (!timingSafeEqual(Buffer.from(signature, 'hex'), expected)) throw Error('Invalid signature');
  return JSON.parse(raw.toString('utf8'));
}
// Your HTTPS handler supplies raw Buffer bytes and the URL pathname, no query.
// Atomically persist/deduplicate event_id, then return 200; reject failures as 401.
''',
        'cURL': '''# Callbacks travel FROM EasyInvio TO your HTTPS receiver.
# cURL cannot implement a signature-verifying server. Use Python/Node.js tabs.
# For receiver health only, after configuring your actual callback URL:
: "${EASYINVIO_CALLBACK_URL:?Set your configured HTTPS callback URL}"
curl --max-time 10 -I "$EASYINVIO_CALLBACK_URL"
# A health response does not prove HMAC verification or event processing.
''',
    }


def code_tabs(identifier: str, examples: dict[str, str]) -> str:
    buttons, panels = [], []
    for index, (language, code) in enumerate(examples.items()):
        active = index == 0
        buttons.append(f'<button type="button" role="tab" id="{identifier}-tab-{index}" aria-controls="{identifier}-{index}" aria-selected="{str(active).lower()}" tabindex="{0 if active else -1}">{escape(language)}</button>')
        panels.append(f'<section role="tabpanel" id="{identifier}-{index}" aria-labelledby="{identifier}-tab-{index}"{ " hidden" if not active else ""}><button type="button" class="copy-code">Copy code</button><pre><code>{escape(code)}</code></pre></section>')
    return '<div class="docs-tabs"><div role="tablist" aria-label="Code language">'+''.join(buttons)+'</div>'+''.join(panels)+'</div>'


def integration_explorer() -> str:
    cards = []
    for title, path, payload, status, response in (
        ('Push an order', '/api/v1/integration/custom-store/orders', ORDER, '201 Created', 'The response includes shipment_id, status=PENDING_IMPORT, replayed, store_order_id and normalized order details. An identical retry returns replayed=true; changed shipping data requires review (409).'),
        ('Fetch checkout rates', '/api/v1/integration/custom-store/checkout-rates', RATE, '200 OK', 'The response includes currency, partial, expires_at, rates and notice. Each live rate contains carrier, service, price_ex_tax, currency and delivery_days. Prices depend on your configured accounts; an estimate never buys a label.'),
    ):
        identifier = 'orders' if payload is ORDER else 'rates'
        example = ({'shipment_id':'00000000-0000-4000-8000-000000001042','status':'PENDING_IMPORT','replayed':False,'store_order_id':'WEB-1042','order_reference':'#1042','shipping_address':ORDER['shipping_address'],'total_weight_kg':'0.4','total_quantity':2,'line_items':ORDER['line_items'],'currency':'GBP'} if payload is ORDER else {'currency':'GBP','partial':True,'expires_at':'2026-11-27T12:01:30+00:00','rates':[],'notice':'Live checkout estimate. Confirm complete shipment and customs details before buying a label.'})
        example_note = 'Example response with synthetic identifiers.' if payload is ORDER else 'Example response when providers return no offers. Successful offers contain carrier, service, price_ex_tax, currency and delivery_days; no invented carrier price is shown.'
        cards.append(f'<section class="api-card"><h3>{title}</h3><p><span class="http-badge">POST</span> <code>{path}</code></p><h4>Request · save as payload.json</h4><div class="code-request"><button type="button" class="copy-code">Copy code</button><pre><code>{escape(json.dumps(payload, indent=2))}</code></pre></div>{code_tabs(identifier, request_examples(path))}<div class="response-card"><span class="http-badge">{status}</span><p>{escape(response)}</p><p>{escape(example_note)}</p><div class="code-request"><button type="button" class="copy-code">Copy code</button><pre><code>{escape(json.dumps(example, indent=2))}</code></pre></div></div></section>')
    return '''<section class="integration-explorer"><div class="docs-tabs"><div role="tablist" aria-label="Choose your setup guide"><button type="button" role="tab" id="owners-tab" aria-controls="owners-panel" aria-selected="true">For business owners</button><button type="button" role="tab" id="developers-tab" aria-controls="developers-panel" aria-selected="false" tabindex="-1">For developers</button></div>
<section role="tabpanel" id="owners-panel" aria-labelledby="owners-tab"><h2>Connect your store, one step at a time</h2><ol class="quickstart-steps"><li><h3>Choose your connection</h3><p>Sign in as an owner or administrator. Open Store Integrations, choose your platform and register your store. Native adapters need your authorized platform credentials; other platforms connect through your developer or middleware.</p></li><li><h3>Start with the simplest route</h3><p>Use existing CSV upload to prepare orders without API work. For automatic order intake and checkout rates, hand the setup guide to your developer and transfer signing credentials through your private secret manager. There is no installed one-click Make/Zapier app or SFTP collector.</p></li><li><h3>Share your return link</h3><p>Open Public returns portal, choose a unique store address and authorize your return policy. Copy the resulting /returns/ link into your website. This needs no custom API code. Eligible single-parcel GB returns are supported; label purchase and QR availability remain subject to payment, policy and carrier support.</p></li></ol><a class="primary-button" href="/login?mode=signin">Open your workspace</a><p>Registration alone does not authorize order retrieval, activate a carrier or buy postage. Store connections require an eligible plan.</p></section>
<section role="tabpanel" id="developers-panel" aria-labelledby="developers-tab" hidden><h2>Signed store API</h2><p>Server-side only. Set EASYINVIO_ORIGIN to your selected HTTPS environment, then set EASYINVIO_STORE_ID, EASYINVIO_KEY_ID and EASYINVIO_SIGNING_SECRET from Connection settings. Never put secrets into storefront JavaScript. Use the same raw bytes for signing and sending.</p><p>These are synthetic documentation addresses, not real customer data. Save one request below as payload.json. The Python and Node.js examples send requests; checkout rates may call your configured providers.</p>''' + ''.join(cards) + '<section class="api-card"><h3>Receive tracking callbacks</h3><p>Configure an HTTPS callback on your saved retailer origin, then enable live write-back. Verify all signature headers and durably deduplicate event_id before acknowledging. Outgoing callback payloads depend on forward/return lifecycle; consult the full contract below.</p>' + code_tabs('callbacks', callback_examples()) + '''<div class="response-card"><span class="http-badge">200 OK</span> Your receiver acknowledges only verified, durably accepted events.</div></section><div class="status-grid"><p><b>401</b> Invalid signature, expired timestamp or rotated key.</p><p><b>403</b> Inactive authority or missing plan entitlement.</p><p><b>409</b> Changed order data or uncertain operation: review before retry.</p><p><b>422</b> Invalid address, measurement or payload.</p><p><b>429</b> Rate limit: 120 orders or 20 checkout calls/minute/store.</p><p><b>502 / 503</b> Provider or storage unavailable.</p></div><p>Exact checkout requests may reuse a tenant/store-bound result for up to 90 seconds. No label or payment is authorized by either endpoint.</p></section></div><p class="docs-copy-status" role="status" aria-live="polite"></p></section>'''
