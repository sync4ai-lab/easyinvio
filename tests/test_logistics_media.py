import base64
from io import BytesIO
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from PIL import Image
from pydantic import SecretStr

from backend.logistics_media import normalize_image,inline_asset,QRMediaService,publish_return_media


def png():
    image=Image.new('RGB',(120,120),'white');output=BytesIO();image.save(output,format='PNG');return output.getvalue()


@pytest.mark.parametrize('raw',[png(),b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120"><rect width="120" height="120" fill="white"/><rect x="20" y="20" width="80" height="80" fill="black"/></svg>'])
def test_real_assets_are_normalized_without_inventing_barcode_data(raw):
    from backend.automation_three_partners import carrier_qr_fields
    result,mime=normalize_image(raw)
    assert mime=='image/png' and Image.open(BytesIO(result)).format=='PNG'
    assert Image.open(BytesIO(result)).size==((120,120) if raw.startswith(b'\x89PNG') else (240,240))
    assert inline_asset({'return_dropoff_qr_code_base64':base64.b64encode(png()).decode()})==png()
    assert inline_asset(carrier_qr_fields(raw))==raw
    assert inline_asset(carrier_qr_fields(base64.b64encode(png()).decode()))==png()


@pytest.mark.parametrize('raw',[b'<svg><image href="https://evil.example/secret"/></svg>',b'<svg><script>bad</script></svg>',b'not an image',b'<svg xmlns="http://www.w3.org/2000/svg" width="100000" height="100000"/>'])
def test_invalid_or_active_assets_are_rejected(raw):
    with pytest.raises((ValueError,OSError)):normalize_image(raw)


@pytest.mark.asyncio
async def test_images_go_to_private_tenant_storage_and_receive_only_read_signed_urls():
    context=SimpleNamespace(tenant_id=uuid4());shipment=uuid4();calls=[]
    connection=SimpleNamespace(fetchval=AsyncMock(return_value=None),execute=AsyncMock())
    class Acquire:
        async def __aenter__(self):return connection
        async def __aexit__(self,*args):pass
    settings=SimpleNamespace(logistics_media_bucket='easyinvio-logistics',supabase_url='https://project.supabase.co',supabase_service_role_key=SecretStr('synthetic-service'))
    async def server(request):
        calls.append(request)
        assert request.headers['authorization']=='Bearer synthetic-service'
        if '/bucket/' in request.url.path:return httpx.Response(200,json={'public':False})
        if '/object/sign/' in request.url.path:
            assert json.loads(request.content)=={'expiresIn':86400}
            return httpx.Response(200,json={'signedURL':request.url.path.removeprefix('/storage/v1')+'?token=synthetic-read-token'})
        assert str(context.tenant_id) in request.url.path and str(shipment) in request.url.path
        assert request.headers['x-upsert']=='false'
        assert request.headers['content-type']=='image/png'
        return httpx.Response(200,json={})
    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
        result=await QRMediaService(SimpleNamespace(acquire=Acquire),settings,client).publish(context,shipment,png(),'https://app.example/view')
    assert '/object/sign/easyinvio-logistics/' in result.media_url and '/public/' not in result.media_url
    assert len(calls)==3 and connection.execute.await_args.args[2:4]==(context.tenant_id,shipment)


@pytest.mark.asyncio
async def test_optional_asset_failure_retains_confirmed_booking_and_safe_view_link():
    from unittest.mock import patch
    result=dict(status='BOOKED',paperless_available=True,shipment_id=str(uuid4()),return_dropoff_qr_code_url='https://app.example/secure-document')
    with patch('backend.automation_three_partners.carrier_document',AsyncMock(side_effect=HTTPException(502,'Document unavailable'))):
        output=await publish_return_media(SimpleNamespace(),SimpleNamespace(),result)
    assert output['status']=='BOOKED' and output['return_dropoff_qr_code_url']==result['return_dropoff_qr_code_url']
    assert output['media_urls']==[] and output['media_status']=='LINK_FALLBACK'
