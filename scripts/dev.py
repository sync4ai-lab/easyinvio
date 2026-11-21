"""Start the complete local app without rebuilding or deploying to Vercel."""
import argparse
import json
import logging
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',default=str(ROOT/'.env.local'))
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--lan',action='store_true',help='Allow phones on your trusted Wi-Fi to connect')
    parser.add_argument('--preview',action='store_true',help='Layout only: no sign-in or database')
    parser.add_argument('--public-url',help='Your trusted Wi-Fi URL or HTTPS tunnel origin, without a path')
    parser.add_argument('--whatsapp',action='store_true',help='Run only the WhatsApp queue in addition to the web app')
    parser.add_argument('--hosted-whatsapp-paused',action='store_true',help='Confirm hosted consumers for the same Gupshup app are paused')
    args=parser.parse_args()
    if args.whatsapp and not args.hosted_whatsapp_paused:
        parser.error('Pause hosted WhatsApp consumers first, then add --hosted-whatsapp-paused. The database/queue is shared.')
    os.chdir(ROOT);sys.path.insert(0,str(ROOT))
    if not args.preview:
        from dotenv import load_dotenv
        if not Path(args.env_file).is_file():parser.error('Create private .env.local first; see docs/local_uat_production.md')
        load_dotenv(args.env_file,override=True)
    # Import every router before starting Uvicorn. Running main.py directly
    # starts its CLI before the routers at the end of that file are imported.
    os.environ['RUNTIME_ROLE']='WEB'
    os.environ.pop('VERCEL',None)
    if args.preview:sys.argv.append('--local-preview')
    base=f'http://127.0.0.1:{args.port}'
    if args.public_url:
        from urllib.parse import urlsplit
        parsed=urlsplit(args.public_url)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            parser.error('--public-url must be a fixed origin without credentials, path or query')
    for name in ['FRONTEND_ALLOWED_ORIGINS']:
        origins=json.loads(os.environ.get(name,'[]'))
        for origin in [base,f'http://localhost:{args.port}']:
            if origin not in origins:origins.append(origin)
        if args.public_url and args.public_url not in origins:origins.append(args.public_url)
        os.environ[name]=json.dumps(origins)
    os.environ['AUTH_RECOVERY_REDIRECT_URL']=base+'/set-password'
    os.environ['CHECKOUT_SUCCESS_URL']=base+'/workspace?payment=success'
    os.environ['CHECKOUT_CANCEL_URL']=base+'/workspace?payment=cancel'
    if args.public_url and args.public_url.startswith('https://'):
        os.environ['BOOKING_PAGE_URL']=args.public_url
        os.environ['AUTH_RECOVERY_REDIRECT_URL']=args.public_url+'/set-password'
        os.environ['CHECKOUT_SUCCESS_URL']=args.public_url+'/workspace?payment=success'
        os.environ['CHECKOUT_CANCEL_URL']=args.public_url+'/workspace?payment=cancel'
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
    from main import app
    if args.whatsapp:
        import asyncio
        from contextlib import asynccontextmanager,suppress
        original=app.router.lifespan_context
        @asynccontextmanager
        async def local_whatsapp(application):
            async with original(application):
                queue=getattr(application.state,'whatsapp_queue',None)
                if queue is None:raise RuntimeError('Enable the configured WhatsApp provider first')
                task=asyncio.create_task(queue.worker())
                try:yield
                finally:
                    task.cancel()
                    with suppress(asyncio.CancelledError):await task
        app.router.lifespan_context=local_whatsapp
    print('Landing: '+base+'/\nSign in: '+base+'/login\nWorkspace: '+base+'/workspace\nPricing: '+base+'/pricing',flush=True)
    print('Background jobs: '+('WhatsApp only (shared queue)' if args.whatsapp else 'off'),flush=True)
    import uvicorn
    uvicorn.run(app,host='0.0.0.0' if args.lan else '127.0.0.1',port=args.port,access_log=False,proxy_headers=False)


if __name__=='__main__':main()
