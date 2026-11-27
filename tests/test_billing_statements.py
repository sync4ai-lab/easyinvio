from datetime import datetime,timezone,timedelta
from decimal import Decimal
from uuid import uuid4
import pytest
from fastapi import HTTPException
from backend.statements import build_snapshot,statement_csv,period_bounds

NOW=datetime(2026,11,1,tzinfo=timezone.utc)
TENANT={'tenant_id':uuid4(),'company_name':'=untrusted <workspace>','is_sandbox':True}

def snapshot(ledger=(),invoices=(),refunds=()):
    return build_snapshot(TENANT,'GBP',NOW,NOW+timedelta(days=30),'0',ledger,[],invoices,[],[],refunds=refunds)

def test_wallet_funding_is_not_revenue_and_shipping_refund_is_not_double_counted():
    rows=[dict(id=1,created_at=NOW,entry_type='TOPUP',balance_delta='100',balance_after='100'),
        dict(id=2,created_at=NOW,entry_type='CAPTURE',balance_delta='-12',balance_after='88',shipment_id=str(uuid4()),shipment_gross='12',shipment_tax='2',carrier_code='TEST',parcel_count=2),
        dict(id=3,created_at=NOW,entry_type='SHIPMENT_REFUND',balance_delta='12',balance_after='100',shipment_id=str(uuid4()),shipment_gross='12',shipment_tax='2',carrier_code='TEST')]
    data=snapshot(rows)
    assert data['total_topups']=='100.00' and data['closing_balance']=='100.00'
    assert data['wallet_breakdown']['Shipping charges (gross)']=='12.00'
    assert data['wallet_breakdown']['Shipping refunds credited']=='12.00'
    assert Decimal(data['gross_total'])==0 and Decimal(data['tax_total'])==0
    assert data['carrier_summary'][0]['parcels']==2 and data['carrier_summary'][0]['refunded_count']==1

def test_stripe_refund_affects_software_total_but_never_wallet():
    invoice=dict(stripe_invoice_id='in_demo',invoice_gross_gbp='345.60',invoice_net_gbp='288',invoice_tax_gbp='57.60',amount_paid_gbp='345.60',created_at=NOW,paid_at=NOW)
    refund=dict(id=uuid4(),settled_at=NOW,net_amount='253.39',tax_amount='50.68',gross_amount='304.07',provider_refund_id='re_demo',stripe_invoice_id='in_demo')
    data=snapshot(invoices=[invoice],refunds=[refund])
    assert Decimal(data['subscription_net'])==Decimal('34.61')
    assert Decimal(data['gross_total'])==Decimal('41.53')
    assert data['closing_balance']=='0.00'
    assert all(r['wallet_delta']=='0.00' for r in data['transactions'])

def test_missing_tax_is_unknown_not_zero_and_broken_wallet_cannot_issue_statement():
    invoice=dict(stripe_invoice_id='in_legacy',invoice_gross_gbp=None,invoice_net_gbp=None,invoice_tax_gbp=None,amount_paid_gbp='29',created_at=NOW,paid_at=NOW)
    data=snapshot(invoices=[invoice]);assert not data['tax_complete'] and data['transactions'][0]['tax_amount'] is None
    with pytest.raises(HTTPException):snapshot([dict(id=1,created_at=NOW,entry_type='TOPUP',balance_delta='100',balance_after='99')])

def test_csv_neutralizes_formulas_and_periods_are_bounded():
    data=snapshot([dict(id=1,created_at=NOW,entry_type='TOPUP',balance_delta='10',balance_after='10',reference='=HYPERLINK("bad")')])
    csv=statement_csv(data).decode('utf-8-sig')
    assert "'=HYPERLINK" in csv
    with pytest.raises(HTTPException):period_bounds(NOW,NOW+timedelta(days=35),now=NOW+timedelta(days=60))
    with pytest.raises(ValueError):period_bounds(NOW.replace(tzinfo=None),NOW,now=NOW)
