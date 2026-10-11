"""Backward-compatible imports for the explicit three-provider engine."""
from backend.automation_three_partners import (
    ADAPTERS, BaseAggregatorAdapter, EasyPostAdapter, SendcloudAdapter, ShippoAdapter,
    NativeRateStrategy, ShippoRateStrategy, FactoryPurchaseBridge, PartnerLifecycleService,
    BookingRequest, VoidRequest, ReturnRequest, authorize, build_router, create_adapter,
    declaration, identifier, return_snapshot, secure_link, verify_quote_connection,
)
