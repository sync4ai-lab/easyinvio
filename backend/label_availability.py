"""Known purchase gates checked before payment; live carrier acceptance is separate."""
from fastapi import HTTPException


def label_availability(settings, rate):
    endpoint = (rate.execution_details.get('account_endpoint') or '').rstrip('/')
    environment = getattr(settings, 'provider_environment', 'LIVE')
    if environment == 'TEST' and endpoint and endpoint not in {
            'https://api.easypost.com/v2', 'https://api.goshippo.com', 'https://api.goshippo.com/v1'}:
        return False, 'Quote only: this test connection cannot issue shipping labels. Choose a bookable service or contact support.'
    if environment == 'LIVE' and not getattr(settings, 'automation_purchase_enabled', True):
        return False, 'Label purchasing is not enabled for this workspace. Contact EasyInvio support before paying.'
    return True, ''


def require_label_purchase(settings, rate):
    available, notice = label_availability(settings, rate)
    if not available:
        raise HTTPException(409, notice + ' No label purchase was initiated.')
