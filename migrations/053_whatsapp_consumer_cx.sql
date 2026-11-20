-- Apply once after 052. No provider calls, purchases, refunds or consent grants.
BEGIN;
SET LOCAL lock_timeout='10s';
CREATE TABLE public.whatsapp_consumer_sessions (
 sender_e164 text NOT NULL,receiver_e164 text NOT NULL,provider text NOT NULL,provider_account text NOT NULL,
 token_sha256 text NOT NULL CHECK(token_sha256 ~ '^[a-f0-9]{64}$'),
 tenant_id uuid NOT NULL,share_link_id uuid NOT NULL,shipment_id uuid NOT NULL,
 payload_ciphertext bytea NOT NULL,key_id text NOT NULL,expires_at timestamptz NOT NULL,
 PRIMARY KEY(provider,provider_account,sender_e164,receiver_e164),
 FOREIGN KEY(tenant_id,share_link_id) REFERENCES public.tracking_share_links(tenant_id,id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
CREATE INDEX whatsapp_consumer_expiry ON public.whatsapp_consumer_sessions(expires_at);
CREATE TABLE public.whatsapp_consumer_messages (
 id uuid PRIMARY KEY,input_sha256 text NOT NULL,token_sha256 text,state text NOT NULL CHECK(state IN ('PROCESSING','COMPLETE')),
 response_ciphertext bytea,key_id text NOT NULL,created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.whatsapp_consumer_messages ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.whatsapp_consumer_messages FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.whatsapp_consumer_messages TO service_role;
CREATE TABLE public.whatsapp_consumer_return_policies (
 tenant_id uuid PRIMARY KEY REFERENCES public.tenants(tenant_id),enabled boolean NOT NULL DEFAULT false,
 authorized_by uuid NOT NULL REFERENCES auth.users(id),window_days integer NOT NULL CHECK(window_days BETWEEN 1 AND 90),
 charge_bearer text NOT NULL CHECK(charge_bearer IN ('RETAILER_PAY','CUSTOMER_PAY')),
 maximum_price_gbp numeric(12,2) NOT NULL CHECK(maximum_price_gbp>0 AND maximum_price_gbp<=100),
 version integer NOT NULL DEFAULT 1,updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.support_tickets ADD COLUMN cx_request_id uuid UNIQUE,
 ADD COLUMN cx_kind text CHECK(cx_kind IN ('SERVICE_REQUEST','COMPLAINT','RETURN_REQUEST','REFUND_INQUIRY')),
 ADD COLUMN issue_category text CHECK(issue_category IN ('DAMAGED','MISSING_DELAYED','ADDRESS_CHANGE','BILLING_OTHER')),
 ADD COLUMN tracking_customer_request_id uuid REFERENCES public.tracking_customer_requests(id);
ALTER TABLE public.support_tickets DROP CONSTRAINT support_ticket_source;
ALTER TABLE public.support_tickets ADD CONSTRAINT support_ticket_source CHECK(
 (cx_request_id IS NULL AND cx_kind IS NULL AND tracking_customer_request_id IS NULL AND (
  (tracking_event_id IS NOT NULL AND automation_failure_id IS NULL AND insurance_claim_id IS NULL AND shipment_id IS NOT NULL)
  OR (tracking_event_id IS NULL AND automation_failure_id IS NOT NULL AND insurance_claim_id IS NULL)
  OR (tracking_event_id IS NULL AND automation_failure_id IS NULL AND insurance_claim_id IS NOT NULL AND shipment_id IS NOT NULL)))
 OR (cx_request_id IS NOT NULL AND cx_kind IS NOT NULL AND issue_category IS NOT NULL AND shipment_id IS NOT NULL
  AND tracking_event_id IS NULL AND automation_failure_id IS NULL AND insurance_claim_id IS NULL));
-- Bind B2C intake to exactly the same tenant and shipment as its support case.
ALTER TABLE public.tracking_customer_requests ADD CONSTRAINT tracking_customer_scope UNIQUE(tenant_id,shipment_id,id);
ALTER TABLE public.support_tickets ADD CONSTRAINT support_customer_scope
 FOREIGN KEY(tenant_id,shipment_id,tracking_customer_request_id) REFERENCES public.tracking_customer_requests(tenant_id,shipment_id,id);
ALTER TABLE public.support_message_outbox DROP CONSTRAINT support_message_outbox_message_kind_check;
ALTER TABLE public.support_message_outbox ADD CONSTRAINT support_message_outbox_message_kind_check
 CHECK(message_kind IN ('CARRIER_EXCEPTION','INSURANCE_SETTLEMENT','CUSTOMER_CX'));
ALTER TABLE public.whatsapp_consumer_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.whatsapp_consumer_return_policies ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.whatsapp_consumer_sessions,public.whatsapp_consumer_return_policies FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.whatsapp_consumer_sessions TO service_role;
GRANT SELECT,INSERT,UPDATE ON public.whatsapp_consumer_return_policies TO service_role;
COMMIT;
