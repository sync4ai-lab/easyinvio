"""Single source of truth for channel identities and implemented capabilities."""
from typing import Literal
from pydantic import BaseModel, ConfigDict

PlatformCode = Literal['SHOPIFY','WOOCOMMERCE','AMAZON','CUSTOM_WEBSITE','EBAY','ETSY',
    'TIKTOK_SHOP','BIGCOMMERCE','WIX','SQUARESPACE','MAGENTO','PRESTASHOP','SHOPWARE',
    'ECWID','SQUARE','WEEBLY','OPENCART','ONBUY','MANOMANO','MIRAKL','KAUFLAND',
    'LINNWORKS','CHANNELENGINE','CSV_SFTP']
OrderPlatform = Literal['SHOPIFY','WOOCOMMERCE','AMAZON','CUSTOM_WEBSITE','EBAY','ETSY',
    'TIKTOK_SHOP','BIGCOMMERCE','WIX','SQUARESPACE','MAGENTO','PRESTASHOP','SHOPWARE',
    'ECWID','SQUARE','WEEBLY','OPENCART','ONBUY','MANOMANO','MIRAKL','KAUFLAND',
    'LINNWORKS','CHANNELENGINE','CSV_SFTP','MANUAL']
REST_PLATFORMS = frozenset({'WOOCOMMERCE','EBAY','BIGCOMMERCE','WIX','MAGENTO'})
NATIVE = frozenset({'SHOPIFY','AMAZON',*REST_PLATFORMS})

class PlatformCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    code: PlatformCode
    name: str
    category: Literal['Custom Website & API','Marketplaces','Hosted Carts','Enterprise']
    order_webhooks: bool = True
    order_polling: bool = False
    tracking_writeback: bool = True
    checkout_rates: bool = True
    hosted_returns: bool = True
    setup_mode: Literal['SELF_SERVE','API_BRIDGE','ASSISTED']
    intake: str

_names = [('SHOPIFY','Shopify'),('WOOCOMMERCE','WooCommerce'),('AMAZON','Amazon'),
    ('CUSTOM_WEBSITE','Custom Website / REST API'),('EBAY','eBay'),('ETSY','Etsy'),
    ('TIKTOK_SHOP','TikTok Shop'),('BIGCOMMERCE','BigCommerce'),('WIX','Wix'),
    ('SQUARESPACE','Squarespace'),('MAGENTO','Magento / Adobe Commerce'),
    ('PRESTASHOP','PrestaShop'),('SHOPWARE','Shopware'),('ECWID','Ecwid'),('SQUARE','Square'),
    ('WEEBLY','Weebly'),('OPENCART','OpenCart'),('ONBUY','OnBuy'),('MANOMANO','ManoMano'),
    ('MIRAKL','Mirakl'),('KAUFLAND','Kaufland'),('LINNWORKS','Linnworks'),
    ('CHANNELENGINE','ChannelEngine'),('CSV_SFTP','CSV / SFTP Batch')]

PLATFORMS = {code: PlatformCapabilities(code=code, name=name,
    category=('Custom Website & API' if code=='CUSTOM_WEBSITE' else
        'Marketplaces' if code in {'AMAZON','EBAY','ETSY','TIKTOK_SHOP','ONBUY','MANOMANO','KAUFLAND'} else
        'Enterprise' if code in {'MIRAKL','LINNWORKS','CHANNELENGINE','CSV_SFTP'} else 'Hosted Carts'),
    order_polling=code in REST_PLATFORMS or code=='SHOPIFY',
    tracking_writeback=code!='AMAZON',
    setup_mode='SELF_SERVE' if code in NATIVE or code=='CUSTOM_WEBSITE' else 'API_BRIDGE',
    intake=('Native signed notifications / API retrieval' if code in {'SHOPIFY','AMAZON','WOOCOMMERCE'} else
        'Authenticated REST retrieval; signed normalized bridge notifications' if code in REST_PLATFORMS else
        'Signed normalized API bridge; external middleware required' if code!='CUSTOM_WEBSITE' else 'Signed REST API'),
    ) for code,name in _names}
