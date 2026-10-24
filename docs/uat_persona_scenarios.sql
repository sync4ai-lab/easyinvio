-- EasyInvio UAT persona checks. Run the complete file in Supabase SQL Editor.
-- SQL Editor runs as an administrator: these inspect data, not frontend RBAC.
-- Browser/API negative-permission tests are documented in uat_persona_scenarios.md.
BEGIN TRANSACTION READ ONLY;
SELECT set_config('easyinvio.uat_workspace','mkr-enterprises-uat',true);

-- OWNER / ADMIN: workspace, actual roles, unique active membership and profiles.
SELECT t.workspace_slug,t.company_name,t.is_sandbox,t.workspace_status,t.billing_status,
       u.full_name,u.role,u.is_active,p.phone_e164,
       (SELECT count(*) FROM public.users x WHERE x.auth_user_id=u.auth_user_id AND x.is_active) AS active_memberships
FROM public.tenants t JOIN public.users u USING(tenant_id)
LEFT JOIN public.app_user_profiles p USING(auth_user_id)
WHERE t.workspace_slug=current_setting('easyinvio.uat_workspace') AND t.is_sandbox;

-- OWNER / ADMIN: four address roles; two unreviewed, exact-decimal products.
SELECT a.label,a.address_role,a.is_default,a.address->>'city' AS city,a.address->>'postal_code' AS postcode
FROM public.tenant_catalog_addresses a JOIN public.tenants t USING(tenant_id)
WHERE t.workspace_slug=current_setting('easyinvio.uat_workspace') AND t.is_sandbox AND a.archived_at IS NULL;
SELECT p.sku,p.description,p.unit_weight_kg,p.unit_value,p.currency,p.hs_code,
       p.hs_reviewed_at IS NOT NULL AS customs_classification_reviewed
FROM public.tenant_catalog_products p JOIN public.tenants t USING(tenant_id)
WHERE t.workspace_slug=current_setting('easyinvio.uat_workspace') AND t.is_sandbox AND p.archived_at IS NULL;

-- DISPATCHER: packing, import review, expired quotes and current carrier facts.
SELECT s.customer_reference,s.status,s.origin_country,s.destination_country,s.cargo_type,
       s.parcel_weight_kg,s.parcel_length_cm,s.parcel_width_cm,s.parcel_height_cm,
       s.customs_required,s.logistics_metadata ? 'batch_csv' AS imported,
       s.quote_expires_at<=now() AS saved_quote_expired,s.carrier_code,s.service_code,s.tracking_number
FROM public.shipments s JOIN public.tenants t USING(tenant_id)
WHERE t.workspace_slug=current_setting('easyinvio.uat_workspace') AND t.is_sandbox
ORDER BY s.created_at DESC LIMIT 30;

-- ACCOUNTANT: empty initial wallet is intentional. Top up through Stripe TEST.
SELECT t.company_name,w.currency,w.balance,w.reserved_balance,w.balance-w.reserved_balance AS available
FROM public.wallets w JOIN public.tenants t USING(tenant_id)
WHERE t.workspace_slug=current_setting('easyinvio.uat_workspace') AND t.is_sandbox;
SELECT l.entry_type,l.currency,l.balance_delta,l.reserved_delta,l.created_at
FROM public.wallet_ledger l JOIN public.tenants t USING(tenant_id)
WHERE t.workspace_slug=current_setting('easyinvio.uat_workspace') AND t.is_sandbox
ORDER BY l.created_at DESC LIMIT 30;
SELECT c.status,c.amount,c.currency,c.created_at
FROM public.payment_carts c JOIN public.tenants t USING(tenant_id)
WHERE t.workspace_slug=current_setting('easyinvio.uat_workspace') AND t.is_sandbox
ORDER BY c.created_at DESC LIMIT 30;

-- ALL SHIPPING PERSONAS: only recorded carrier events constitute progress.
SELECT s.customer_reference,e.status,e.occurred_at
FROM public.tracking_events e JOIN public.shipments s ON s.tenant_id=e.tenant_id AND s.id=e.shipment_id
JOIN public.tenants t ON t.tenant_id=e.tenant_id
WHERE t.workspace_slug=current_setting('easyinvio.uat_workspace') AND t.is_sandbox
ORDER BY e.occurred_at DESC LIMIT 30;

-- OWNER / ADMIN: returns keep original and child shipment identities separate.
SELECT s.customer_reference,r.charge_bearer,r.state,r.return_shipment_id,r.expires_at
FROM public.return_review_sessions r JOIN public.shipments s ON s.tenant_id=r.tenant_id AND s.id=r.original_shipment_id
JOIN public.tenants t ON t.tenant_id=r.tenant_id
WHERE t.workspace_slug=current_setting('easyinvio.uat_workspace') AND t.is_sandbox
ORDER BY r.created_at DESC LIMIT 30;

-- CLAIMS / SUPPORT: an operational support ticket is not an insurer settlement.
SELECT c.state,c.reason,c.insurer_status,c.last_error_code,c.created_at
FROM public.insurance_claim_cases c JOIN public.tenants t USING(tenant_id)
WHERE t.workspace_slug=current_setting('easyinvio.uat_workspace') AND t.is_sandbox
ORDER BY c.created_at DESC LIMIT 30;
SELECT k.status,k.ai_summary,k.created_at
FROM public.support_tickets k JOIN public.tenants t USING(tenant_id)
WHERE t.workspace_slug=current_setting('easyinvio.uat_workspace') AND t.is_sandbox
ORDER BY k.created_at DESC LIMIT 30;

-- OUTBOUND COMMUNICATIONS: accepted is server acceptance, not inbox delivery.
SELECT s.customer_reference,n.category,n.channel,n.state,n.error_code,n.attempts
FROM public.shipment_sender_notifications n JOIN public.shipments s ON s.tenant_id=n.tenant_id AND s.id=n.shipment_id
JOIN public.tenants t ON t.tenant_id=n.tenant_id
WHERE t.workspace_slug=current_setting('easyinvio.uat_workspace') AND t.is_sandbox
ORDER BY n.id DESC LIMIT 30;

-- REFERENCE INTEGRITY: all counts must be zero.
SELECT
 (SELECT count(*) FROM public.users u LEFT JOIN auth.users a ON a.id=u.auth_user_id WHERE a.id IS NULL) AS missing_auth_users,
 (SELECT count(*) FROM public.shipments s JOIN public.tenants t USING(tenant_id)
  LEFT JOIN public.users u ON u.tenant_id=s.tenant_id AND u.id=s.created_by_user_id
  WHERE t.workspace_slug=current_setting('easyinvio.uat_workspace') AND t.is_sandbox AND u.id IS NULL) AS missing_shipment_memberships;
COMMIT;
