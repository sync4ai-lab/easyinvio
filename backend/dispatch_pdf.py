"""Bounded, tenant-authorized print bundles of confirmed carrier PDFs.

Never manufactures a carrier label or renders ZPL as a pretend shipping label.
Only exact operator-approved HTTPS hosts are fetched, without redirects.
"""
from __future__ import annotations

import asyncio
from io import BytesIO
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

import httpx
from fastapi import HTTPException
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


class PrintSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    # JSON array of exact trusted carrier/storage hosts, controlled on server.
    carrier_pdf_hosts: list[str] = Field(default_factory=list)

    @field_validator('carrier_pdf_hosts')
    @classmethod
    def hosts(cls, values):
        import ipaddress
        import re
        for value in values:
            if not re.fullmatch(r'[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?', value) or '.' not in value:
                raise ValueError('Use exact public HTTPS DNS hosts without paths or wildcards')
            try:
                ipaddress.ip_address(value)
            except ValueError:
                if value.endswith(('.localhost', '.local', '.internal')):
                    raise ValueError('Private hosts are prohibited')
            else:
                raise ValueError('IP addresses are prohibited')
        return values


def invoice_pdf(reference, declaration):
    """Print reviewed commercial metadata, not a certified postal form substitute."""
    if not declaration.get('ready_for_provider') or not declaration.get('signer'):
        raise HTTPException(409, 'Reviewed customs declaration required before printing')
    styles = getSampleStyleSheet()
    def paragraph(text, style='BodyText'):
        return Paragraph(escape(str(text or 'Not supplied')), styles[style])
    output = BytesIO()
    story = [paragraph('COMMERCIAL INVOICE', 'Title'), paragraph('Order: ' + reference), Spacer(1, 14)]
    parties = []
    for key in ('sender', 'recipient'):
        party = declaration[key]
        lines = [key.title(), party.get('name'), party.get('line1'), party.get('line2'),
                 ' '.join(str(party.get(k) or '') for k in ('city', 'state', 'postal_code', 'country_code')),
                 'EORI: ' + str(party.get('eori') or 'Not supplied'),
                 'VAT: ' + str(party.get('vat_registration') or 'Not supplied')]
        parties.append([paragraph(line) for line in lines if line])
    table = Table([parties], colWidths=[250, 250])
    table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOX', (0, 0), (-1, -1), .5, colors.grey)]))
    story += [table, Spacer(1, 14), paragraph('Currency: ' + declaration['currency'] + ' | Incoterm: ' + declaration['incoterm']), Spacer(1, 10)]
    goods = [[paragraph(x) for x in ['Description / origin', 'HS code', 'Qty', 'Unit value', 'Total value', 'Net kg']]]
    for item in declaration['items']:
        goods.append([paragraph(item['description'] + ' / ' + item['origin_country']), paragraph(item['hs_code']),
                      paragraph(item['quantity']), paragraph(item['unit_value']), paragraph(item['line_value']), paragraph(item['line_weight_kg'])])
    table = Table(goods, colWidths=[165, 75, 35, 75, 75, 75], repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e2e8f0')),
                              ('GRID', (0, 0), (-1, -1), .4, colors.grey), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                              ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
    story += [table, Spacer(1, 14)]
    totals = declaration['totals']
    story += [paragraph(f"Goods value: {totals['goods_value']} {declaration['currency']} | Net weight: {totals['net_weight_kg']} kg | Gross weight: {totals['gross_weight_kg']} kg"),
              Spacer(1, 12), paragraph(declaration['declaration_statement']), Spacer(1, 12),
              paragraph('Declared by: ' + declaration['signer']),
              paragraph('Signature: ____________________________________   Date: __________________'), Spacer(1, 10),
              paragraph('HS classification and declaration facts were reviewed by the shipper. This page does not replace carrier-issued CN22/CN23 forms.')]
    def footer(canvas, doc):
        canvas.setFont('Helvetica', 8)
        canvas.drawString(42, 24, 'EasyInvio.com | Reviewed commercial declaration | Page ' + str(doc.page))
    SimpleDocTemplate(output, pagesize=A4, leftMargin=42, rightMargin=42, topMargin=36, bottomMargin=42).build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


async def fetch_pdf(client, url, hosts):
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        raise HTTPException(409, 'Invalid carrier document URL') from None
    if (parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or parsed.password
        or port not in (None, 443) or parsed.fragment):
        raise HTTPException(409, 'Carrier PDF host is not approved for server downloads')
    data = bytearray()
    try:
        async with client.stream('GET', url, timeout=30, follow_redirects=False) as response:
            if response.status_code != 200 or response.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/pdf':
                raise HTTPException(502, 'Carrier did not return a PDF document')
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 5_000_000:
                    raise HTTPException(413, 'Carrier document exceeds 5 MB')
    except httpx.HTTPError:
        raise HTTPException(502, 'Carrier PDF download failed; no printing occurred') from None
    if not data.startswith(b'%PDF-'):
        raise HTTPException(502, 'Invalid carrier PDF')
    return bytes(data)


def merge_pdfs(documents):
    writer = PdfWriter()
    page_count = 0
    try:
        for data in documents:
            reader = PdfReader(BytesIO(data), strict=True)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= 100:
                raise ValueError('Invalid document')
            if reader.get_fields():
                raise HTTPException(409, 'Carrier must supply a flattened print PDF; interactive forms cannot be discarded')
            page_count += len(reader.pages)
            if page_count > 1000:
                raise HTTPException(413, 'Print bundle exceeds 1000 pages')
            for page in reader.pages:
                # Avoid active PDF actions/attachments while preserving label geometry.
                for key in ('/AA', '/Annots'):
                    if key in page:
                        del page[key]
                writer.add_page(page)
        output = BytesIO()
        writer.write(output)
        return output.getvalue()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502, 'Carrier PDF could not be safely merged') from None


async def bundle_shipments(rows, *, client=None, hosts=None):
    from backend.dispatch_workspace import decoded
    if not rows:
        raise HTTPException(422, 'Select confirmed bookings')
    hosts = PrintSettings().carrier_pdf_hosts if hosts is None else hosts
    async def build(http):
        documents = []
        total = 0
        for row in rows:
            if (row['status'] not in {'BOOKED', 'IN_TRANSIT', 'DELIVERED', 'EXCEPTION'}
                or not row['booked_at'] or not row['tracking_number'] or not row['label_storage_path']):
                raise HTTPException(409, 'Every selected shipment requires a confirmed carrier label')
            documents.append(await fetch_pdf(http, row['label_storage_path'], hosts))
            metadata = decoded(row['logistics_metadata'])
            declaration = metadata.get('automation_customs')
            forms = metadata.get('automation_label', {}).get('carrier_forms', [])
            if row['customs_required']:
                if not declaration or not declaration.get('ready_for_provider'):
                    raise HTTPException(409, 'Reviewed stored customs declaration is missing')
                if declaration.get('postal_form') and not any(f.get('document_type', '').upper() == declaration['postal_form'] for f in forms):
                    raise HTTPException(409, 'Carrier-issued postal declaration is missing; reconcile carrier forms before printing')
                documents.append(await asyncio.to_thread(invoice_pdf, row['customer_reference'] or str(row['id']), declaration))
            for form in forms:
                documents.append(await fetch_pdf(http, form['url'], hosts))
            total = sum(len(data) for data in documents)
            if total > 50_000_000:
                raise HTTPException(413, 'Print bundle exceeds 50 MB; select fewer orders')
        return await asyncio.to_thread(merge_pdfs, documents)
    if client is not None:
        return await build(client)
    async with httpx.AsyncClient(trust_env=False) as http:
        return await build(http)
