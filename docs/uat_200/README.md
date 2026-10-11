# 200-case UAT audit

Run from the project root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\.venv\Scripts\python.exe -m pytest tests/uat_automation_suite.py -q --tb=short
```

The suite defines exactly 200 IDs using the specification's explicit ranges: A35, B35, C35, D35, E35, F25. A includes real HTTP calls to the running backend using disposable password-verified Supabase identities (OWNER, DISPATCHER, ACCOUNTANT). Financial probes connect to the actual configured sandbox PostgreSQL database and roll back all financial changes. A 150-order international CSV is generated at `tests/uat_200/veloce_bulk_test_150.csv`.

The report is `UAT_EXECUTION_REPORT.md` in the project root; machine-readable evidence is `docs/uat_200/results.json`. Both include all 200 scenario entries. The matrix has different evidence levels:

- PASS: the case's stated scope actually passed.
- FAIL: a executed assertion failed.
- PARTIAL: contract/parser behavior passed with controlled dependencies, but the specified genuine provider/database workflow is not verified.
- BLOCKED: dependency/human/provider prerequisites prevented the desired workflow.

Pytest represents PARTIAL and BLOCKED as skipped so they cannot masquerade as green acceptance. It exits nonzero on an actual failed case. The suite is an executable bounded audit, not a claim that 200 genuine end-to-end workflows completed. No secrets or raw provider records are saved in the report. Provider readiness probes are read-only. It does not silently enable live dispatch, CRM provisioning, change financial configuration, send phone messages, complete card challenges or turn off customs-review requirements.

The role fixture creates three transient auth users, public member rows and app sessions in a pre-existing synthetic tenant. It verifies real password login and cleans up users/member/session rows afterward. It never uses the account holder's password or grants super-admin to disposable identities. Cleanup failures are explicitly reported. Existing fixture credits are synthetic opening balances, not Stripe receipts. API request steps, exact executable contract references and measured case timings are included in the report.

Supplementary browser scripts executed separately (outside the 200 count): `test_identity_browser.py`, `test_password_recovery_browser.py`, and `test_enterprise_browser.py`. All passed; no JavaScript errors were observed in the enterprise probe. These scripts use controlled API/sample responses where documented. They cover responsive login, recovery URL handling, session clearing, role navigation, input contrast, HS injection and exception/POD actions.

The remediation adds explicit tenant-query rejection. TC-032 now passes with HTTP 403; no SQL migration is needed. Missing provider prerequisites and incomplete live evidence remain partial/blocked rather than marked passed.

Additional regression run: `python -m unittest discover -s tests -p "test_*.py"` executed 215 test executions successfully. This is supplementary controlled regression evidence, outside the 200 UAT count; overlapping assertions are not presented as 209 additional unique business journeys.
