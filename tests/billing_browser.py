"""Synthetic browser QA of billing presentation; no real sessions or providers."""
import asyncio,json,os,time,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from playwright.async_api import async_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.entitlements import Plan,capabilities
from backend.subscription_lifecycle import document
from backend.subscription_math import cycle_price
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'.playwright'))

async def main():
    out=ROOT/'output/subscription-qa';out.mkdir(parents=True,exist_ok=True)
    errors=[];requests=[];commands=[];gate=asyncio.Event();gate.set();can_manage=True;enabled=False;statement_failure=False;review_failure=False;current_plan='VELOCITY';unbounded=False;ignore_dates=False;prices_ready=True
    registered='2026-07-15T10:00:00Z';card_flow=False;invoice_pending=False;wallet_available='83.00';wallet_failure=False
    plans=document([{'plan':p.value,'annual_fee_gbp':cycle_price(p,'ANNUAL'),**capabilities(p).model_dump()} for p in Plan])
    snapshot={'id':'00000000-0000-4000-8000-000000000003','statement_number':'EI-DEMO','period_start':'2026-10-01','period_end':'2026-11-01','currency':'GBP','opening_balance':'100.00','closing_balance':'88.00','total_topups':'0.00','subscription_net':'0.00','shipping_net':'10.00','refunds_net':'0.00','tax_total':'2.00','gross_total':'12.00','tax_complete':True,'transactions':[{'occurred_at':'2026-10-15T12:00:00Z','type':'SHIPPING','reference':'<script>bad()</script>','carrier':'Synthetic Carrier','net_amount':'10.00','tax_amount':'2.00','gross_amount':'12.00','running_wallet_balance':'88.00'}],'notice':'Synthetic statement for testing.'}
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge');page=await browser.new_page(viewport={'width':1440,'height':1100});page.on('pageerror',lambda e:errors.append(str(e)))
        async def handler(route):
            nonlocal current_plan,invoice_pending
            path=urlsplit(route.request.url).path
            if urlsplit(route.request.url).hostname!='billing.test':return await route.abort()
            if path=='/workspace':return await route.fulfill(body=(ROOT/'index.html').read_text(encoding='utf-8'),content_type='text/html')
            if path.startswith('/api/') or path=='/health':
                if path.startswith('/api/v1/billing') and path!='/api/v1/billing/wallet-activity':requests.append((path,route.request.method))
                if path=='/health':data={'mode':'local-preview','status':'ok'}
                elif path=='/api/v1/config':data={'mode':'local-preview'}
                elif path.endswith('/shipments/manifest'):data={'shipments':[]}
                elif path=='/api/v1/wallet':data={'balance':'100.00','reserved_balance':'0.00','currency':'GBP'}
                elif path.startswith('/api/v1/billing/topups/') :data={'status':'CREDITED','amount':'100.00','currency':'GBP'}
                elif path=='/api/v1/billing/wallet-activity':data={'entries':[]}
                elif path=='/api/v1/billing/wallet-ledger':
                    query=parse_qs(urlsplit(route.request.url).query)
                    if wallet_failure and query.get('limit')==['1']:return await route.fulfill(status=503,json={'detail':'Wallet balance is unavailable. Reload billing details before choosing payment.'})
                    topup={'id':'funding','entry_type':'TOPUP','balance_delta':'100.00','balance_after':'100.00','currency':'GBP','reference':'cs_test_funding','created_at':'2026-11-20T12:00:00Z'}
                    charge={'id':'label','entry_type':'CAPTURE','balance_delta':'-12.00','balance_after':'88.00','currency':'GBP','reference':'ORDER-1','shipment_id':'00000000-0000-4000-8000-000000000099','created_at':'2026-11-21T12:00:00Z'}
                    hold={**charge,'entry_type':'RESERVE','balance_delta':'0.00','reserved_delta':'5.00'}
                    entries=[topup] if 'cursor' in query or query.get('category')==['TOPUPS'] else [charge]+([hold] if query.get('holds')==['true'] else [])
                    data={'entries':entries,'next_cursor':None if 'cursor' in query else 'second','wallet':{'balance':'88.00','available':wallet_available,'reserved_balance':'5.00','currency':'GBP'},'month_to_date':{'shipping_gross':'12.00','refunds_gross':'0.00','recorded_shipping_vat':'2.00','missing_tax':0}}
                elif path=='/api/v1/billing/capabilities':data={'statements_enabled':enabled,'subscription_changes_enabled':can_manage,'message':'Billing statements are not enabled for this deployment.'}
                elif statement_failure and path.startswith('/api/v1/billing/statements'):
                    return await route.fulfill(status=503,json={'detail':{'code':'TEST_UNAVAILABLE','message':'Statement service temporarily unavailable. Please retry.'}})
                elif path=='/api/v1/billing/subscription' or (path.endswith('/process') and path.startswith('/api/v1/billing/subscription/')):
                    await gate.wait();rank=['STARTER','VELOCITY','COMMAND'].index(current_plan)
                    management={'reason':'This is complimentary access with no paid renewal to cancel.' if unbounded else None,'upgrade_targets':['STARTER','VELOCITY','COMMAND'][rank+1:] if not unbounded else [],'downgrade_targets':['STARTER','VELOCITY','COMMAND'][:rank] if not unbounded else [],'can_cancel':not unbounded and rank>0,'activation_targets':['VELOCITY','COMMAND'] if unbounded else []}
                    data={'tax':{'rate_percent':'20','prices_exclude_tax':True},'registered_at':registered,'activation_checkout_available':{'VELOCITY':prices_ready,'COMMAND':prices_ready},'is_sandbox':unbounded,'can_manage':can_manage,'management':management,'plans':plans,'subscription':{'subscription_plan':current_plan,'billing_cycle':'ANNUAL' if unbounded else 'MONTHLY','plan_status':'ACTIVE','subscription_complimentary':unbounded,'plan_period_start':'2026-11-28T01:23:49Z','plan_period_end':None if unbounded else '2026-12-28T01:23:49Z','stripe_subscription_id':None if unbounded else 'sub_synthetic'},'operations':([{'id':'change-demo','action':'UPGRADE','state':'PROVIDER_PENDING','provider_url':'https://invoice.stripe.com/i/synthetic','funding':'STRIPE'}] if invoice_pending else [{'id':'old-failed','state':'FAILED','action':'UPGRADE','error_code':'UNPAID_SETUP_RESTART_REQUIRED'}]),'wallet':{'currency':'GBP','available':'0.00'},'usage':{'parcels':48}}
                elif path=='/api/v1/billing/subscription/reconcile':
                    assert route.request.method=='POST' and not route.request.post_data
                    data={'reconciled':False}
                elif path=='/api/v1/billing/subscription/cancel':
                    body=route.request.post_data_json;commands.append((path,body));data={'id':'operation-demo','state':'SCHEDULED' if body.get('confirm') else 'PREVIEW','source_plan':'VELOCITY','target_plan':'STARTER','effective_at':'2026-12-15T00:00:00Z','amount':'0.00','payload_sha256':'a'*64,'payload':{'breakdown':{'annual_clawback':{'usage_at_monthly_price':'5.00','notice_at_monthly_price':'24.84','verified_annual_prepaid_net':'240.00','net_refund':'210.16','additional_balance_for_review':'0.00'}}}}
                elif path in {'/api/v1/billing/subscription/upgrade','/api/v1/billing/subscription/downgrade'}:
                    body=route.request.post_data_json;commands.append((path,body))
                    if review_failure:return await route.fulfill(status=409,json={'detail':'The agreement requires reconciliation. No charge was made.'})
                    action='UPGRADE' if path.endswith('/upgrade') else 'DOWNGRADE'
                    data={'id':'change-demo','state':('APPLIED' if action=='UPGRADE' else 'SCHEDULED') if body.get('confirm') else 'PREVIEW','source_plan':current_plan,'target_plan':body['target_plan'],'effective_at':'2026-11-28T01:37:04Z' if action=='UPGRADE' else '2026-12-28T01:23:49Z','amount':'59.98' if action=='UPGRADE' else '0.00','payload_sha256':'b'*64,'payload':{'net_amount':'49.98' if action=='UPGRADE' else '0.00','tax_amount':'10.00' if action=='UPGRADE' else '0.00','tax_rate_percent':'20','breakdown':{'remaining_days':'29.990798611111111111111111111','total_days':'30','prorated_amount':'49.98'} if action=='UPGRADE' else {'next_period_price':'240.00'}}}
                    if action=='UPGRADE' and body.get('confirm'):
                        if card_flow:invoice_pending=True;data['state']='AUTHORIZED'
                        else:current_plan=body['target_plan']
                elif path=='/api/v1/billing/statements' and route.request.method=='GET':data={'statements':[snapshot]}
                elif path=='/api/v1/billing/statements/monthly':
                    body=route.request.post_data_json;assert body=={'year':2026,'month':9,'currency':'GBP'};data={**snapshot,'period_start':'2026-09-01T00:00:00Z','period_end':'2026-10-01T00:00:00Z','display_reference':'EI-01092026-30092026'}
                elif path=='/api/v1/billing/statements':raise AssertionError('Custom date ranges must never be persisted')
                elif path.endswith('/preview'):
                    query={} if ignore_dates else parse_qs(urlsplit(route.request.url).query);data={**snapshot,'id':None,'preview':True,'period_start':query.get('start',['2026-11-01T00:00:00Z'])[0],'period_end':query.get('end',['2026-11-22T12:00:00Z'])[0]}
                elif path.startswith('/api/v1/billing/statements/'):data=snapshot
                else:data={}
                return await route.fulfill(json=data)
            asset=ROOT/path.lstrip('/')
            if asset.is_file() and asset.suffix in {'.js','.css','.svg'}:return await route.fulfill(body=asset.read_bytes(),content_type={'.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'}[asset.suffix])
            return await route.fulfill(status=404,json={'detail':'Unavailable'})
        await page.route('**/*',handler);await page.goto('https://billing.test/workspace');await page.wait_for_function("typeof state!=='undefined' && document.querySelector('#billing-workspace')")
        await page.evaluate("""() => {state.session={access_token:'synthetic',expires_at:Date.now()/1000+900};identityProfile={email:'owner@example.invalid'};portal.profile={tenant_id:'00000000-0000-4000-8000-000000000001',workspace_role:'OWNER',portal_role:'CLIENT'};state.mode='configured';document.body.classList.remove('auth-locked','auth-checking');document.querySelector('#loginContainer').hidden=true;setView('wallet');ensureActiveIdentitySession=async()=>{};}""")
        await expect(page.locator('#billing-workspace')).to_be_visible();await expect(page.locator('#billing-status')).to_contain_text('not enabled')
        assert await page.locator('link[rel=manifest]').get_attribute('crossorigin')=='use-credentials'
        await expect(page.locator('#billing-status')).to_contain_text('not enabled')
        await expect(page.locator('#billing-preview')).to_be_disabled();await expect(page.locator('#billing-generate')).to_be_disabled()
        assert ('/api/v1/billing/capabilities','GET') in requests
        assert ('/api/v1/billing/wallet-ledger','GET') in requests
        enabled=True
        await page.locator('#billing-refresh').click();await expect(page.locator('#billing-agreement')).to_contain_text('Velocity')
        await expect(page.locator('#billing-change')).to_be_hidden();assert 'Queued payments' not in await page.locator('#billing-status').inner_text()
        await expect(page.locator('#finance-available')).to_have_text('£83.00')
        await expect(page.locator('#ledger-table')).to_contain_text('LABEL CHARGE')
        await expect(page.locator('#ledger-table')).not_to_contain_text('HOLD RELEASE')
        await page.locator('#ledger-next').click();await expect(page.locator('#ledger-table')).to_contain_text('TOP-UP')
        await page.locator('#ledger-prev').click();await expect(page.locator('#ledger-table')).to_contain_text('LABEL CHARGE')
        await page.locator('#ledger-holds').check();await expect(page.locator('#ledger-table')).to_contain_text('HOLD')
        await page.locator('[data-ledger-filter=TOPUPS]').click();await expect(page.locator('#ledger-table')).not_to_contain_text('LABEL CHARGE')
        assert await page.locator('#invoice-audit-panel').count()==0
        await page.set_viewport_size({'width':390,'height':844});await page.locator('#billing-kpis').screenshot(path=str(out/'enterprise-summary-mobile.png'));assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        await page.set_viewport_size({'width':1440,'height':1100})
        await page.locator('#wallet').screenshot(path=str(out/'enterprise-wallet.png'))

        await page.locator('#billing-compare').click();await expect(page.locator('#billing-comparison')).to_be_visible();await expect(page.locator('#billing-comparison')).to_contain_text('WhatsApp booking')
        await page.keyboard.press('Escape');await expect(page.locator('#billing-comparison')).to_be_hidden()
        await expect(page.locator('#billing-agreement')).not_to_contain_text('Finance review')
        await expect(page.locator('#billing-agreement')).not_to_contain_text('Not completed')
        wallet_available='250.00'
        await page.locator('#billing-refresh').click()
        await expect(page.locator('#finance-available')).to_have_text('£250.00')
        wallet_failure=True
        await page.locator('#billing-refresh').click()
        await expect(page.locator('#billing-status')).to_contain_text('Wallet balance is unavailable')
        await expect(page.locator('#billing-agreement')).to_contain_text('Current plan: Velocity')
        await expect(page.locator('#billing-wallet-available')).to_contain_text('balance unavailable')
        await expect(page.locator('[name="billing-funding"][value="WALLET"]')).to_be_disabled()
        wallet_failure=False
        await page.locator('#billing-refresh').click()
        await expect(page.locator('#billing-wallet-available')).to_have_text('(GBP 250.00 available)')

        await page.locator('#billing-manage').click();await expect(page.locator('#billing-change')).to_be_visible()
        await page.locator('#billing-target').select_option('COMMAND');await expect(page.locator('#billing-plan-review')).to_have_text('Review upgrade to Command')
        # Renew the token during a failed financial review: retain the agreement and error.
        await page.evaluate("window.billingRenew=true;ensureActiveIdentitySession=async()=>{if(window.billingRenew){state.session.access_token='renewed-synthetic';window.billingRenew=false;}}")
        review_failure=True
        await page.locator('#billing-plan-review').click();await expect(page.locator('#billing-status')).to_contain_text('requires reconciliation')
        await expect(page.locator('#billing-agreement')).to_contain_text('Velocity');await expect(page.locator('#billing-change')).to_be_visible()
        review_failure=False
        await page.locator('#billing-plan-review').click();await expect(page.locator('#billing-quote')).to_contain_text('49.98')
        assert not any(body.get('confirm') for _,body in commands)
        await expect(page.locator('#billing-payment-options')).to_be_visible()
        await expect(page.locator('#billing-wallet-available')).to_have_text('(GBP 250.00 available)')
        await expect(page.locator('[name="billing-funding"][value="WALLET"]')).to_be_enabled()
        await expect(page.locator('#billing-quote')).to_contain_text('29.99 / 30.00 days left')
        await expect(page.locator('#billing-quote')).not_to_contain_text('Stripe')
        await expect(page.locator('#billing-quote')).not_to_contain_text('111111')
        await expect(page.locator('#billing-agreement')).not_to_contain_text('00:00:00')
        await page.locator('[name="billing-funding"][value="WALLET"]').check()
        await expect(page.locator('#billing-confirm')).to_be_hidden()
        await page.locator('#billing-plan-review').click()
        await expect(page.locator('#billing-confirm')).to_contain_text('pay from wallet')
        await expect(page.locator('#billing-quote')).to_contain_text('VAT (20%) GBP 10.00')
        await expect(page.locator('#billing-quote')).to_contain_text('Total GBP 59.98')
        await expect(page.locator('#billing-quote')).not_to_contain_text('wallet tax')
        assert commands[-1][1]['funding']=='WALLET' and not commands[-1][1].get('confirm')
        await page.locator('#billing-change').screenshot(path=str(out/'upgrade-wallet.png'))
        await page.set_viewport_size({'width':390,'height':900})
        await page.locator('#billing-change').screenshot(path=str(out/'upgrade-wallet-mobile.png'))
        assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        await page.set_viewport_size({'width':1440,'height':1100})
        await page.locator('#billing-confirm').click();await expect(page.locator('#billing-status')).to_contain_text('Upgrade applied')
        await expect(page.locator('#finance-plan strong')).to_have_text('Command')
        await expect(page.locator('#billing-agreement')).to_contain_text('Current plan: Command')
        # Card confirmation prepares an actionable invoice; access stays unchanged.
        current_plan='VELOCITY';card_flow=True
        await page.locator('#billing-refresh').click()
        await page.locator('#billing-target').select_option('COMMAND')
        await page.locator('[name="billing-funding"][value="STRIPE"]').check()
        await page.locator('#billing-plan-review').click();await page.locator('#billing-confirm').click()
        await expect(page.locator('#billing-quote a')).to_have_text('Pay by card')
        await page.locator('#billing-change').screenshot(path=str(out/'upgrade-card-invoice.png'))
        await expect(page.locator('#finance-plan strong')).to_have_text('Velocity')
        await expect(page.locator('#billing-quote')).not_to_contain_text('Stripe')
        invoice_pending=False;card_flow=False;current_plan='COMMAND'
        await page.locator('#billing-refresh').click()
        await expect(page.locator('#finance-plan strong')).to_have_text('Command')

        await page.locator('#billing-refresh').click();await page.locator('#billing-target').select_option('VELOCITY')
        await expect(page.locator('#billing-plan-review')).to_have_text('Review downgrade to Velocity')
        await page.locator('#billing-plan-review').click();assert commands[-1][0].endswith('/downgrade')
        await expect(page.locator('#billing-quote')).to_contain_text('No payment due now.')
        await expect(page.locator('[aria-label="Next renewal total"]')).to_contain_text('GBP 30.00')
        await expect(page.locator('#billing-quote')).to_contain_text('Refund / credit now: GBP 0.00')
        await expect(page.locator('#billing-quote')).not_to_contain_text('Payment: card')
        retention=page.locator('[aria-label="Downgrade comparison"]')
        await expect(retention).to_contain_text('Before you switch to Velocity')
        await expect(retention).to_contain_text('Detailed ledger exports')
        await expect(retention).not_to_contain_text('WhatsApp booking')
        await expect(retention).not_to_contain_text('Customs')
        await expect(retention).to_contain_text('4,000')
        await expect(retention).to_contain_text('2,000')
        await expect(retention).to_contain_text('Save GBP 50.00/month')
        await retention.screenshot(path=str(out/'downgrade-command-velocity.png'))
        confirmations=sum(bool(body.get('confirm')) for _,body in commands)
        await page.locator('[data-keep-current-plan]').click()
        await expect(page.locator('#billing-status')).to_contain_text('keeping Command')
        await expect(page.locator('#billing-change')).to_be_hidden()
        assert sum(bool(body.get('confirm')) for _,body in commands)==confirmations
        await page.locator('#billing-manage').click()
        await page.locator('#billing-target').select_option('VELOCITY');await page.locator('#billing-plan-review').click()
        await expect(page.locator('#billing-confirm')).to_have_text('Confirm scheduled downgrade');await page.locator('#billing-confirm').click()
        await expect(page.locator('#billing-status')).to_contain_text('Downgrade scheduled')
        current_plan='VELOCITY'
        await page.locator('#billing-refresh').click()
        await page.locator('#billing-target').select_option('STARTER');await page.locator('#billing-plan-review').click()
        retention=page.locator('[aria-label="Downgrade comparison"]')
        await expect(retention).to_contain_text('Connected sales channels')
        await expect(retention).to_contain_text('WhatsApp booking')
        await expect(retention).to_contain_text('Self-serve returns')
        await expect(retention).to_contain_text('Save GBP 25.00/month')
        await expect(retention).to_contain_text('150')
        await expect(retention).not_to_contain_text('Detailed ledger exports')
        await page.locator('#billing-change').screenshot(path=str(out/'downgrade-velocity-starter.png'))
        await page.set_viewport_size({'width':390,'height':900})
        await retention.screenshot(path=str(out/'downgrade-velocity-starter-mobile.png'))
        assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        await page.set_viewport_size({'width':1440,'height':1100})
        await page.locator('[data-keep-current-plan]').click()
        await expect(page.locator('#finance-plan strong')).to_have_text('Velocity')
        await page.locator('#billing-manage').click()
        await page.locator('[data-billing-action=CANCEL]').click();await expect(page.locator('#billing-quote')).to_contain_text('210.16');await expect(page.locator('#billing-quote')).to_contain_text('Annual discount removed')
        await expect(page.locator('#billing-confirm')).to_have_text('Confirm cancellation')
        assert not commands[-1][1].get('confirm')
        assert not any(method=='POST' for path,method in requests if path.endswith('/statements'))
        await page.locator('#billing-confirm').click();await expect(page.locator('#billing-status')).to_contain_text('Cancellation scheduled')
        statement_failure=True
        await page.locator('#billing-preview').click();await expect(page.locator('#billing-statement-status')).to_contain_text('temporarily unavailable')
        await expect(page.locator('#billing-statement-status')).to_have_attribute('role','alert');await expect(page.locator('#billing-preview')).to_be_enabled()
        statement_failure=False
        await page.locator('#billing-preview').click();await expect(page.locator('#billing-statement-status')).to_contain_text('Activity ready')
        await page.locator('#billing-from').fill('2026-08-01');await page.locator('#billing-until').fill('2026-10-31')
        ignore_dates=True
        await page.locator('#billing-generate').click();await expect(page.locator('#billing-statement-status')).to_contain_text('Restart the local server')
        ignore_dates=False
        await page.locator('#billing-generate').click();await expect(page.locator('#billing-statement')).to_contain_text('2026-08-01')
        await expect(page.locator('#billing-statement')).to_contain_text('2026-10-31')
        await expect(page.locator('[data-billing-export="pdf"]')).to_be_visible();await expect(page.locator('[data-billing-export="csv"]')).to_be_visible()
        await page.locator('#billing-previous summary').click();await page.locator('#billing-month').fill('2026-09')
        await page.locator('#billing-save').click();await expect(page.locator('#billing-statement')).to_contain_text('EI-01092026-30092026')
        await expect(page.locator('#billing-statement')).to_contain_text('2026-09-30')
        # Stripe reconciliation, not a return URL, closes the funding dialog.
        await page.evaluate("async()=>{const original=refreshBookingWallet;refreshBookingWallet=async()=>{};openStripePaymentModal();await verifyStripeCredit('00000000-0000-4000-8000-000000000077',state.session);refreshBookingWallet=original;}")
        await expect(page.locator('#stripePaymentModal')).not_to_be_visible();await expect(page.locator('#wallet')).to_be_visible()
        await page.locator('[data-ledger-filter="ALL"]').click();await page.locator('[data-finance-shipment]').first.click()
        await expect(page.locator('[data-return-wallet]')).to_be_visible();await page.locator('[data-return-wallet]').click();await expect(page.locator('#wallet')).to_be_visible()
        await page.locator('[data-finance-shipment]').first.click();await page.locator('[data-show-shipments]').click();await expect(page.locator('#manifest-search')).to_have_value('');await page.evaluate("setView('wallet')")

        await page.locator('[data-statement-id]').click();await expect(page.locator('#billing-statement')).to_contain_text('<script>bad()</script>');assert await page.locator('#billing-statement script').count()==0
        out=ROOT/'output/subscription-qa/billing';out.mkdir(parents=True,exist_ok=True);await page.locator('#billing-workspace').screenshot(path=str(out/'workspace-owner.png'))
        current_plan='COMMAND';unbounded=True
        await page.locator('#billing-refresh').click();await expect(page.locator('#billing-agreement')).not_to_contain_text('Test workspace')
        await page.locator('#billing-manage').click();await expect(page.locator('#billing-target')).to_be_visible()
        await page.locator('#billing-target').select_option('VELOCITY');await page.locator('#billing-plan-review').click()
        await expect(page.locator('#billing-quote')).to_contain_text('New subscription');await expect(page.locator('#billing-quote')).to_contain_text('240.00')
        assert ('/api/v1/billing/subscription/reconcile','POST') in requests
        await expect(page.locator('#billing-confirm')).to_have_text('Confirm plan and continue to payment')
        await expect(page.locator('#billing-cancel')).to_be_disabled();await expect(page.locator('#billing-confirm')).to_be_enabled()
        prices_ready=False
        await page.locator('#billing-refresh').click();await page.locator('#billing-target').select_option('VELOCITY');await page.locator('#billing-plan-review').click()
        await expect(page.locator('#billing-confirm')).to_be_disabled();await expect(page.locator('#billing-status')).to_contain_text('payments are not configured')
        count=len(commands);await page.locator('#billing-compare').click();await expect(page.locator('#billing-comparison')).to_be_visible();await page.locator('#billing-comparison-close').click();assert len(commands)==count
        registered=datetime.now(timezone.utc).isoformat()
        await page.locator('#billing-refresh').click()
        await expect(page.locator('#billing-month')).to_be_hidden()
        await expect(page.locator('#billing-statements')).to_have_text('No statements to display.')
        today=datetime.now(timezone.utc).date().isoformat()
        await expect(page.locator('#billing-from')).to_have_attribute('min',today)
        await page.locator('#billing-from').fill((datetime.now(timezone.utc).date()-timedelta(days=1)).isoformat())
        await page.locator('#billing-until').fill(today)
        count=len(requests)
        await page.locator('#billing-generate').click()
        await expect(page.locator('#billing-statement-status')).to_contain_text('on or after your registration date')
        assert len(requests)==count
        registered='2026-07-15T10:00:00Z'
        # A response from the previous workspace must be discarded after a role change.
        gate.clear();await page.locator('#billing-refresh').click()
        await page.evaluate("portal.profile.workspace_role='DISPATCHER';setView('wallet')")
        gate.set();await expect(page.locator('#billing-workspace')).to_be_hidden()
        await page.evaluate("portal.profile.workspace_role='ACCOUNTANT';setView('wallet')")
        # Backend's read-only flag controls visibility even if the DOM was previously Owner.
        await expect(page.locator('#billing-change')).to_be_hidden();await expect(page.locator('#billing-statement')).to_be_empty()
        can_manage=False
        await page.locator('#billing-refresh').click();await expect(page.locator('#billing-agreement')).to_contain_text('Command');await expect(page.locator('#billing-change')).to_be_hidden()
        await page.set_viewport_size({'width':390,'height':844});await page.locator('#billing-compare').click()
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        await page.locator('#billing-comparison').screenshot(path=str(out/'plan-comparison-mobile.png'))
        await page.keyboard.press('Escape')
        # A token with different permission/session claims clears cached financial data.
        await page.evaluate("state.session.access_token='header.'+btoa(JSON.stringify({jti:'first',user_id:'user',tenant_id:portal.profile.tenant_id,role:'ACCOUNTANT'}))+'.signature';setView('wallet')")
        await page.locator('#billing-refresh').click();await expect(page.locator('#billing-agreement')).to_contain_text('Command')
        await page.evaluate("state.session.access_token='header.'+btoa(JSON.stringify({jti:'first',user_id:'user',tenant_id:portal.profile.tenant_id,role:'DISPATCHER'}))+'.signature';setView('wallet')")
        await expect(page.locator('#billing-agreement')).to_be_empty()
        assert not errors,errors
        report={'passed':True,'page_errors':errors,'checks':['automatic upgrade/downgrade direction','token renewal preserves panel and conflict error','financial review precedes confirmation','explicit cancellation review and confirmation','unpaid sandbox account can review a new subscription without a charge','closable feature comparison with keyboard support','disabled features discovered without failed statement requests','statement errors visible beside controls and retry succeeds','current month, custom dates and monthly picker work; stale API is detected','protected manifest includes credentials','statement content escaped','late Owner response discarded on role change','Dispatcher cannot see financial panel','Accountant read-only state','mobile viewport fits']}
        (out/'browser-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));await browser.close()
if __name__=='__main__':asyncio.run(main())
