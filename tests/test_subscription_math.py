from datetime import datetime,timedelta,timezone
from decimal import Decimal
import pytest
from backend.subscription_math import annual_refund_breakdown,calculate_proration,cancellation_breakdown,upgrade_breakdown,add_cycle,money

def dt(value):return datetime.fromisoformat(value+'T00:00:00+00:00')

def test_annual_cancellation_removes_discount_for_usage_and_notice():
    result=annual_refund_breakdown('VELOCITY',dt('2026-11-09'),dt('2027-11-09'),dt('2026-11-15'),'288')
    assert result['cancellation_effective_at'].startswith('2026-12-15')
    assert result['usage_at_monthly_price']=='5.80'
    assert result['total_repriced_usage_and_notice']=='34.61'
    assert result['net_refund']=='253.39'
    assert result['automatic_additional_debit'] is False

def test_monthly_notice_charges_six_days_in_next_31_day_cycle():
    result=cancellation_breakdown('VELOCITY','MONTHLY',dt('2026-11-09'),dt('2026-12-09'),dt('2026-11-15'))
    assert result['uncovered_days']=='6'
    assert result['final_notice_prorated_amount']=='5.61'

def test_upgrade_prorates_price_difference_not_full_new_plan():
    result=upgrade_breakdown('VELOCITY','COMMAND','MONTHLY',dt('2026-11-09'),dt('2026-12-09'),dt('2026-11-15'))
    assert result['remaining_days']=='24' and result['prorated_amount']=='40.00'
    with pytest.raises(ValueError):upgrade_breakdown('COMMAND','VELOCITY','MONTHLY',dt('2026-11-09'),dt('2026-12-09'),dt('2026-11-15'))

def test_annual_late_cancellation_has_explicit_balance_not_negative_refund():
    result=annual_refund_breakdown('VELOCITY',dt('2026-01-01'),dt('2027-01-01'),dt('2026-12-25'),'288')
    assert result['net_refund']=='0.00'
    assert Decimal(result['additional_balance_for_review'])>0
    assert result['automatic_additional_debit'] is False

def test_previous_refunds_reduce_cash_available():
    r=annual_refund_breakdown('VELOCITY',dt('2026-11-09'),dt('2027-11-09'),dt('2026-11-15'),'100')
    assert r['net_refund']=='65.39'

def test_historical_upgrade_reprices_each_tier_at_its_monthly_price():
    r=annual_refund_breakdown('VELOCITY',dt('2026-11-01'),dt('2027-11-01'),dt('2026-11-16'),'700',[(dt('2026-11-16'),'COMMAND')])
    assert r['usage_at_monthly_price']=='14.50'
    # Remaining November 15/30 * 79 + December 15/31 * 79.
    assert r['total_repriced_usage_and_notice']=='92.23'
    assert r['net_refund']=='607.77'

@pytest.mark.parametrize('anchor,month1,month2',[('2024-01-31','2024-02-29','2024-03-31'),('2025-01-31','2025-02-28','2025-03-31')])
def test_original_month_end_anchor_is_preserved(anchor,month1,month2):
    assert add_cycle(dt(anchor),'MONTHLY',1)==dt(month1)
    assert add_cycle(dt(anchor),'MONTHLY',2)==dt(month2)

def test_money_strictness_and_fractional_seconds():
    assert money('1.005')==Decimal('1.01')
    for invalid in [1.5,True,'NaN','Infinity']:
        with pytest.raises(ValueError):money(invalid)
    a=dt('2026-01-01');r=calculate_proration('10',a,a+timedelta(seconds=3),a+timedelta(seconds=1,microseconds=500000))
    assert r['prorated_amount']=='5.00'
    with pytest.raises(ValueError):calculate_proration('10',a.replace(tzinfo=None),a,a)

def test_month_end_notice_uses_original_anchor_instead_of_february_drift():
    r=cancellation_breakdown('VELOCITY','MONTHLY',dt('2025-01-31'),dt('2025-02-28'),dt('2025-02-20'))
    assert r['segments'][0]['total_days']=='31'
    assert r['final_notice_prorated_amount']=='20.58'

def test_invalid_history_and_periods_rejected():
    with pytest.raises(ValueError):annual_refund_breakdown('VELOCITY',dt('2026-11-01'),dt('2027-11-01'),dt('2026-11-16'),'288',[(dt('2026-12-01'),'COMMAND')])
    with pytest.raises(ValueError):annual_refund_breakdown('VELOCITY',dt('2026-11-01'),dt('2027-11-01'),dt('2026-11-16'),'-1')
