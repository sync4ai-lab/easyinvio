"""Shipment phone UI contracts; no carrier requests or customer records."""
import asyncio,json,os,socket,threading,time
from pathlib import Path
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from playwright.async_api import async_playwright
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())

async def run(origin):
    errors=[]
    async with async_playwright() as pw:
        browser=await pw.chromium.launch();page=await browser.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        await page.route('**/api/v1/**',lambda route:route.fulfill(json={'mode':'local-preview','supabase_url':None,'publishable_key':None}))
        await page.goto(origin,wait_until='domcontentloaded')
        async def probe(value,dispatch=True):
            return await page.evaluate('''({value,dispatch})=>{
                const phone=document.querySelector('#destination-phone');phone.value=value;
                if(dispatch)phone.dispatchEvent(new Event('input',{bubbles:true}));
                let result,error=null;try{result=address('destination')}catch(e){error=e.message}
                return {value:phone.value,valid:phone.validity.valid,error,result,open:phone.closest('details').open,type:phone.type};
            }''',{'value':value,'dispatch':dispatch})
        invalid=await probe('07700900123')
        assert not invalid['valid'] and invalid['value']=='07700900123'
        assert 'recipient phone with +' in invalid['error'] and invalid['open']
        for value in ['+44 7700 900123','0044 (7700) 900-123','+447700900123']:
            result=await probe(value)
            assert result['valid'] and result['result']['phone']=='+447700900123',result
            assert result['type']=='tel'
        blank=await probe('')
        assert blank['valid'] and 'phone' not in blank['result']
        assert not (await probe('+44 ABC 123'))['valid']
        assert not (await probe('123',dispatch=False))['valid']
        assert (await probe('+12025550123'))['valid']
        assert not errors,errors
        await browser.close()
    print(json.dumps({'status':'PASS','checks':['National numbers receive a clear field error','No guessed country codes','Explicit international formatting normalized','Blank optional phone omitted','Saved or scripted invalid values blocked'],'javascript_errors':errors},indent=2))

if __name__ == '__main__':
    app = FastAPI()

    @app.get('/')
    async def frontend():
        return FileResponse('index.html')

    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError('Isolated server did not start')
            time.sleep(.05)
        asyncio.run(run(origin))
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
