# Additional UAT fixtures

Run `01_supplemental_data.sql` in full after `rigorous_v1/all_in_one.sql` has completed. The numbered rigorous_v1 files are an alternative for one persistent transaction, not extra scripts to run after all_in_one.

This supplement passed actual Supabase constraint validation in a rolled-back transaction. It has now been applied by the user and verified against Supabase. No further seed execution is needed. It adds three sandbox tenants, including an empty long-name postpaid workspace; OWNER/ADMIN/DISPATCHER memberships including one inactive dispatcher; inactive TEST carrier parents; FIXED 5.50, zero percentage, weight-tier and priority-conflict rules; eight exact-value quotes. Auth principals are banned; no real login, label, payment or external message is created. Opening credits are synthetic fixture balances, not payment receipts.

UAT results: `docs/uat_100/RESULTS.md`. Applying SQL alone will not resolve missing product features or browser/provider/session prerequisites. Priority tests intentionally demonstrate the current lower-number-wins convention.
