# Moving or renaming the EasyInvio checkout

The Windows checkout is now `C:\Projects\easyinvio`. The product and domain are
EasyInvio.com and easyinvio.com. Application modules, frontend assets, certificates,
migration files and architecture generators resolve from the checkout or their own
file locations; the directory name is not an application identifier.

## Local Python environment

Moving a Windows virtual environment leaves absolute interpreter paths inside its
activation files and installed `.exe` launchers. Its Python executable may still
work while `pip.exe`, `uvicorn.exe` or `pytest.exe` fail. Do not reinstall or upgrade
application packages merely to change the checkout's name.

For this existing Windows environment with the same base Python installation:

```powershell
cd C:\Projects\easyinvio
.\.venv\Scripts\python.exe scripts\repair_renamed_venv.py
.\.venv\Scripts\python.exe scripts\repair_renamed_venv.py --apply
.\.venv\Scripts\pip.exe --version
.\.venv\Scripts\uvicorn.exe --version
.\.venv\Scripts\pytest.exe --version
```

The first command inspects only. The repair regenerates standard activation scripts
and existing package entry points using installed metadata and pip's bundled
launcher generator. It makes no network calls, changes no installed package
versions and refuses to modify system Python or another checkout's environment.
It is intended for a folder move on the same Windows/Python installation. For a
different Python installation or operating system, recreate `.venv` and install the
appropriate pinned requirements instead.

Close terminals using the old activation, open `C:\Projects\easyinvio` in VS Code,
then select `C:\Projects\easyinvio\.venv\Scripts\python.exe` as the interpreter.
Restart the local backend from the new location:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Activation is optional. If PowerShell blocks `Activate.ps1`, use the explicit
`.venv\Scripts\python.exe` command above; changing execution policy is unnecessary.

Check `http://127.0.0.1:8000/health`. Module invocation also avoids depending on a
console launcher when diagnosing an environment that has just moved. Browser test
tools should keep their bundled browser directory under the current checkout.

If an external shortcut, scheduled task or IDE workspace stores the old absolute
directory, point it at the new directory. Such external settings are not changed by
a Git commit.

## Configuration and compatibility

The existing `.env` remains private and should move with the checkout. Database,
Stripe, Supabase, Twilio, SMTP, encryption and signing credentials do not change
because a local directory changed. Do not rotate `CREDENTIAL_KEYS` merely to rename
the directory: previously encrypted carrier settings and queue payloads need those
keys. The configured example CA path is relative to the checkout; update only any
actual absolute local paths you configured, without changing the certificate.

The public domain, registered webhook URLs, Supabase redirects and deployed
environment variables change only if the hosting URL changes. A folder rename
does not change those URLs or require a database migration.

Legacy `veloce_*` CRM/database fields, webhook headers, token issuer/audience values,
browser storage keys, telemetry identifiers and deterministic fixture tags remain
unchanged. They are compatibility identifiers, not the customer-facing brand or
folder path. Blind replacement would invalidate existing integrations, links,
saved preferences or synthetic-data identity.

The configured Git remote is
`https://github.com/sync4ai-lab/easyinvio.git`. The GitHub repository was renamed
separately after the local folder move, retaining its existing commit history.
The local remote and architecture source-link generator now use the new URL.
Renaming the local folder alone does not rename a GitHub repository. For any future
repository rename, verify the new URL before updating these references and check
the hosting project's Git connection before the next deployment.

## Verification

Run offline application checks from the new directory:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests
.\.venv\Scripts\python.exe docs\platform_overview\generate.py --check
git diff --check
```

Disposable PostgreSQL tests require the explicit test-only PGLite dependency; they
skip when it is unavailable. No live database mutation, label purchase, payment or
customer message is needed to verify a folder rename.
