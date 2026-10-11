"""Start local Stripe forwarding with the project's key, without printing secrets.

Stop any previous local Stripe listener before running this helper, then restart
main.py after it synchronizes the private local listener signing secret.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def main():
    values = dotenv_values(ROOT / '.env')
    key = values.get('STRIPE_SECRET_KEY', '')
    if (not key.startswith('sk_test_') or values.get('STRIPE_LIVEMODE', '').lower() != 'false'
            or values.get('DATABASE_ENVIRONMENT') != 'SANDBOX'
            or values.get('PROVIDER_ENVIRONMENT') != 'TEST'):
        raise SystemExit('This helper requires the project sandbox key and STRIPE_LIVEMODE=false.')
    cli = shutil.which('stripe.cmd') or shutil.which('stripe')
    if not cli:
        candidate = Path(os.environ.get('APPDATA', '')) / 'npm' / 'stripe.cmd'
        cli = str(candidate) if candidate.is_file() else None
    if not cli:
        raise SystemExit('Install the official Stripe CLI first.')
    child_env = os.environ.copy()
    child_env['STRIPE_API_KEY'] = key
    try:
        probe = subprocess.run([cli, 'listen', '--print-secret'], env=child_env,
            capture_output=True, text=True, timeout=30, cwd=ROOT)
    except (OSError, subprocess.TimeoutExpired):
        raise SystemExit('Could not check the Stripe sandbox listener.') from None
    match = re.search(r'whsec_[A-Za-z0-9]+', probe.stdout + '\n' + probe.stderr)
    if probe.returncode != 0 or not match:
        raise SystemExit('Stripe listener authentication failed; verify your project sandbox key.')
    env_file = ROOT / '.env'
    text = env_file.read_text(encoding='utf-8')
    pattern = r'^STRIPE_WEBHOOK_SECRET=.*$'
    if len(re.findall(pattern, text, re.MULTILINE)) != 1:
        raise SystemExit('Keep exactly one STRIPE_WEBHOOK_SECRET entry in .env.')
    text = re.sub(pattern, lambda _: 'STRIPE_WEBHOOK_SECRET=' + match.group(), text, flags=re.MULTILINE)
    env_file.write_text(text, encoding='utf-8')
    with (ROOT / 'stripe-listener-output.log').open('wb') as out, (ROOT / 'stripe-listener-error.log').open('wb') as err:
        subprocess.Popen([cli, 'listen', '--events', 'checkout.session.completed,charge.refunded,charge.failed',
            '--forward-to', 'http://127.0.0.1:8000/api/v1/billing/webhooks/stripe'], env=child_env, cwd=ROOT,
            stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    print('Sandbox Stripe forwarding started; local signing secret synchronized privately.')
    print('Restart the backend to load the signing secret. This helper creates no payments.')


if __name__ == '__main__':
    main()
