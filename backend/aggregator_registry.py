"""Explicit aggregator capabilities: shared interface, provider-specific wire contracts."""
from dataclasses import dataclass, asdict

@dataclass(frozen=True)
class AggregatorCapabilities:
    code: str
    name: str
    endpoint: str
    rate_lookup: bool
    label_purchase: bool
    order_management: bool = False
    returns: bool = False
    authentication: str = 'API_KEY'
    native_order_sync: bool = False

AGGREGATORS = (
    AggregatorCapabilities('EASYPOST','EasyPost','https://api.easypost.com/v2',True,True,returns=True,native_order_sync=True),
    AggregatorCapabilities('SENDCLOUD_V3','Sendcloud v3','https://panel.sendcloud.sc/api/v3',True,True,order_management=True,returns=True,authentication='BASIC_PUBLIC_SECRET',native_order_sync=True),
    AggregatorCapabilities('SHIPPO','Shippo','https://api.goshippo.com',True,True,order_management=True,returns=True,authentication='SHIPPO_TOKEN',native_order_sync=True),
)

def identify_aggregator(endpoint: str):
    return next((item for item in AGGREGATORS if item.endpoint == endpoint),None)

def public_capabilities():
    return [asdict(item) for item in AGGREGATORS]


def supported_provider_endpoint(endpoint: str) -> bool:
    """Reject retired Sendcloud versions even if a generic origin is approved."""
    from urllib.parse import urlsplit
    parsed = urlsplit(endpoint)
    host = (parsed.hostname or '').lower()
    if host == 'sendcloud.sc' or host.endswith('.sendcloud.sc'):
        return endpoint.rstrip('/') == 'https://panel.sendcloud.sc/api/v3'
    return True
