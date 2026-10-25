"""Read-only PostgreSQL WhatsApp readiness probe; no app lifespan or messages."""
import asyncio,json
import asyncpg
from main import Settings,database_tls_context

async def run():
 settings=Settings()
 c=await asyncpg.connect(settings.database_url.get_secret_value(),ssl=database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict),timeout=20)
 try:
  async with c.transaction(readonly=True):
   expected=['whatsapp_bindings','whatsapp_routes','whatsapp_inbound_queue','whatsapp_reply_outbox']
   rows=await c.fetch("SELECT relname,relrowsecurity FROM pg_class WHERE relnamespace='public'::regnamespace AND relname=ANY($1::text[])",expected)
   assert {r['relname'] for r in rows}==set(expected),'Required WhatsApp schema missing'
   assert all(r['relrowsecurity'] for r in rows),'Required RLS missing'
   for table in ['whatsapp_inbound_queue','whatsapp_reply_outbox']:
    assert not await c.fetchval('SELECT has_table_privilege($1,$2,$3)','authenticated','public.'+table,'SELECT'),'Private message queue is browser-readable'
   states={}
   for table in ['whatsapp_inbound_queue','whatsapp_reply_outbox']:
    states[table]=[dict(r) for r in await c.fetch('SELECT state,count(*) AS count FROM public.'+table+' GROUP BY state')]
   print(json.dumps({'required_tables_present':True,'rls_enabled':True,'message_queues_private':True,'queue_states':states,'database_writes':0,'provider_calls':0,'messages_sent':0},indent=2))
 finally:await c.close()

if __name__=='__main__':asyncio.run(run())
