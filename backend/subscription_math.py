"""Pure UTC period arithmetic. No provider, database, clock or float dependencies."""
from calendar import monthrange
from datetime import datetime,timedelta,timezone
from decimal import Decimal,ROUND_HALF_UP,localcontext
from backend.entitlements import Plan,capabilities

CENT=Decimal('0.01')
DAY=Decimal(86400)

def money(value):
    if isinstance(value,(float,bool)):raise ValueError('Money must use Decimal, integers or decimal strings')
    result=Decimal(value)
    if not result.is_finite():raise ValueError('Non-finite money')
    return result.quantize(CENT,rounding=ROUND_HALF_UP)

def utc(value):
    if not isinstance(value,datetime) or value.tzinfo is None:raise ValueError('Timezone-aware timestamps required')
    return value.astimezone(timezone.utc)

def seconds(delta):
    return Decimal(delta.days*86400+delta.seconds)+Decimal(delta.microseconds)/Decimal(1000000)

def calculate_proration(amount,period_start,period_end,at):
    start,end,at=map(utc,(period_start,period_end,at));amount=money(amount)
    if end<=start or not start<=at<=end or amount<0:raise ValueError('Invalid proration period or amount')
    total=seconds(end-start);remaining=seconds(end-at)
    with localcontext() as ctx:
        ctx.prec=40
        return {'period_start':start.isoformat(),'period_end':end.isoformat(),'effective_at':at.isoformat(),
            'total_seconds':str(total),'remaining_seconds':str(remaining),'total_days':str(total/DAY),
            'remaining_days':str(remaining/DAY),'daily_rate':str(amount*DAY/total),
            'period_price':str(amount),'prorated_amount':str(money(amount*remaining/total))}

def cycle_price(plan,cycle):
    p=capabilities(plan)
    if cycle not in {'MONTHLY','ANNUAL'}:raise ValueError('Unknown billing cycle')
    return money(p.monthly_fee_gbp if cycle=='MONTHLY' else p.annual_monthly_fee_gbp*12)

def add_cycle(anchor,cycle,number=1):
    anchor=utc(anchor)
    if cycle not in {'MONTHLY','ANNUAL'} or type(number) is not int or number<0:raise ValueError('Invalid cycle')
    months=number*(12 if cycle=='ANNUAL' else 1);index=anchor.year*12+anchor.month-1+months
    year,month=divmod(index,12);month+=1
    return anchor.replace(year=year,month=month,day=min(anchor.day,monthrange(year,month)[1]))

def upgrade_breakdown(current,target,cycle,start,end,at):
    if list(Plan).index(Plan(target))<=list(Plan).index(Plan(current)):raise ValueError('Choose a strictly higher tier')
    result=calculate_proration(cycle_price(target,cycle)-cycle_price(current,cycle),start,end,at)
    return {**result,'source_plan':Plan(current).value,'target_plan':Plan(target).value,'billing_cycle':cycle}

def cancellation_breakdown(plan,cycle,period_start,period_end,requested_at):
    start,end,requested=map(utc,(period_start,period_end,requested_at))
    if not start<=requested<end:raise ValueError('Cancellation requires a current paid period')
    if add_cycle(start,cycle)!=end:raise ValueError('Irregular billing periods require reconciliation before notice proration')
    notice_end=requested+timedelta(days=30);amount=Decimal(0);segments=[];n=0
    # Monthly notice may span February and March. Split on real anchored cycle boundaries.
    while (end if n==0 else add_cycle(start,cycle,n+1))<notice_end:
        a=end if n==0 else add_cycle(start,cycle,n+1)
        b=add_cycle(start,cycle,n+2)
        if b<=a:raise ValueError('Paid period does not match a regular billing cycle')
        covered=min(b,notice_end)
        duration=seconds(covered-a);total=seconds(b-a)
        exact=cycle_price(plan,cycle)*duration/total;amount+=exact
        segments.append({'period_start':a.isoformat(),'period_end':b.isoformat(),'covered_until':covered.isoformat(),
            'total_days':str(total/DAY),'uncovered_days':str(duration/DAY),'exact_amount':str(exact)})
        n+=1
    unused=calculate_proration(cycle_price(plan,cycle),start,end,min(notice_end,end))
    return {'requested_at':requested.isoformat(),'cancellation_effective_at':notice_end.isoformat(),
        'paid_period_end':end.isoformat(),'notice_days':30,'uncovered_days':str(max(Decimal(0),seconds(notice_end-end)/DAY)),
        'final_notice_prorated_amount':str(money(amount)),'segments':segments,
        'unused_prepaid_credit_for_review':unused['prorated_amount'],
        'credit_is_automatic':False}

def annual_refund_breakdown(plan,start,end,requested_at,prepaid_net,history=()):
    """Reprice actual use plus notice at monthly retail rates; never keep the annual discount.

    Monthly boundaries retain the original anchor (including Jan 31/leap years).
    Historical tier changes split a month using that month's exact UTC seconds.
    """
    start,end,requested=map(utc,(start,end,requested_at));paid=money(prepaid_net)
    if not start<=requested<end or paid<0:raise ValueError('Invalid annual agreement')
    notice=requested+timedelta(days=30)
    changes=sorted([(utc(at),Plan(tier)) for at,tier in history],key=lambda x:x[0])
    if any(at<start or at>requested for at,_ in changes):raise ValueError('Tier history is outside the paid term')
    def retail_until(stop):
        total=Decimal(0);segments=[];n=0;current=Plan(plan)
        while add_cycle(start,'MONTHLY',n)<stop:
            a=add_cycle(start,'MONTHLY',n);b=add_cycle(start,'MONTHLY',n+1);right=min(b,stop)
            cuts=[a]+[at for at,_ in changes if a<at<right]+[right]
            for left,r in zip(cuts,cuts[1:]):
                active=next((tier for at,tier in reversed(changes) if at<=left),current)
                cost=capabilities(active).monthly_fee_gbp*seconds(r-left)/seconds(b-a)
                total+=cost;segments.append({'start':left.isoformat(),'end':r.isoformat(),'plan':active.value,
                    'monthly_price':str(capabilities(active).monthly_fee_gbp),'cycle_days':str(seconds(b-a)/DAY),
                    'used_days':str(seconds(r-left)/DAY),'exact_cost':str(cost)})
            n+=1
        return money(total),segments
    used,_=retail_until(requested);all_usage,segments=retail_until(notice)
    return {'annual_discount_removed':True,'requested_at':requested.isoformat(),'cancellation_effective_at':notice.isoformat(),
        'verified_annual_prepaid_net':str(paid),'usage_at_monthly_price':str(used),
        'notice_at_monthly_price':str(all_usage-used),'total_repriced_usage_and_notice':str(all_usage),
        'net_refund':str(max(Decimal('0.00'),paid-all_usage)),
        'additional_balance_for_review':str(max(Decimal('0.00'),all_usage-paid)),
        'segments':segments,'notice_days':30,'automatic_additional_debit':False}
