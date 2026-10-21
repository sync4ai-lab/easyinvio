"""Royal Mail direct provision. An issued, certified API contract is mandatory."""
from __future__ import annotations

from typing import Any

import httpx

from main import CarrierAccount, ProviderFailure, RateStrategy, RatingRequest, WholesaleRate
from backend.automation_freight_engine import PurchaseUncertain
from backend.adapters.direct_contract import DirectCarrierContract, DirectLabel, DirectManifest, DirectParcel, PAFDeliveryAddress
from backend.integration_policy import IntegrationSettings


class RoyalMailStrategy(RateStrategy):
    carrier_code = 'ROYALMAIL'
    policy_code = 'royal_mail'

    def __init__(self, client: httpx.AsyncClient, account: CarrierAccount, *,
                 settings: IntegrationSettings | None = None, contract: DirectCarrierContract | None = None):
        super().__init__(client, account)
        self.settings = settings if settings is not None else IntegrationSettings()
        self.contract = contract

    def verified_contract(self) -> DirectCarrierContract:
        if not getattr(self.settings, f'integration_{self.policy_code}_enabled', False):
            raise ProviderFailure('DIRECT_CARRIER_DISABLED')
        if self.contract is None:
            raise ProviderFailure('DIRECT_CARRIER_CONTRACT_NOT_CONFIGURED')
        return self.contract

    async def rates(self, request: RatingRequest) -> list[WholesaleRate]:
        contract = self.verified_contract()
        parcel = DirectParcel.from_rating(request)
        rates = await contract.quote(request, parcel)
        for rate in rates:
            if (rate.carrier_code != self.carrier_code or rate.account_id != self.account.id
                    or rate.currency != request.currency or rate.provider != 'REGIONAL'):
                raise ProviderFailure('DIRECT_CARRIER_RESPONSE_IDENTITY_MISMATCH')
        return [rate.model_copy(update={'execution_details': {
            **rate.execution_details, 'direct_carrier': self.carrier_code}}) for rate in rates]

    async def purchase_label(self, shipment_data: dict[str, Any]) -> DirectLabel:
        contract = self.verified_contract()
        try:
            PAFDeliveryAddress.model_validate(shipment_data['recipient_paf'])
        except (ValueError, KeyError, TypeError):
            raise ProviderFailure('DIRECT_PAF_RECIPIENT_REQUIRED') from None
        result = await contract.purchase_label(shipment_data)
        try:
            return DirectLabel.model_validate(result)
        except ValueError:
            raise PurchaseUncertain('DIRECT_LABEL_RESPONSE_REQUIRES_RECONCILIATION') from None

    async def create_manifest(self, shipping_account_id: str) -> DirectManifest:
        if not shipping_account_id.strip():
            raise ProviderFailure('DIRECT_SHIPPING_ACCOUNT_REQUIRED')
        result = await self.verified_contract().create_manifest(shipping_account_id)
        try:
            return DirectManifest.model_validate(result)
        except ValueError:
            raise PurchaseUncertain('DIRECT_MANIFEST_RESPONSE_REQUIRES_RECONCILIATION') from None
