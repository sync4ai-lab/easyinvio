"""Shipsurance premium arithmetic and explicit integration readiness.

Paid cover requires Shipsurance's actual partner API contract and UK-origin
policy. No purchase or claims endpoints are inferred from its public website.
"""
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.ai_engine import strict_decimal

PROTECTION_NOTICE = ('Shipment protection is not available for purchase yet. Shipsurance UK-origin coverage, '
                     'partner API access and wholesale pricing must be verified. No protection fee is charged.')
TAX_NOTICE = ('The shipping subtotal excludes VAT. VAT is not assessed or collected by the current checkout. '
              'Applicable carrier taxes, import duties and destination charges may be billed separately. '
              'Protection tax treatment will be shown before protection can be purchased.')


async def calculate_shipsurance_premium(item_declared_value: Decimal) -> dict:
    """Calculate the requested GBP customer price without creating paid coverage."""
    try:
        value = strict_decimal(item_declared_value)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    if value > Decimal('5000.00'):
        raise HTTPException(400, 'EasyInvio Error: Declared cargo value exceeds our maximum system protection liability cap of £5,000 per package.')
    if value <= 0:
        raise HTTPException(400, 'Declared goods value must be greater than zero')
    premium = max((value * Decimal('.01')).quantize(Decimal('.01'), rounding=ROUND_HALF_UP), Decimal('1.20'))
    return {'declared_value': str(value), 'currency': 'GBP', 'premium_estimate': str(premium),
            'maximum_package_value': '5000.00', 'insured': False, 'available': False,
            'wholesale_cost': None, 'profit_margin': None, 'tax_assessed': False,
            'notice': PROTECTION_NOTICE, 'tax_notice': TAX_NOTICE}


def build_router(authenticate):
    from backend.customer_checkout import offer_context, quoted_goods
    router = APIRouter(tags=['Shipment protection readiness'])

    @router.get('/api/v1/shipping/protection-quote')
    async def protection_quote(offer_id: UUID, request: Request, context=Depends(authenticate)):
        row, quote, quoted, rate, reference, required = await offer_context(request.app.state.partner_lifecycle, context, offer_id)
        items = quoted_goods(quote)
        if not items or (quote.goods_currency or quote.currency) != 'GBP':
            return {'available': False, 'insured': False, 'premium_estimate': None,
                    'notice': PROTECTION_NOTICE, 'tax_notice': TAX_NOTICE}
        value = sum((strict_decimal(item['unit_value']) * int(item['quantity']) for item in items), Decimal(0))
        try:
            return await calculate_shipsurance_premium(value)
        except HTTPException as exc:
            # Optional protection availability must never block an unprotected quote.
            return {'available': False, 'insured': False, 'premium_estimate': None,
                    'notice': str(exc.detail), 'tax_notice': TAX_NOTICE}

    return router
