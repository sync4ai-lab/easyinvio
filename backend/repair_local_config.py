"""Repair identifiable dotenv formatting without printing credential values."""
import base64
import json
import re
from pathlib import Path
from urllib.parse import quote, unquote

from cryptography.fernet import Fernet
from dotenv import dotenv_values, set_key


def run():
    path = Path(__file__).resolve().parents[1] / ".env"
    values = dotenv_values(path)
    key = values.get("SUPABASE_SERVICE_ROLE_KEY", "")
    try:
        claims = json.loads(base64.urlsafe_b64decode(key.split(".")[1] + "==="))
    except Exception:
        claims = {}
    project = claims.get("ref")
    match = re.search(r"([a-z]{20})\.supabase\.co", values.get("SUPABASE_URL", ""))
    if not re.fullmatch(r"[a-z]{20}", project or "") or claims.get("role") != "service_role":
        raise SystemExit("Cannot safely infer the Supabase project from the server key")
    if match and match.group(1) != project:
        raise SystemExit("Project mismatch between URL and server key; no changes made")
    updates = {"SUPABASE_URL": f"https://{project}.supabase.co", "STRIPE_ENABLED": "false",
               "TWILIO_ENABLED": "false", "SANDBOX_HOOKS_ENABLED": "false",
               "TWILIO_WHATSAPP_SANDBOX_ENABLED": "false", "DATABASE_ENVIRONMENT": "SANDBOX"}
    db = values.get("DATABASE_URL", "")
    # Square brackets around a DNS hostname are example notation, not valid URI syntax.
    db = re.sub(r"@\[([a-zA-Z0-9.-]+\.supabase\.(?:co|com))\]", r"@\1", db)
    # Percent-encode the credential section, preserving already encoded passwords.
    match_db = re.fullmatch(r"(postgres(?:ql)?://)([^:]+):(.*)@([^/]+)(/.*)", db)
    if match_db:
        prefix, user, password, host, tail = match_db.groups()
        db = prefix + quote(unquote(user), safe=".") + ":" + quote(unquote(password), safe="") + "@" + host + tail
    updates["DATABASE_URL"] = db
    try:
        keys = json.loads(values.get("CREDENTIAL_KEYS", "{}"))
        for value in keys.values():
            Fernet(value.encode("ascii"))
    except Exception:
        # Do not invent a replacement encryption key for existing carrier data.
        updates["CREDENTIAL_KEYS"] = "{}"
    for name, value in updates.items():
        set_key(str(path), name, value, quote_mode="always")
    print("Updated setting names:", ", ".join(sorted(updates)))
    print("Existing Supabase keys preserved; unavailable payment/messaging integrations disabled")


if __name__ == "__main__":
    run()
