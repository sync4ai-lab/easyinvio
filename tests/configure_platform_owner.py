"""Verify the explicitly authorized owner and update only its local allowlist."""
import json
import re
import argparse
from pathlib import Path
from uuid import UUID

import httpx
from main import Settings


def main():
    parser=argparse.ArgumentParser(description='Verify and allowlist an explicitly authorized Supabase Auth owner')
    parser.add_argument('auth_user_id',type=UUID)
    owner=parser.parse_args().auth_user_id
    settings = Settings()
    key = settings.supabase_service_role_key.get_secret_value()
    with httpx.Client(timeout=30) as client:
        response = client.get(
            str(settings.supabase_url).rstrip("/") + f"/auth/v1/admin/users/{owner}",
            headers={"apikey": key, "Authorization": "Bearer " + key},
        )
    if response.status_code != 200:
        raise SystemExit(f"Owner verification failed (HTTP {response.status_code}); configuration unchanged")
    if response.json().get("id") != str(owner):
        raise SystemExit("Owner identity mismatch; configuration unchanged")
    ids = list(dict.fromkeys([str(uid) for uid in settings.platform_admin_user_ids] + [str(owner)]))
    path = Path(".env")
    content = path.read_text(encoding="utf-8")
    pattern = r"(?m)^PLATFORM_ADMIN_USER_IDS\s*=.*$"
    if len(re.findall(pattern, content)) > 1:
        raise SystemExit("Duplicate owner configuration entries; configuration unchanged")
    line = "PLATFORM_ADMIN_USER_IDS=" + json.dumps(ids)
    updated = re.sub(pattern, lambda _: line, content) if re.search(pattern, content) else content.rstrip() + "\n" + line + "\n"
    path.write_text(updated, encoding="utf-8")
    assert owner in Settings().platform_admin_user_ids
    print(json.dumps({"auth_user_exists": True, "owner_allowlist_configured": True, "owner_count": len(ids)}))


if __name__ == "__main__":
    main()
