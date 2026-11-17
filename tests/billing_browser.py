"""Synthetic browser QA of billing presentation; no real sessions or providers."""
import asyncio,json,os,time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'.playwright'))

async def main():
    errors=[];requests=[];gate=asyncio.Event();gate.set();can_manage=True
    snapshot={'id':'00000000-0000-4000-8000-000000000003','statement_number':'EI-DEMO','period_start':'2026-10-01','period_end':'2026-11-01','currency':'GBP','opening_balance':'100.00','closing_balance':'88.00','total_topups':'0.00','subscription_net':'0.00','shipping_net':'10.00','refunds_net':'0.00','tax_total':'2.00','gross_total':'12.00','tax_complete':True,'transactions':[{'occurred_at':'2026-10-15T12:00:00Z','type':'SHIPPING','reference':'<script>bad()</script>','carrier':'Synthetic Carrier','net_amount':'10.00','tax_amount':'2.00','gross_amount':'12.00','running_wallet_balance':'88.00'}],'notice':'Synthetic statement for testing.'}
    async with async_playwright() as p:
        browser=await p.chromium.launch();page=await browser.new_page(viewport={'width':1440,'height':1100});page.on('pageerror',lambda e:errors.append(str(e)))
        async def handler(route):
            path=urlsplit(route.request.url).path
            if urlsplit(route.request.url).hostname!='billing.test':return await route.abort()
            if path=='/workspace':return await route.fulfill(body=(ROOT/'index.html').read_text(encoding='utf-8'),content_type='text/html')
            if path.startswith('/api/') or path=='/health':
                if path.startswith('/api/v1/billing'):requests.append((path,route.request.method))
                if path=='/health':data={'mode':'local-preview','status':'ok'}
                elif path=='/api/v1/config':data={'mode':'local-preview'}
                elif path=='/api/v1/billing/subscription':
                    await gate.wait();data={'can_manage':can_manage,'subscription':{'subscription_plan':'VELOCITY','billing_cycle':'ANNUAL','plan_status':'ACTIVE','plan_period_start':'2026-11-09T00:00:00Z','plan_period_end':'2027-11-09T00:00:00Z','stripe_subscription_id':'sub_synthetic'},'operations':[]}
                elif path=='/api/v1/billing/subscription/cancel':
                    body=route.request.post_data_json;data={'id':'operation-demo','state':'AUTHORIZED' if body.get('confirm') else 'PREVIEW','source_plan':'VELOCITY','target_plan':'STARTER','effective_at':'2026-12-15T00:00:00Z','amount':'0.00','payload_sha256':'a'*64,'payload':{'breakdown':{'annual_clawback':{'usage_at_monthly_price':'5.80','notice_at_monthly_price':'28.81','verified_annual_prepaid_net':'288.00','net_refund':'253.39','additional_balance_for_review':'0.00'}}}}
                elif path=='/api/v1/billing/statements' and route.request.method=='GET':data={'statements':[snapshot]}
                elif path.endswith('/preview') or path.startswith('/api/v1/billing/statements/'):data=snapshot
                else:data={}
                return await route.fulfill(json=data)
            asset=ROOT/path.lstrip('/')
            if asset.is_file() and asset.suffix in {'.js','.css','.svg'}:return await route.fulfill(body=asset.read_bytes(),content_type={'.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'}[asset.suffix])
            return await route.fulfill(status=404,json={'detail':'Unavailable'})
        await page.route('**/*',handler);await page.goto('https://billing.test/workspace');await page.wait_for_function("typeof state!=='undefined' && document.querySelector('#billing-workspace')")
        await page.evaluate("""() => {state.session={access_token:'synthetic',expires_at:Date.now()/1000+900};identityProfile={email:'owner@example.invalid'};portal.profile={tenant_id:'00000000-0000-4000-8000-000000000001',workspace_role:'OWNER',portal_role:'CLIENT'};state.mode='configured';document.body.classList.remove('auth-locked','auth-checking');document.querySelector('#loginContainer').hidden=true;setView('wallet');ensureActiveIdentitySession=async()=>{};}""")
        await expect(page.locator('#billing-workspace')).to_be_visible();assert not requests
        await page.locator('#billing-refresh').click();await expect(page.locator('#billing-agreement')).to_contain_text('VELOCITY')
        await page.locator('[data-billing-action=CANCEL]').click();await expect(page.locator('#billing-quote')).to_contain_text('253.39');await expect(page.locator('#billing-quote')).to_contain_text('Annual discount removed')
        assert not any(method=='POST' for path,method in requests if path.endswith('/statements'))
        await page.locator('#billing-confirm').click();await expect(page.locator('#billing-status')).to_contain_text('AUTHORIZED')
        await page.locator('[data-statement-id]').click();await expect(page.locator('#billing-statement')).to_contain_text('<script>bad()</script>');assert await page.locator('#billing-statement script').count()==0
        out=ROOT/'output/subscription-qa/billing';out.mkdir(parents=True,exist_ok=True);await page.locator('#billing-workspace').screenshot(path=str(out/'workspace-owner.png'))
        # A response from the previous workspace must be discarded after a role change.
        gate.clear();await page.locator('#billing-refresh').click()
        await page.evaluate("portal.profile.workspace_role='DISPATCHER';setView('wallet')")
        gate.set();await expect(page.locator('#billing-workspace')).to_be_hidden()
        await page.evaluate("portal.profile.workspace_role='ACCOUNTANT';setView('wallet')")
        # Backend's read-only flag controls visibility even if the DOM was previously Owner.
        await expect(page.locator('#billing-change')).to_be_hidden();await expect(page.locator('#billing-statement')).to_be_empty()
        can_manage=False
        await page.locator('#billing-refresh').click();await expect(page.locator('#billing-agreement')).to_contain_text('VELOCITY');await expect(page.locator('#billing-change')).to_be_hidden()
        await page.set_viewport_size({'width':390,'height':844});assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert not errors,errors
        report={'passed':True,'page_errors':errors,'checks':['no billing reads until requested','server-owned cancellation preview and explicit confirmation','annual discount removal and refund disclosure','statement content escaped','late Owner response discarded on role change','Dispatcher cannot see financial panel','Accountant starts with cleared read-only state','mobile viewport fits']}
        (out/'browser-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));await browser.close()
if __name__=='__main__':asyncio.run(main())
