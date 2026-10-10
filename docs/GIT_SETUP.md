# Veloce.AI Git workflow

Git is installed. This workspace is not yet a Git repository. `.gitignore` now
excludes `.env` variants, private keys, virtual environments, browser binaries,
logs, database dumps and selected environment-specific test receipts. Track
`.env.example`, application source, requirements, migrations, synthetic seeds,
test scripts and documentation. The public Supabase CA certificate may be tracked.

## First upload

Create an **empty private repository** named `veloce-ai` in your Git provider.
For GitHub, do not select initial README/license/gitignore files: they already
exist here. Copy the HTTPS clone URL.

Run in the VS Code PowerShell terminal:

```powershell
cd C:\Projects\veloce-ai
git init -b main
git config user.name "YOUR NAME"
git config user.email "YOUR GIT EMAIL"
git check-ignore -v .env .venv .playwright
git add .
git status --short
git diff --cached --stat
git ls-files -- .env
```

The last command must return **no output**. Review staged filenames and changes.
`.env.example` should be tracked; `.env`, credentials, real customer exports and
database dumps should not. Ignore rules do not remove already tracked files.

Replace the URL below with your empty repository's actual clone URL:

```powershell
git commit -m "Initial Veloce.AI application"
git remote add origin https://github.com/YOUR-ACCOUNT/veloce-ai.git
git push -u origin main
```

Authenticate using the browser/Git Credential Manager prompt. Never embed tokens
or passwords in the URL. No repository was created or uploaded automatically.
Reference: [GitHub's existing-project upload guide](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github).

## Daily maintenance

```powershell
git switch main
git pull --ff-only
git switch -c feature/describe-the-change
# Make changes and run the relevant tests.
git status --short
git add backend index.html frontend migrations tests docs .env.example
git diff --cached --stat
git commit -m "Describe the behavior changed"
git push -u origin feature/describe-the-change
```

Stage only relevant existing paths. Open a pull request and merge after review
and checks. Pull `main` again before the next branch. VS Code's Source Control
panel supports the same stage/commit/push workflow. Configure branch protection,
required tests and secret scanning where your hosting plan supports them.

## Keep Supabase reproducible

Pushing code does not copy database rows, run SQL, configure Auth hooks or deploy
the backend. Keep each machine's credentials in its local `.env` or your hosting
secret manager. Database backups belong in protected backup storage, not Git.

The current numbered migration files start at **006** and now run through **016**.
The original base schema and Auth setup were created outside this repository;
these additions alone cannot recreate an empty database. Capture a schema-only
baseline before treating the repository as a complete database recovery source.

After installing Supabase CLI and its required tooling:

```powershell
supabase init
supabase login
supabase link --project-ref yutdvcbaqjhryubnlods
supabase db pull
```

Review the generated schema migration and reconcile the manually applied history
before using `supabase db push`. Supabase uses timestamped `supabase/migrations`
history; the numbered `migrations/` files are not registered there automatically.
Do not reapply all numbered additions on top of a pulled full baseline. Never
run `supabase db reset --linked` on this project; that resets the remote database.
Reference: [Supabase migration workflow](https://supabase.com/docs/guides/local-development/database-migrations).

## Restore the application

Clone the repository, install Python 3.12+, create `.venv`, install the requirements
and copy `.env.example` to `.env`. Configure credentials locally and connect to
the matching database. Run the local checks, then start `main.py`. Environments
and credentials are deliberately recreated rather than synchronized through Git.
