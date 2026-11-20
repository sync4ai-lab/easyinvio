"""Synthetic statement export/render QA; never reads configuration or customer data."""
from pathlib import Path
import io,json,sys
from datetime import datetime,timedelta,timezone
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.statements import build_snapshot,statement_pdf,statement_csv

def main():
    import fitz
    from pypdf import PdfReader
    out=ROOT/'output/subscription-qa/billing';out.mkdir(parents=True,exist_ok=True)
    start=datetime(2026,10,1,tzinfo=timezone.utc);balance=1000
    ledger=[dict(id=1,created_at=start,entry_type='TOPUP',balance_delta='1000',balance_after='1000',reference='Synthetic top-up')]
    for n in range(1,61):
        balance-=12
        ledger.append(dict(id=n+1,created_at=start+timedelta(hours=n),entry_type='CAPTURE',balance_delta='-12',balance_after=str(balance),
            shipment_id=str(uuid4()),shipment_gross='12',shipment_tax='2',carrier_code=['TEST ROYAL MAIL','TEST EVRI','TEST DPD'][n%3],
            tracking_number='ILLUSTRATIVE-'+str(n),parcel_count=1,route='GBR to GBR',reference='DEMO-ORDER-'+str(n)))
    data=build_snapshot({'tenant_id':uuid4(),'company_name':'Synthetic EasyInvio QA workspace','is_sandbox':True},'GBP',start,start+timedelta(days=31),'0',ledger,[],[],[],[],reference='EI-202610-SYNTHETIC')
    raw=statement_pdf(data);(out/'statement.pdf').write_bytes(raw);(out/'statement.csv').write_bytes(statement_csv(data))
    reader=PdfReader(io.BytesIO(raw));assert len(reader.pages)>=3
    text='\n'.join(page.extract_text() for page in reader.pages)
    assert 'Synthetic EasyInvio' in text and 'DEMO-ORDER-60' in text
    pdf=fitz.open(stream=raw,filetype='pdf')
    for n,page in enumerate(pdf):page.get_pixmap(matrix=fitz.Matrix(1.2,1.2)).save(out/f'page-{n+1}.png')
    (out/'report.json').write_text(json.dumps({'passed':True,'pages':len(reader.pages),'transactions':61,'closing_balance':data['closing_balance']},indent=2))
    print(json.dumps({'pages':len(reader.pages),'closing_balance':data['closing_balance']}))
if __name__=='__main__':main()
