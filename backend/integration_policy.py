"""Server-owned switches for new provider work; historical reads remain available."""
from typing import Any
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.aggregator_registry import identify_aggregator


class IntegrationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', hide_input_in_errors=True)

    integration_easypost_enabled: bool = True
    integration_sendcloud_enabled: bool = True
    integration_shippo_enabled: bool = True
    integration_regional_enabled: bool = True
    integration_royal_mail_enabled: bool = False
    integration_evri_enabled: bool = False


def integration_code(endpoint: str) -> str:
    host = (urlsplit(endpoint).hostname or '').lower()
    for domain, code in (('royalmail.net', 'royal_mail'), ('evri.com', 'evri')):
        if host == domain or host.endswith('.' + domain):
            return code
    if endpoint.rstrip('/') == 'https://api.goshippo.com/v1':
        return 'shippo'
    known = identify_aggregator(endpoint.rstrip('/'))
    if known:
        return 'sendcloud' if known.code.startswith('SENDCLOUD') else known.code.lower()
    # Direct endpoints are registered in code only after the issued contract is implemented.
    from backend.adapters import direct_registration
    registration = direct_registration(endpoint)
    return registration.code if registration else 'regional'


def integration_enabled(endpoint: str, settings: Any = None) -> bool:
    policy = settings if settings is not None else IntegrationSettings()
    code = integration_code(endpoint)
    default = code not in {'royal_mail', 'evri'}
    return bool(getattr(policy, f'integration_{code}_enabled', default))


def require_integration(endpoint: str, settings: Any = None) -> None:
    from backend.automation_freight_engine import PurchaseRejected
    if not integration_enabled(endpoint, settings):
        raise PurchaseRejected('PROVIDER_DISABLED_REQUOTE_REQUIRED')
