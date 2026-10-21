// Executes real DDL against disposable in-memory PostgreSQL (PGlite), never .env.
// Usage: node --test tests/test_manifest_migrations.cjs
// Set PGLITE_TEST_MODULE to an installed @electric-sql/pglite dist/index.cjs.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { PGlite } = require(process.env.PGLITE_TEST_MODULE || '@electric-sql/pglite');
const root = path.resolve(__dirname, '..');
const ingress = fs.readFileSync(path.join(root, 'migrations/043_whatsapp_async_ingress.sql'), 'utf8');
const manifests = fs.readFileSync(path.join(root, 'migrations/044_carrier_manifests_and_media.sql'), 'utf8');
const actor = '00000000-0000-4000-8000-000000000001';
const tenant = '00000000-0000-4000-8000-000000000002';
const account = '00000000-0000-4000-8000-000000000003';
const shipment = '00000000-0000-4000-8000-000000000004';
const manifest = '00000000-0000-4000-8000-000000000005';
const sha = 'a'.repeat(64);

async function fixture(fn, { enumStatus = false, storage = false, queue = true } = {}) {
  const db = new PGlite();
  try {
    await db.waitReady;
    await db.exec(`
      CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
      CREATE SCHEMA auth;
      CREATE TABLE auth.users(id uuid PRIMARY KEY);
      CREATE TABLE public.tenants(tenant_id uuid PRIMARY KEY);
      CREATE TABLE public.carrier_accounts(id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES public.tenants,
        CONSTRAINT carrier_workspace_unique UNIQUE(tenant_id,id));
      ${enumStatus ? "CREATE TYPE public.shipment_status AS ENUM('BOOKED','DELIVERED');" : ''}
      CREATE TABLE public.shipments(id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES public.tenants,
        carrier_account_id uuid NOT NULL REFERENCES public.carrier_accounts,
        status ${enumStatus ? 'public.shipment_status' : 'text'} NOT NULL DEFAULT 'BOOKED',
        CONSTRAINT shipment_status_allowed CHECK(status IN ('BOOKED','DELIVERED')),
        CONSTRAINT shipment_workspace_unique UNIQUE(tenant_id,id));
      INSERT INTO auth.users VALUES('${actor}'); INSERT INTO public.tenants VALUES('${tenant}');
      INSERT INTO public.carrier_accounts VALUES('${account}','${tenant}');
      INSERT INTO public.shipments VALUES('${shipment}','${tenant}','${account}','BOOKED');
    `);
    if (storage) await db.exec(`
      CREATE SCHEMA storage;
      CREATE TABLE storage.buckets(id text PRIMARY KEY,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);
      CREATE TABLE storage.objects(id uuid PRIMARY KEY,bucket_id text REFERENCES storage.buckets);
      ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;
    `);
    if (queue) {
      await db.exec(ingress);
      await db.exec(`
        INSERT INTO public.whatsapp_inbound_queue
          (message_sid,sender_e164,receiver_e164,input_sha256,payload_ciphertext,key_id)
          VALUES('SM${'1'.repeat(32)}','+447700900123','+447700900124','${sha}',decode('01','hex'),'offline-fixture');
        INSERT INTO public.whatsapp_reply_outbox(inbound_id,part_index,payload_ciphertext,key_id)
          VALUES(1,0,decode('02','hex'),'offline-fixture');
      `);
    }
    await fn(db);
  } finally {
    await db.close();
  }
}

async function preflightFailure(db, pattern) {
  await assert.rejects(db.exec(manifests), error => {
    assert.equal(error.code, '55000');
    assert.match(error.message, pattern);
    assert.ok(error.hint);
    return true;
  });
  await db.exec('ROLLBACK');
  assert.equal((await db.query("SELECT to_regclass('public.carrier_manifests') AS name")).rows[0].name, null);
  const enumValues = await db.query("SELECT enumlabel FROM pg_enum WHERE enumtypid=to_regtype('public.shipment_status')");
  assert.ok(enumValues.rows.every(row => row.enumlabel !== 'MANIFESTED'));
}

test('missing 043 stops before enum commit and names the complete prerequisite migration', async () => {
  await fixture(async db => {
    await preflightFailure(db, /whatsapp_inbound_queue.*whatsapp_reply_outbox/);
  }, { queue: false, enumStatus: true });
});

test('missing only the outbox preserves existing inbound messages and prevents schema changes', async () => {
  await fixture(async db => {
    await db.exec('DROP TABLE public.whatsapp_reply_outbox');
    await preflightFailure(db, /whatsapp_reply_outbox/);
    assert.equal((await db.query('SELECT count(*)::int AS count FROM public.whatsapp_inbound_queue')).rows[0].count, 1);
  }, { enumStatus: true });
});

test('an empty replacement outbox is rejected instead of treated as migration 043', async () => {
  await fixture(async db => {
    await db.exec('DROP TABLE public.whatsapp_reply_outbox; CREATE TABLE public.whatsapp_reply_outbox(id bigint PRIMARY KEY)');
    await preflightFailure(db, /baseline columns.*whatsapp_reply_outbox.inbound_id/);
  });
});

test('incompatible queue columns are detected before enum changes', async () => {
  await fixture(async db => {
    await db.exec('ALTER TABLE public.whatsapp_reply_outbox ALTER COLUMN part_index TYPE bigint');
    await preflightFailure(db, /part_index \(integer\)/);
  }, { enumStatus: true });
});

test('missing tenant composite key fails before foreign-key DDL', async () => {
  await fixture(async db => {
    await db.exec('ALTER TABLE public.carrier_accounts DROP CONSTRAINT carrier_workspace_unique');
    await preflightFailure(db, /unique key on public.carrier_accounts/);
  });
});

test('missing receipt ordering uniqueness is rejected', async () => {
  await fixture(async db => {
    await db.exec('ALTER TABLE public.whatsapp_reply_outbox DROP CONSTRAINT whatsapp_reply_outbox_inbound_id_part_index_key');
    await preflightFailure(db, /unique key on public.whatsapp_reply_outbox/);
  });
});

test('missing inbound foreign key and disabled queue RLS are rejected', async () => {
  await fixture(async db => {
    await db.exec('ALTER TABLE public.whatsapp_reply_outbox DROP CONSTRAINT whatsapp_reply_outbox_inbound_id_fkey');
    await preflightFailure(db, /outbox-to-inbound foreign key/);
  });
  await fixture(async db => {
    await db.exec('ALTER TABLE public.whatsapp_reply_outbox DISABLE ROW LEVEL SECURITY');
    await preflightFailure(db, /row-level security/);
  });
});

async function successfulUpgrade(db, hasStorage) {
  await db.exec(manifests);
  const before = await db.query('SELECT state,payload_ciphertext,fallback_for,delivery_status FROM public.whatsapp_reply_outbox WHERE id=1');
  assert.equal(before.rows[0].state, 'STAGED');
  assert.deepEqual(Array.from(before.rows[0].payload_ciphertext), [2]);
  assert.equal(before.rows[0].fallback_for, null);
  assert.equal(before.rows[0].delivery_status, null);
  await db.exec(`
    INSERT INTO public.carrier_manifests(id,tenant_id,carrier_account_id,carrier_code,status,total_shipments,total_weight_kg,
      created_by,request_id,input_sha256,document_kind,snapshot,environment)
      VALUES('${manifest}','${tenant}','${account}','ROYALMAIL','SUBMITTED',1,1.250,
      '${actor}','${manifest}','${sha}','INTERNAL_HANDOVER','[]','TEST');
    UPDATE public.shipments SET status='MANIFESTED',manifest_id='${manifest}' WHERE id='${shipment}';
    INSERT INTO public.carrier_manifest_events(tenant_id,manifest_id,actor_auth_user_id,event_type)
      VALUES('${tenant}','${manifest}','${actor}','SUBMITTED');
    INSERT INTO public.logistics_media_assets(id,tenant_id,shipment_id,object_key,content_sha256,mime_type)
      VALUES('${manifest}','${tenant}','${shipment}','${tenant}/${shipment}/asset.png','${sha}','image/png');
    INSERT INTO public.whatsapp_reply_outbox(inbound_id,part_index,payload_ciphertext,key_id,fallback_for,delivery_status)
      VALUES(1,1,decode('03','hex'),'offline-fixture',1,'queued');
  `);
  assert.equal((await db.query('SELECT status FROM public.shipments')).rows[0].status, 'MANIFESTED');
  await assert.rejects(db.exec("UPDATE public.shipments SET status='UNSUPPORTED'"), error => ['22P02', '23514'].includes(error.code));
  await assert.rejects(db.exec("UPDATE public.carrier_manifest_events SET detail='{}'"), error => error.code === '42501');
  await assert.rejects(db.exec(`INSERT INTO public.whatsapp_reply_outbox(inbound_id,part_index,payload_ciphertext,key_id,fallback_for)
    VALUES(1,2,decode('04','hex'),'offline-fixture',1)`), error => error.code === '23505');
  await assert.rejects(db.exec(`UPDATE public.carrier_manifests SET status='COMPLETED' WHERE id='${manifest}'`), error => error.code === '23514');
  const guards = await db.query(`SELECT relname,relrowsecurity FROM pg_class
    WHERE oid IN ('public.carrier_manifests'::regclass,'public.carrier_manifest_events'::regclass,'public.logistics_media_assets'::regclass)`);
  assert.equal(guards.rows.length, 3);
  assert.ok(guards.rows.every(row => row.relrowsecurity));
  const permissions = await db.query(`SELECT has_table_privilege('anon','public.carrier_manifests','SELECT') AS browser_read,
    has_table_privilege('authenticated','public.logistics_media_assets','INSERT') AS browser_write,
    has_table_privilege('service_role','public.carrier_manifests','INSERT') AS server_write,
    has_sequence_privilege('service_role','public.carrier_manifest_events_id_seq','USAGE') AS sequence_usage`);
  assert.deepEqual(permissions.rows[0], { browser_read: false, browser_write: false, server_write: true, sequence_usage: true });
  const otherTenant = '00000000-0000-4000-8000-000000000006';
  const otherAccount = '00000000-0000-4000-8000-000000000007';
  const otherManifest = '00000000-0000-4000-8000-000000000008';
  await db.exec(`
    INSERT INTO public.tenants VALUES('${otherTenant}');
    INSERT INTO public.carrier_accounts VALUES('${otherAccount}','${otherTenant}');
    INSERT INTO public.carrier_manifests(id,tenant_id,carrier_account_id,carrier_code,status,total_shipments,total_weight_kg,
      created_by,request_id,input_sha256,document_kind,snapshot,environment)
      VALUES('${otherManifest}','${otherTenant}','${otherAccount}','ROYALMAIL','SUBMITTED',1,1.250,
        '${actor}','${otherManifest}','${sha}','INTERNAL_HANDOVER','[]','TEST');
  `);
  await assert.rejects(db.exec(`UPDATE public.shipments SET manifest_id='${otherManifest}' WHERE id='${shipment}'`),
    error => error.code === '23503');
  await assert.rejects(db.exec(`UPDATE public.shipments SET carrier_account_id='${otherAccount}' WHERE id='${shipment}'`),
    error => error.code === '23503');
  await db.exec('GRANT SELECT,UPDATE ON public.shipments TO authenticated; SET ROLE authenticated');
  try {
    await assert.rejects(db.exec(`UPDATE public.shipments SET manifest_id=NULL WHERE id='${shipment}'`),
      error => error.code === '42501' && /server-owned/.test(error.message));
  } finally {
    await db.exec('RESET ROLE');
  }
  if (hasStorage) {
    assert.equal((await db.query("SELECT public FROM storage.buckets WHERE id='easyinvio-logistics'")).rows[0].public, false);
    const policies = await db.query("SELECT permissive FROM pg_policies WHERE policyname='easyinvio_logistics_server_only'");
    assert.equal(policies.rows[0].permissive, 'RESTRICTIVE');
  }
}

test('043 then 044 upgrades text status, preserves receipts, constraints and private grants', async () => {
  await fixture(db => successfulUpgrade(db, false));
});

test('043 then 044 upgrades enum status across commits and creates private Supabase Storage policies', async () => {
  await fixture(db => successfulUpgrade(db, true), { enumStatus: true, storage: true });
});

test('retry after an earlier enum-only commit is safe without deleting the enum value', async () => {
  await fixture(async db => {
    await db.exec("ALTER TYPE public.shipment_status ADD VALUE 'MANIFESTED'");
    await successfulUpgrade(db, false);
  }, { enumStatus: true });
});
