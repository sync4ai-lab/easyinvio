"""Run the isolated offline provider lab. Does not load .env or start main workers."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',default=str(ROOT/'.env.providers-demo.example'))
    parser.add_argument('--port',type=int,default=8010)
    parser.add_argument('--lan',action='store_true')
    args=parser.parse_args()
    sys.path.insert(0,str(ROOT))
    from dotenv import dotenv_values
    from backend.provider_simulation import ProviderSimulation
    from backend.provider_lab import build_lab
    path=Path(args.env_file)
    if not path.is_file():parser.error('Dummy configuration file does not exist')
    values=dotenv_values(path)
    allowed={'PROVIDER_LAB_ENVIRONMENT','PROVIDER_LAB_ACCOUNT','PROVIDER_LAB_EVENT_SECRET'}
    if set(values)-allowed:parser.error('Only the three documented dummy lab settings are accepted; do not use .env.local or real keys')
    try:
        service=ProviderSimulation(environment=values.get('PROVIDER_LAB_ENVIRONMENT',''),
            dummy_account=values.get('PROVIDER_LAB_ACCOUNT',''),event_secret=values.get('PROVIDER_LAB_EVENT_SECRET',''))
    except ValueError:parser.error('Use SIMULATED mode and DEMO-prefixed dummy values; real credentials are not supported')
    print(f'SIMULATED Provider Lab: http://127.0.0.1:{args.port}/',flush=True)
    print('No real carriers, insurer, database, wallet or WhatsApp transport. Restart clears dummy data.',flush=True)
    if args.lan:print(f'On your phone, use http://YOUR-LAPTOP-WIFI-IP:{args.port}/ (not 0.0.0.0).',flush=True)
    import uvicorn
    uvicorn.run(build_lab(service),host='0.0.0.0' if args.lan else '127.0.0.1',port=args.port,access_log=False,proxy_headers=False)


if __name__=='__main__':main()
