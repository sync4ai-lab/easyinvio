-- Private insurance support evidence and reconciled booking receipts.
-- No policy purchases, claims submissions, wallet credits or messages.
BEGIN;
SET LOCAL lock_timeout='10s';
CREATE TABLE IF NOT EXISTS public.insurance_purchases (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL,shipment_id uuid NOT NULL,offer_id uuid NOT NULL,
 declared_value numeric(12,2) NOT NULL CHECK(declared_value>0 AND declared_value<=5000),
 premium numeric(12,2),tax_amount numeric(12,2),total_charge numeric(12,2),reported_commission numeric(12,2),
 package_id text,quote_id uuid,terms_url text,
 state text NOT NULL CHECK(state IN ('QUOTE_PENDING','QUOTED','RESERVED','POLICY_SUBMITTED','INSURED','FAILED','RECONCILIATION_REQUIRED')),
 requested_by uuid NOT NULL REFERENCES auth.users(id),expires_at timestamptz NOT NULL,
 terms_accepted_at timestamptz,terms_accepted_by uuid REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,id),UNIQUE(tenant_id,shipment_id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id),
 CHECK(state IN ('QUOTE_PENDING','RECONCILIATION_REQUIRED') OR
  (premium IS NOT NULL AND tax_amount IS NOT NULL AND total_charge IS NOT NULL AND
  premium>=1.20 AND tax_amount>=0 AND total_charge=premium+tax_amount AND package_id IS NOT NULL AND quote_id IS NOT NULL AND terms_url IS NOT NULL)),
 CHECK(reported_commission IS NULL OR (reported_commission>=0 AND reported_commission<=premium))
);
CREATE INDEX IF NOT EXISTS insurance_pending_policy ON public.insurance_purchases(updated_at) WHERE state IN ('RESERVED','POLICY_SUBMITTED');
ALTER TABLE public.wallet_ledger ADD COLUMN IF NOT EXISTS insurance_purchase_id uuid;
ALTER TABLE public.wallet_ledger ADD COLUMN IF NOT EXISTS insurance_reported_commission numeric(12,2) CHECK(insurance_reported_commission>=0);
ALTER TABLE public.wallet_ledger ADD COLUMN IF NOT EXISTS insurance_estimated_baseline_cost numeric(12,2) CHECK(insurance_estimated_baseline_cost>=0);
ALTER TABLE public.wallet_ledger ADD COLUMN IF NOT EXISTS insurance_estimated_margin numeric(12,2) CHECK(insurance_estimated_margin>=0);
DO $$ DECLARE expression text; BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.wallet_ledger'::regclass AND conname='wallet_insurance_purchase_fk') THEN
  ALTER TABLE public.wallet_ledger ADD CONSTRAINT wallet_insurance_purchase_fk FOREIGN KEY(tenant_id,insurance_purchase_id) REFERENCES public.insurance_purchases(tenant_id,id);
 END IF;
 SELECT pg_get_expr(conbin,conrelid) INTO expression FROM pg_constraint
 WHERE conrelid='public.wallet_ledger'::regclass AND conname='wallet_ledger_entry_check';
 IF expression IS NULL THEN RAISE EXCEPTION 'Expected wallet ledger validation is missing'; END IF;
 IF position('INSURANCE_CAPTURE' in expression)=0 THEN
  ALTER TABLE public.wallet_ledger DROP CONSTRAINT wallet_ledger_entry_check;
  EXECUTE format('ALTER TABLE public.wallet_ledger ADD CONSTRAINT wallet_ledger_entry_check CHECK ((%s) OR (
   insurance_purchase_id IS NOT NULL AND reservation_id IS NULL AND topup_id IS NULL AND stripe_session_id IS NULL
   AND stripe_event_id IS NULL AND stripe_payment_intent_id IS NULL AND currency=''GBP'' AND
   ((entry_type=''INSURANCE_RESERVE'' AND balance_delta=0 AND reserved_delta>0)
    OR (entry_type=''INSURANCE_CAPTURE'' AND balance_delta<0 AND reserved_delta=balance_delta)
    OR (entry_type=''INSURANCE_RELEASE'' AND balance_delta=0 AND reserved_delta<0))))',expression);
 END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS wallet_insurance_entry_once ON public.wallet_ledger(tenant_id,insurance_purchase_id,entry_type) WHERE insurance_purchase_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS public.insurance_claim_cases (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, shipment_id uuid NOT NULL,
 policy_id text NOT NULL CHECK(length(policy_id) BETWEEN 1 AND 150),
 reason text NOT NULL CHECK(reason IN ('PARCEL_LOST','PARCEL_DAMAGED')),
 state text NOT NULL DEFAULT 'CLAIM_INGESTED' CHECK(state IN ('CLAIM_INGESTED','SUBMISSION_PENDING','SUBMISSION_SUBMITTED','INSURER_SUBMITTED','UNDER_INSURER_REVIEW','ACTION_REQUIRED','DECLINED','CLOSED','INSURER_PAYMENT_REPORTED','RECONCILIATION_REQUIRED','REFUND_APPROVED_AND_CREDITED')),
 submission_payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(submission_payload)='object'),
 upstream_claim_id uuid,upstream_claim_reference text,insurer_status text,last_error_code text,
 updated_at timestamptz NOT NULL DEFAULT now(),
 notes text NOT NULL CHECK(length(notes) BETWEEN 10 AND 2000),
 created_by uuid NOT NULL REFERENCES auth.users(id),
 payload_sha256 text NOT NULL CHECK(payload_sha256 ~ '^[a-f0-9]{64}$'),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(tenant_id,id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
CREATE INDEX IF NOT EXISTS insurance_cases_workspace ON public.insurance_claim_cases(tenant_id,created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS xclaim_remote_case_once ON public.insurance_claim_cases(upstream_claim_id) WHERE upstream_claim_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS xclaim_remote_reference_once ON public.insurance_claim_cases(upstream_claim_reference) WHERE upstream_claim_reference IS NOT NULL;
CREATE INDEX IF NOT EXISTS xclaim_pending_case ON public.insurance_claim_cases(updated_at) WHERE state IN ('SUBMISSION_PENDING','SUBMISSION_SUBMITTED','INSURER_SUBMITTED','UNDER_INSURER_REVIEW','INSURER_PAYMENT_REPORTED');
CREATE TABLE IF NOT EXISTS public.insurance_settlements (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL,case_id uuid NOT NULL,shipment_id uuid NOT NULL,
 approved_amount numeric(12,2) NOT NULL CHECK(approved_amount>0 AND approved_amount<=5000),
 currency text NOT NULL CHECK(currency='GBP'),insurer_payment_reference text NOT NULL UNIQUE CHECK(length(insurer_payment_reference) BETWEEN 5 AND 150),
 received_at timestamptz NOT NULL,verified_by uuid REFERENCES auth.users(id),
 verification_source text NOT NULL DEFAULT 'PLATFORM_OPERATOR' CHECK(verification_source IN ('PLATFORM_OPERATOR','XCLAIM_API')),
 provider_response_sha256 text,
 created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(tenant_id,id),UNIQUE(tenant_id,case_id),
 FOREIGN KEY(tenant_id,case_id) REFERENCES public.insurance_claim_cases(tenant_id,id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id),
 CHECK((verification_source='PLATFORM_OPERATOR' AND verified_by IS NOT NULL)
  OR (verification_source='XCLAIM_API' AND provider_response_sha256 ~ '^[a-f0-9]{64}$' AND provider_response_sha256 IS NOT NULL))
);
ALTER TABLE public.wallet_ledger ADD COLUMN IF NOT EXISTS insurance_settlement_id uuid;
DO $$ DECLARE expression text; BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.wallet_ledger'::regclass AND conname='wallet_insurance_settlement_fk') THEN
  ALTER TABLE public.wallet_ledger ADD CONSTRAINT wallet_insurance_settlement_fk FOREIGN KEY(tenant_id,insurance_settlement_id) REFERENCES public.insurance_settlements(tenant_id,id);
 END IF;
 SELECT pg_get_expr(conbin,conrelid) INTO expression FROM pg_constraint WHERE conrelid='public.wallet_ledger'::regclass AND conname='wallet_ledger_entry_check';
 IF position('INSURANCE_CLAIM_CREDIT' in expression)=0 THEN
  ALTER TABLE public.wallet_ledger DROP CONSTRAINT wallet_ledger_entry_check;
  EXECUTE format('ALTER TABLE public.wallet_ledger ADD CONSTRAINT wallet_ledger_entry_check CHECK ((%s) OR
   (entry_type=''INSURANCE_CLAIM_CREDIT'' AND insurance_settlement_id IS NOT NULL AND insurance_purchase_id IS NULL
    AND currency=''GBP'' AND balance_delta>0 AND reserved_delta=0 AND reservation_id IS NULL AND topup_id IS NULL
    AND stripe_session_id IS NULL AND stripe_event_id IS NULL AND stripe_payment_intent_id IS NULL))',expression);
 END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS wallet_insurance_settlement_once ON public.wallet_ledger(tenant_id,insurance_settlement_id) WHERE insurance_settlement_id IS NOT NULL;
ALTER TABLE public.support_message_outbox ADD COLUMN IF NOT EXISTS message_kind text NOT NULL DEFAULT 'CARRIER_EXCEPTION' CHECK(message_kind IN ('CARRIER_EXCEPTION','INSURANCE_SETTLEMENT'));
CREATE TABLE IF NOT EXISTS public.insurance_claim_evidence (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, case_id uuid NOT NULL,
 content_type text NOT NULL CHECK(content_type IN ('image/jpeg','image/png')),
 content_sha256 text NOT NULL CHECK(content_sha256 ~ '^[a-f0-9]{64}$'),
 content bytea NOT NULL CHECK(octet_length(content) BETWEEN 1 AND 5000000),
 upstream_file_id uuid,upload_state text NOT NULL DEFAULT 'PENDING' CHECK(upload_state IN ('PENDING','SUBMITTED','CONFIRMED')),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,case_id) REFERENCES public.insurance_claim_cases(tenant_id,id)
);
CREATE INDEX IF NOT EXISTS insurance_evidence_case ON public.insurance_claim_evidence(tenant_id,case_id);
CREATE TABLE IF NOT EXISTS public.xclaim_webhook_receipts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL,case_id uuid NOT NULL,
 body_sha256 text NOT NULL CHECK(body_sha256 ~ '^[a-f0-9]{64}$'),
 event text NOT NULL CHECK(event IN ('claim.status-update','claim.status-category-update','claim.deleted')),
 created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(tenant_id,body_sha256),
 FOREIGN KEY(tenant_id,case_id) REFERENCES public.insurance_claim_cases(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS public.insurance_webhook_receipts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, shipment_id uuid NOT NULL,
 policy_id text NOT NULL CHECK(length(policy_id) BETWEEN 1 AND 150),
 body_sha256 text NOT NULL CHECK(body_sha256 ~ '^[a-f0-9]{64}$'),
 event text NOT NULL CHECK(event IN ('BOOKING_CREATED','BOOKING_UPDATED','BOOKING_CANCELLED')),
 verified_status text NOT NULL CHECK(verified_status IN ('CONFIRMED','CANCELLED')),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(tenant_id,body_sha256),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
ALTER TABLE public.support_tickets ADD COLUMN IF NOT EXISTS insurance_claim_id uuid;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.support_tickets'::regclass AND conname='support_insurance_case_fk') THEN
  ALTER TABLE public.support_tickets ADD CONSTRAINT support_insurance_case_fk
   FOREIGN KEY(tenant_id,insurance_claim_id) REFERENCES public.insurance_claim_cases(tenant_id,id);
 END IF;
END $$;
ALTER TABLE public.support_tickets DROP CONSTRAINT IF EXISTS support_ticket_source;
ALTER TABLE public.support_tickets ADD CONSTRAINT support_ticket_source CHECK(
 (tracking_event_id IS NOT NULL AND automation_failure_id IS NULL AND insurance_claim_id IS NULL AND shipment_id IS NOT NULL)
 OR (tracking_event_id IS NULL AND automation_failure_id IS NOT NULL AND insurance_claim_id IS NULL)
 OR (tracking_event_id IS NULL AND automation_failure_id IS NULL AND insurance_claim_id IS NOT NULL AND shipment_id IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS support_insurance_case_unique ON public.support_tickets(tenant_id,insurance_claim_id) WHERE insurance_claim_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS shipments_xcover_policy_lookup ON public.shipments((logistics_metadata->'insurance'->>'policy_id'))
 WHERE logistics_metadata->'insurance'->>'provider'='XCOVER';
ALTER TABLE public.insurance_claim_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.insurance_purchases ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.insurance_claim_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.insurance_webhook_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.insurance_settlements ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.xclaim_webhook_receipts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.insurance_claim_cases,public.insurance_claim_evidence,public.insurance_webhook_receipts FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT ON public.insurance_claim_cases,public.insurance_claim_evidence,public.insurance_webhook_receipts TO service_role;
REVOKE ALL ON public.insurance_purchases FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.insurance_purchases TO service_role;
GRANT UPDATE ON public.insurance_claim_cases TO service_role;
REVOKE ALL ON public.insurance_settlements FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT ON public.insurance_settlements TO service_role;
GRANT UPDATE ON public.insurance_claim_evidence TO service_role;
REVOKE ALL ON public.xclaim_webhook_receipts FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT ON public.xclaim_webhook_receipts TO service_role;
COMMIT;
