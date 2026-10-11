"""Private carrier consolidation, tenant-local history and branded public payloads."""
import re
from datetime import datetime,timezone,timedelta
from decimal import Decimal,ROUND_HALF_UP
from uuid import uuid4
import asyncpg

ALIASES={'DHLEXPRESS':'DHL','DHL':'DHL','UNITEDPARCELSERVICE':'UPS','UPS':'UPS','DPD':'DPD','FEDEX':'FEDEX','FEDERALEXPRESS':'FEDEX'}
SERVICE_ALIASES={'EXPRESSWORLDWIDE':'EXPRESSWORLDWIDE','WORLDWIDEEXPRESS':'EXPRESSWORLDWIDE','NEXTDAYAIR':'NEXTDAYAIR','UPS_NEXT_DAY_AIR':'NEXTDAYAIR'}
PRIVATE_KEYS={'provider','aggregator','account_id','carrier_account_id','platform_connection_id','upstream_shipment_id','upstream_rate_id','recommended_provider'}
BRANDS=re.compile(r'(?i)easypost|sendcloud|shiprocket|shippo|localregional')


def carrier_identity(name):
    code=re.sub(r'[^A-Z0-9]','',name.upper())
    return ALIASES.get(code,code)


def service_identity(carrier,service):
    code=re.sub(r'[^A-Z0-9]','',service.upper())
    for prefix in [carrier_identity(carrier),re.sub(r'[^A-Z0-9]','',carrier.upper())]:
        if code.startswith(prefix) and len(code)>len(prefix):code=code[len(prefix):];break
    return SERVICE_ALIASES.get(code,code)


def consolidate_rates(rates):
    """Distinct tiers/currencies remain separate. Tie breaks are stable."""
    winners={}
    def ranking(rate):
        wholesale=Decimal(rate.fee_breakdown['wholesale_total'])
        profit=rate.client_price_ex_tax-wholesale
        if not wholesale.is_finite() or not profit.is_finite():raise ValueError('Invalid price')
        return (-profit,rate.client_price_ex_tax,wholesale,
                rate.delivery_days if rate.delivery_days is not None else 10000,
                str(rate.account_id),rate.upstream_rate_id)
    for rate in rates:
        key=(carrier_identity(rate.carrier_code),service_identity(rate.carrier_code,rate.service_code),rate.currency)
        if key not in winners or ranking(rate)<ranking(winners[key]):winners[key]=rate
    return sorted(winners.values(),key=lambda rate:(rate.client_price_ex_tax,carrier_identity(rate.carrier_code),service_identity(rate.carrier_code,rate.service_code),str(rate.account_id)))


def business_days(start,end):
    """Elapsed weekday date boundaries; public method notes exclude holidays."""
    n=(end.date()-start.date()).days
    weeks,remainder=divmod(n,7)
    return weeks*5+sum((start.weekday()+i)%7<5 for i in range(1,remainder+1))


def summarize_history(rows):
    groups={}
    for row in rows:
        carrier=carrier_identity(row['carrier_code'] or '')
        data=groups.setdefault(carrier,{'transits':[],'eligible':0,'on_time':0,'exceptions':0,'samples':0})
        data['samples']+=1
        if row['status']=='EXCEPTION':data['exceptions']+=1
        start=row['dispatched_at'] or row['booked_at'];end=row['delivered_at']
        if row['status']!='DELIVERED' or not start or not end or end<start:continue
        elapsed=end-start
        seconds=Decimal(elapsed.days*86400+elapsed.seconds)+Decimal(elapsed.microseconds)/Decimal('1000000')
        data['transits'].append(seconds/Decimal('86400'))
        estimate=row.get('delivery_days')
        if estimate is not None and re.fullmatch(r'[0-9]{1,3}',str(estimate)):
            data['eligible']+=1
            if business_days(start,end)<=int(estimate):data['on_time']+=1
    results={}
    for carrier,data in groups.items():
        on_time=(Decimal(data['on_time'])*100/Decimal(data['eligible'])).quantize(Decimal('.1'),rounding=ROUND_HALF_UP) if data['eligible'] else None
        average=(sum(data['transits'],Decimal(0))/len(data['transits'])).quantize(Decimal('.1'),rounding=ROUND_HALF_UP) if data['transits'] else None
        high=data['exceptions']>=3 or (data['eligible']>=10 and on_time is not None and on_time<80)
        medium=data['exceptions']>0 or (data['eligible']>=10 and on_time is not None and on_time<90)
        results[carrier]={'on_time_rate':on_time,'avg_transit_days':average,'route_risk_level':'HIGH_DELAY_ALERT' if high else 'MEDIUM' if medium else 'LOW',
            'history_samples':data['samples'],'delivery_samples':len(data['transits']),'on_time_samples':data['eligible'],
            'active_exceptions':data['exceptions'],'history_status':'RECORDED_HISTORY',
            'on_time_method':'quoted business-day estimate; weekends excluded, holidays not adjusted',
            'transit_method':'elapsed calendar days from dispatch, or booking when dispatch is unavailable'}
    return results


def unknown_history(status='NO_HISTORY'):
    return {'on_time_rate':None,'avg_transit_days':None,'route_risk_level':'LOW','history_samples':0,
            'delivery_samples':0,'on_time_samples':0,'active_exceptions':0,'history_status':status,
            'on_time_method':'No qualified delivery estimate history','transit_method':'No measured deliveries'}


async def route_history(pool,tenant_id,destination):
    if pool is None:return {}
    async with pool.acquire() as connection:
        rows=await connection.fetch("""SELECT carrier_code,status,booked_at,dispatched_at,delivered_at,
                pricing_snapshot->'selected_rate'->>'delivery_days' AS delivery_days
            FROM public.shipments WHERE tenant_id=$1 AND destination_country=$2
            AND COALESCE(delivered_at,last_tracking_event_at,booked_at,created_at)>=now()-interval '90 days'
            AND logistics_metadata->>'synthetic' IS DISTINCT FROM 'true'
            AND NOT (logistics_metadata ? 'fixture_batch') LIMIT 10001""",tenant_id,destination)
    if len(rows)>10000:raise ValueError('History capacity exceeded; no biased sample published')
    return summarize_history(rows)


def public_payload(value,financial=True,key=None):
    """Transport projection only: private booking snapshots remain unchanged."""
    if isinstance(value,list):return [public_payload(item,financial,key) for item in value]
    if isinstance(value,dict):
        result={field:public_payload(item,financial,field) for field,item in value.items() if field not in PRIVATE_KEYS}
        if 'client_price_ex_tax' in result:
            result.setdefault('offer_id',str(uuid4()))
            if not financial:result['fee_breakdown']={'source':'financial_role_required'}
        return result
    if isinstance(value,str) and key in {'carrier_code','service_code','code','detail','notice','error','ai_summary','message','service_name','carrier_name','source','provider_name'} and not value.startswith(('https://','http://')):
        return BRANDS.sub('EasyInvio',value)
    return value
