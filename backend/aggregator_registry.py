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

AGGREGATORS = (
    AggregatorCapabilities('EASYPOST','EasyPost','https://api.easypost.com/v2',True,True),
    AggregatorCapabilities('SENDCLOUD_V3','Sendcloud v3','https://panel.sendcloud.sc/api/v3',True,False,authentication='BASIC_PUBLIC_SECRET'),
    AggregatorCapabilities('SENDCLOUD_V2','Sendcloud v2 legacy','https://panel.sendcloud.sc/api/v2',True,False,authentication='BASIC_PUBLIC_SECRET'),
)

def identify_aggregator(endpoint: str):
    return next((item for item in AGGREGATORS if item.endpoint == endpoint),None)

def public_capabilities():
    return [asdict(item) for item in AGGREGATORS]
