"""Normalize real carrier assets and publish read-only, tenant-scoped signed images."""
from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import datetime,timedelta,timezone
from io import BytesIO
import re
from typing import TYPE_CHECKING
from urllib.parse import quote, urlsplit
from uuid import UUID, uuid4

import asyncpg
import httpx
from defusedxml.ElementTree import fromstring
from fastapi import HTTPException
from PIL import Image
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from main import Settings, TenantContext


class PublishedMedia(BaseModel):
    model_config = ConfigDict(extra='forbid')
    media_url: str
    view_url: str
    mime_type: str
    expires_in: int = 86400


def normalize_image(raw: bytes) -> tuple[bytes, str]:
    """No network references/scripts in SVG, bounded raster size, no invented barcode."""
    if not raw or len(raw)>5_000_000:
        raise ValueError('Carrier image exceeds media limit')
    if raw.lstrip().startswith((b'<svg',b'<?xml')):
        if b'<!DOCTYPE' in raw.upper():raise ValueError('SVG document types are not accepted')
        root=fromstring(raw)
        if root.tag.rsplit('}',1)[-1]!='svg':raise ValueError('Expected SVG')
        nodes=list(root.iter())
        if len(nodes)>50000:raise ValueError('SVG complexity limit')
        allowed={'svg','g','rect','path','polygon','polyline','line','circle','ellipse','text','tspan','defs','clipPath','title','desc'}
        for node in nodes:
            if node.tag.rsplit('}',1)[-1] not in allowed:raise ValueError('Unsupported active SVG')
            for key,value in node.attrib.items():
                if key.rsplit('}',1)[-1].lower().startswith(('on','href')) or re.search(r'url\s*\(|https?:|file:|data:',value,re.I):
                    raise ValueError('External SVG reference')
        kind='svg'
    elif raw.startswith(b'%PDF-'):
        kind='pdf'
    else:
        kind=None
    if kind:
        import pymupdf
        with pymupdf.open(stream=raw,filetype=kind) as document:
            if document.page_count!=1:raise ValueError('A single carrier drop-off page is required')
            page=document[0]
            if page.rect.width<=0 or page.rect.height<=0 or page.rect.width*page.rect.height>3_000_000:
                raise ValueError('Carrier page dimensions exceed limit')
            raw=page.get_pixmap(matrix=pymupdf.Matrix(2,2),alpha=False).tobytes('png')
    with Image.open(BytesIO(raw)) as image:
        if image.format not in {'PNG','JPEG'} or image.width*image.height>12_000_000 or getattr(image,'n_frames',1)!=1:
            raise ValueError('Expected a bounded PNG/JPEG image')
        image.load()
        # Strip metadata and composite transparency onto a white paper background.
        result=Image.new('RGB',image.size,'white')
        if image.mode=='RGBA':result.paste(image,mask=image.getchannel('A'))
        else:result.paste(image.convert('RGB'))
        output=BytesIO();result.save(output,format='PNG')
    if len(output.getvalue())>5_000_000:raise ValueError('Rasterized image exceeds media limit')
    return output.getvalue(),'image/png'


def inline_asset(label: dict) -> bytes | None:
    if label.get('return_dropoff_qr_code_svg'):
        return label['return_dropoff_qr_code_svg'].encode('utf-8')
    value=label.get('return_dropoff_qr_code_base64')
    if value:
        if not isinstance(value,str) or len(value)>7_000_000:raise ValueError('Invalid encoded carrier image')
        if value.startswith('data:'):
            header,value=value.split(',',1)
            if header not in {'data:image/png;base64','data:image/jpeg;base64','data:image/svg+xml;base64'}:
                raise ValueError('Unsupported carrier data URI')
        return base64.b64decode(value,validate=True)
    return None


class QRMediaService:
    def __init__(self,pool: asyncpg.Pool,settings: Settings,client: httpx.AsyncClient):
        self.pool,self.settings,self.client=pool,settings,client

    async def publish(self,context: TenantContext,shipment_id: UUID,raw: bytes,view_url: str) -> PublishedMedia:
        image,mime=await asyncio.to_thread(normalize_image,raw)
        digest=hashlib.sha256(image).hexdigest()
        bucket=self.settings.logistics_media_bucket
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,62}',bucket):raise ValueError('Private media bucket is not configured')
        prefix=self.settings.supabase_url.rstrip('/')+'/storage/v1'
        headers={'Authorization':'Bearer '+self.settings.supabase_service_role_key.get_secret_value(),
                 'apikey':self.settings.supabase_service_role_key.get_secret_value()}
        # Refuse an accidentally public bucket. A signed URL does not privatize public objects.
        bucket_response=await self.client.get(prefix+'/bucket/'+bucket,headers=headers,timeout=10,follow_redirects=False)
        if bucket_response.status_code!=200 or bucket_response.json().get('public') is not False:
            raise HTTPException(503,'A private logistics media bucket is required')
        key=f'{context.tenant_id}/{shipment_id}/{digest}.png'
        async with self.pool.acquire() as connection:
            exists=await connection.fetchval('SELECT id FROM public.logistics_media_assets WHERE tenant_id=$1 AND shipment_id=$2 AND content_sha256=$3',context.tenant_id,shipment_id,digest)
        if exists is None:
            uploaded=await self.client.post(prefix+'/object/'+bucket+'/'+key,headers=headers|{'Content-Type':mime,'x-upsert':'false'},content=image,timeout=15,follow_redirects=False)
            if uploaded.status_code not in {200,201,409}:
                # Supabase may return a 400 resource-already-exists envelope.
                if uploaded.status_code!=400 or str(uploaded.json().get('statusCode'))!='409':
                    raise HTTPException(503,'Carrier image storage unavailable')
            async with self.pool.acquire() as connection:
                await connection.execute('''INSERT INTO public.logistics_media_assets
                  (id,tenant_id,shipment_id,object_key,content_sha256,mime_type) VALUES($1,$2,$3,$4,$5,$6)
                  ON CONFLICT(tenant_id,shipment_id,content_sha256) DO NOTHING''',uuid4(),context.tenant_id,shipment_id,key,digest,mime)
        signed=await self.client.post(prefix+'/object/sign/'+bucket+'/'+key,headers=headers,json={'expiresIn':86400},timeout=10,follow_redirects=False)
        if signed.status_code!=200:raise HTTPException(503,'Carrier image signing unavailable')
        value=signed.json().get('signedURL') or signed.json().get('signedUrl')
        if not isinstance(value,str):raise ValueError('Invalid signed image link')
        url=prefix+value if value.startswith('/object/sign/') else value
        parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.netloc!=urlsplit(prefix).netloc or parsed.path!='/storage/v1/object/sign/'+bucket+'/'+key or not parsed.query or parsed.fragment:
            raise ValueError('Invalid signed image origin/path')
        return PublishedMedia(media_url=url,view_url=view_url,mime_type=mime)


async def publish_return_media(lifecycle,context,result: dict) -> dict:
    """Optional delivery enhancement cannot change a confirmed booking outcome."""
    if result.get('status')!='BOOKED' or not result.get('paperless_available'):return result
    try:
        if result.get('media_urls') and datetime.fromisoformat(result.get('media_expires_at',''))>datetime.now(timezone.utc)+timedelta(minutes=5):
            return result
        from backend.automation_three_partners import carrier_document
        document=await carrier_document(UUID(str(result['shipment_id'])),'return-qr',lifecycle,context)
        service=QRMediaService(lifecycle.pool,lifecycle.automation.settings,lifecycle.client)
        published=await service.publish(context,UUID(str(result['shipment_id'])),document.body,result['return_dropoff_qr_code_url'])
        return result|{'media_urls':[published.media_url],'media_view_url':published.view_url,
                      'media_expires_in':published.expires_in,'media_expires_at':(datetime.now(timezone.utc)+timedelta(seconds=published.expires_in)).isoformat(),'media_status':'READY'}
    except Exception:
        import logging
        logging.getLogger(__name__).warning('Carrier media publication unavailable; confirmed label and viewing link retained')
        return result|{'media_urls':[],'media_status':'LINK_FALLBACK'}
