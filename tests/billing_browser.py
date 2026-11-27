"""Synthetic browser QA of billing presentation; no real sessions or providers."""
import asyncio,json,os,time,sys
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
    errors=[];requests=[];commands=[];gate=asyncio.Event();gate.set();can_manage=True;enabled=False;statement_failure=False;review_failure=False;current_plan='VELOCITY';unbounded=False
    plans=document([{'plan':p.value,'annual_fee_gbp':cycle_price(p,'ANNUAL'),**capabilities(p).model_dump()} for p in Plan])
    snapshot={'id':'00000000-0000-4000-8000-000000000003','statement_number':'EI-DEMO','period_start':'2026-10-01','period_end':'2026-11-01','currency':'GBP','opening_balance':'100.00','closing_balance':'88.00','total_topups':'0.00','subscription_net':'0.00','shipping_net':'10.00','refunds_net':'0.00','tax_total':'2.00','gross_total':'12.00','tax_complete':True,'transactions':[{'occurred_at':'2026-10-15T12:00:00Z','type':'SHIPPING','reference':'<script>bad()</script>','carrier':'Synthetic Carrier','net_amount':'10.00','tax_amount':'2.00','gross_amount':'12.00','running_wallet_balance':'88.00'}],'notice':'Synthetic statement for testing.'}
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge');page=await browser.new_page(viewport={'width':1440,'height':1100});page.on('pageerror',lambda e:errors.append(str(e)))
        async def handler(route):
            nonlocal current_plan
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
                    topup={'id':'funding','entry_type':'TOPUP','balance_delta':'100.00','balance_after':'100.00','currency':'GBP','reference':'cs_test_funding','created_at':'2026-11-20T12:00:00Z'}
                    charge={'id':'label','entry_type':'CAPTURE','balance_delta':'-12.00','balance_after':'88.00','currency':'GBP','reference':'ORDER-1','shipment_id':'00000000-0000-4000-8000-000000000099','created_at':'2026-11-21T12:00:00Z'}
                    hold={**charge,'entry_type':'RESERVE','balance_delta':'0.00','reserved_delta':'5.00'}
                    entries=[topup] if 'cursor' in query or query.get('category')==['TOPUPS'] else [charge]+([hold] if query.get('holds')==['true'] else [])
                    data={'entries':entries,'next_cursor':None if 'cursor' in query else 'second','wallet':{'balance':'88.00','available':'83.00','reserved_balance':'5.00','currency':'GBP'},'month_to_date':{'shipping_gross':'12.00','refunds_gross':'0.00','recorded_shipping_vat':'2.00','missing_tax':0}}
                elif path=='/api/v1/finance/audit-invoice-upload':data={'results':[{'upstream_shipment_id':'TRACK-1','currency':'GBP','billed_amount':'15.00','expected_amount':'12.00','estimated_overcharge':'3.00','status':'FLAGGED','dispute_id':'00000000-0000-4000-8000-000000000088','findings':[{'code':'WHOLESALE_COST_EXCEEDS_SNAPSHOT'}]}]}
                elif path.endswith('/support-case'):data={'ticket_id':'00000000-0000-4000-8000-000000000087','message':'Support case logged. No carrier submission or refund has been made.'}
                elif path=='/api/v1/billing/capabilities':data={'statements_enabled':enabled,'subscription_changes_enabled':can_manage,'message':'Billing statements are not enabled for this deployment.'}
                elif statement_failure and path.startswith('/api/v1/billing/statements'):
                    return await route.fulfill(status=503,json={'detail':{'code':'TEST_UNAVAILABLE','message':'Statement service temporarily unavailable. Please retry.'}})
                elif path=='/api/v1/billing/subscription':
                    await gate.wait();rank=['STARTER','VELOCITY','COMMAND'].index(current_plan)
                    management={'reason':'This is complimentary access with no paid renewal to cancel.' if unbounded else None,'upgrade_targets':['STARTER','VELOCITY','COMMAND'][rank+1:] if not unbounded else [],'downgrade_targets':['STARTER','VELOCITY','COMMAND'][:rank] if not unbounded else [],'can_cancel':not unbounded and rank>0}
                    data={'can_manage':can_manage,'management':management,'plans':plans,'subscription':{'subscription_plan':current_plan,'billing_cycle':'ANNUAL','plan_status':'ACTIVE','subscription_complimentary':unbounded,'plan_period_start':'2026-11-09T00:00:00Z','plan_period_end':None if unbounded else '2027-11-09T00:00:00Z','stripe_subscription_id':'sub_synthetic'},'operations':[],'usage':{'parcels':48}}
                elif path=='/api/v1/billing/subscription/cancel':
                    body=route.request.post_data_json;commands.append((path,body));data={'id':'operation-demo','state':'SCHEDULED' if body.get('confirm') else 'PREVIEW','source_plan':'VELOCITY','target_plan':'STARTER','effective_at':'2026-12-15T00:00:00Z','amount':'0.00','payload_sha256':'a'*64,'payload':{'breakdown':{'annual_clawback':{'usage_at_monthly_price':'5.00','notice_at_monthly_price':'24.84','verified_annual_prepaid_net':'240.00','net_refund':'210.16','additional_balance_for_review':'0.00'}}}}
                elif path in {'/api/v1/billing/subscription/upgrade','/api/v1/billing/subscription/downgrade'}:
                    body=route.request.post_data_json;commands.append((path,body))
                    if review_failure:return await route.fulfill(status=409,json={'detail':'The agreement requires reconciliation. No charge was made.'})
                    action='UPGRADE' if path.endswith('/upgrade') else 'DOWNGRADE'
                    data={'id':'change-demo','state':('APPLIED' if action=='UPGRADE' else 'SCHEDULED') if body.get('confirm') else 'PREVIEW','source_plan':current_plan,'target_plan':body['target_plan'],'effective_at':'2027-11-09T00:00:00Z','amount':'40.00' if action=='UPGRADE' else '0.00','payload_sha256':'b'*64,'payload':{'breakdown':{'remaining_days':'24','total_days':'30','prorated_amount':'40.00'} if action=='UPGRADE' else {'next_period_price':'240.00'}}}
                    if action=='UPGRADE' and body.get('confirm'):current_plan=body['target_plan']
                elif path=='/api/v1/billing/statements' and route.request.method=='GET':data={'statements':[snapshot]}
                elif path=='/api/v1/billing/statements':data=snapshot
                elif path.endswith('/preview'):
                    query=parse_qs(urlsplit(route.request.url).query);data={**snapshot,'id':None,'preview':True,'period_start':query.get('start',['2026-11-01T00:00:00Z'])[0],'period_end':query.get('end',['2026-11-22T12:00:00Z'])[0]}
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
        await page.locator('#invoice-upload-form [name=file]').set_input_files({'name':'invoice.csv','mimeType':'text/csv','buffer':b'upstream_shipment_id,currency,invoice_weight_kg,wholesale_cost,residential_fee\nTRACK-1,GBP,2,15,0\n'})
        await page.locator('#invoice-upload-form [name=invoice_reference]').fill('INV-BROWSER')
        await page.locator('#invoice-upload-form [type=submit]').click();await expect(page.locator('#invoice-audit-result')).to_contain_text('£3.00')
        await page.locator('[data-dispute-case]').click();await expect(page.locator('#audit-status')).to_contain_text('Support case logged')
        await page.set_viewport_size({'width':390,'height':844});await page.locator('#billing-kpis').screenshot(path=str(out/'enterprise-summary-mobile.png'));assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        await page.set_viewport_size({'width':1440,'height':1100})
        await page.locator('#wallet').screenshot(path=str(out/'enterprise-wallet.png'))

        await page.locator('#billing-compare').click();await expect(page.locator('#billing-comparison')).to_be_visible();await expect(page.locator('#billing-comparison')).to_contain_text('WhatsApp booking')
        await page.keyboard.press('Escape');await expect(page.locator('#billing-comparison')).to_be_hidden()
        await page.locator('#billing-manage').click();await expect(page.locator('#billing-change')).to_be_visible()
        await page.locator('#billing-target').select_option('COMMAND');await expect(page.locator('#billing-plan-review')).to_have_text('Review upgrade to Command')
        # Renew the token during a failed financial review: retain the agreement and error.
        await page.evaluate("window.billingRenew=true;ensureActiveIdentitySession=async()=>{if(window.billingRenew){state.session.access_token='renewed-synthetic';window.billingRenew=false;}}")
        review_failure=True
        await page.locator('#billing-plan-review').click();await expect(page.locator('#billing-status')).to_contain_text('requires reconciliation')
        await expect(page.locator('#billing-agreement')).to_contain_text('Velocity');await expect(page.locator('#billing-change')).to_be_visible()
        review_failure=False
        await page.locator('#billing-plan-review').click();await expect(page.locator('#billing-quote')).to_contain_text('40.00')
        assert not any(body.get('confirm') for _,body in commands)
        await page.locator('#billing-confirm').click();await expect(page.locator('#billing-status')).to_contain_text('Upgrade applied')
        await page.locator('#billing-refresh').click();await page.locator('#billing-target').select_option('VELOCITY')
        await expect(page.locator('#billing-plan-review')).to_have_text('Review downgrade to Velocity')
        await page.locator('#billing-plan-review').click();assert commands[-1][0].endswith('/downgrade')
        await expect(page.locator('#billing-confirm')).to_have_text('Confirm scheduled downgrade');await page.locator('#billing-confirm').click()
        await expect(page.locator('#billing-status')).to_contain_text('Downgrade scheduled')
        current_plan='VELOCITY'
        await page.locator('#billing-refresh').click()
        await page.locator('[data-billing-action=CANCEL]').click();await expect(page.locator('#billing-quote')).to_contain_text('210.16');await expect(page.locator('#billing-quote')).to_contain_text('Annual discount removed')
        await expect(page.locator('#billing-confirm')).to_have_text('Confirm cancellation')
        assert not commands[-1][1].get('confirm')
        assert not any(method=='POST' for path,method in requests if path.endswith('/statements'))
        await page.locator('#billing-confirm').click();await expect(page.locator('#billing-status')).to_contain_text('Cancellation scheduled')
        statement_failure=True
        await page.locator('#billing-preview').click();await expect(page.locator('#billing-statement-status')).to_contain_text('temporarily unavailable')
        await expect(page.locator('#billing-statement-status')).to_have_attribute('role','alert');await expect(page.locator('#billing-preview')).to_be_enabled()
        statement_failure=False
        await page.locator('#billing-preview').click();await expect(page.locator('#billing-statement-status')).to_contain_text('Activity loaded')
        await page.locator('#billing-from').fill('2026-08-01');await page.locator('#billing-until').fill('2026-10-31')
        await page.locator('#billing-generate').click();await expect(page.locator('#billing-statement')).to_contain_text('2026-08-01')
        await expect(page.locator('#billing-statement')).to_contain_text('2026-10-31')
        await expect(page.locator('[data-billing-export="pdf"]')).to_be_visible();await expect(page.locator('[data-billing-export="csv"]')).to_be_visible()
        await page.locator('#billing-save').click();await expect(page.locator('#billing-statement-status')).to_contain_text('1 to 32 days')
        await page.locator('#billing-from').fill('2026-10-01');await page.locator('#billing-save').click();await expect(page.locator('#billing-statement-status')).to_contain_text('created and retained')
        # Stripe reconciliation, not a return URL, closes the funding dialog.
        await page.evaluate("async()=>{const original=refreshBookingWallet;refreshBookingWallet=async()=>{};openStripePaymentModal();await verifyStripeCredit('00000000-0000-4000-8000-000000000077',state.session);refreshBookingWallet=original;}")
        await expect(page.locator('#stripePaymentModal')).not_to_be_visible();await expect(page.locator('#wallet')).to_be_visible()
        await page.locator('[data-ledger-filter="ALL"]').click();await page.locator('[data-finance-shipment]').first.click()
        await expect(page.locator('[data-return-wallet]')).to_be_visible();await page.locator('[data-return-wallet]').click();await expect(page.locator('#wallet')).to_be_visible()
        await page.locator('[data-finance-shipment]').first.click();await page.locator('[data-show-shipments]').click();await expect(page.locator('#manifest-search')).to_have_value('');await page.evaluate("setView('wallet')")

        await page.locator('[data-statement-id]').click();await expect(page.locator('#billing-statement')).to_contain_text('<script>bad()</script>');assert await page.locator('#billing-statement script').count()==0
        out=ROOT/'output/subscription-qa/billing';out.mkdir(parents=True,exist_ok=True);await page.locator('#billing-workspace').screenshot(path=str(out/'workspace-owner.png'))
        current_plan='COMMAND';unbounded=True
        await page.locator('#billing-refresh').click();await expect(page.locator('#billing-agreement')).to_contain_text('no paid renewal to cancel')
        await expect(page.locator('#billing-target')).to_be_hidden();await expect(page.locator('#billing-plan-review')).to_be_hidden();await expect(page.locator('#billing-cancel')).to_be_hidden()
        count=len(commands);await page.locator('#billing-compare').click();await expect(page.locator('#billing-comparison')).to_be_visible();await page.locator('#billing-comparison-close').click();assert len(commands)==count
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
        report={'passed':True,'page_errors':errors,'checks':['automatic upgrade/downgrade direction','token renewal preserves panel and conflict error','financial review precedes confirmation','explicit cancellation review and confirmation','unbounded complimentary account cannot submit paid changes','closable feature comparison with keyboard support','disabled features discovered without failed statement requests','statement errors visible beside controls and retry succeeds','both statement buttons work','protected manifest includes credentials','statement content escaped','late Owner response discarded on role change','Dispatcher cannot see financial panel','Accountant read-only state','mobile viewport fits']}
        (out/'browser-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));await browser.close()
if __name__=='__main__':asyncio.run(main())
