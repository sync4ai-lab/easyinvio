-- Synthetic disposable test schema only. Complete the pre-052 financial fields.
ALTER TABLE public.wallets ADD COLUMN reserved_balance numeric NOT NULL DEFAULT 0,ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.wallet_ledger ADD COLUMN topup_id uuid,ADD COLUMN stripe_session_id text,ADD COLUMN stripe_event_id text,ADD COLUMN stripe_payment_intent_id text;
ALTER TABLE public.wallet_ledger ADD COLUMN insurance_purchase_id uuid,ADD COLUMN insurance_settlement_id uuid;
ALTER TABLE public.wallet_ledger ADD CONSTRAINT original_ledger_shape CHECK(
 (entry_type='TOPUP' AND balance_delta>0 AND reserved_delta=0 AND topup_id IS NOT NULL)
 OR (entry_type='CAPTURE' AND balance_delta<0 AND reserved_delta=balance_delta AND reservation_id IS NOT NULL)
 OR (entry_type='SHIPMENT_REFUND' AND balance_delta>0 AND reserved_delta=0 AND reservation_id IS NOT NULL));
ALTER TABLE public.shipments ADD COLUMN tax_amount numeric,ADD COLUMN tracking_number text,ADD COLUMN customer_reference text,
 ADD COLUMN origin_country text DEFAULT 'GBR',ADD COLUMN destination_country text DEFAULT 'GBR';
CREATE TABLE public.billing_disputes(tenant_id uuid,currency text,status text,estimated_overcharge numeric,created_at timestamptz DEFAULT now());
