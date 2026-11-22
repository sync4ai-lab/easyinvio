"""Offline connector guardrails. No private env, database or provider calls."""
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.cx_connectors import connector_checks


def main() -> None:
    settings = SimpleNamespace(provider_environment='LIVE', tracking_polling_enabled=True,
        integration_royal_mail_enabled=False, integration_evri_enabled=False)
    row = {'id':str(UUID(int=1)), 'api_base_url':'https://panel.sendcloud.sc/api/v3',
        'sendcloud_integration_id':None, 'webhook_enabled':True,
        'webhook_secret_configured':True, 'setup_state':'READY'}
    check=connector_checks(settings,[row],worker_running=True)
    assert not check['ready'] and 'SENDCLOUD_LIVE_INTEGRATION_ID_REQUIRED' in check['issues']
    row['sendcloud_integration_id']=123
    assert connector_checks(settings,[row],worker_running=True)['ready']
    assert not connector_checks(settings,[row],worker_running=False)['ready']
    row['webhook_secret_configured']=False
    assert not connector_checks(settings,[row],worker_running=True)['ready']
    settings.integration_evri_enabled=True
    assert 'EVRI_DIRECT_CONTRACT_NOT_INJECTED' in connector_checks(settings,[row],worker_running=True)['issues']
    assert check['test_label_contracts']==['EASYPOST','SHIPPO']
    assert check['sendcloud_test_label_purchase'].startswith('BLOCKED')
    print('PASS: offline connector guardrails; no live readiness check or external calls performed.')


if __name__=='__main__':
    main()
