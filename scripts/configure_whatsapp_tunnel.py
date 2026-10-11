r"""Start/reuse ngrok and configure exact signed callback URLs without printing secrets.

Run from the project: .\.venv\Scripts\python.exe scripts\configure_whatsapp_tunnel.py
Restart the backend afterwards and save the printed webhook in Twilio's Sandbox.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def running_tunnel(client: httpx.Client) -> str | None:
    try:
        response = client.get("http://127.0.0.1:4040/api/tunnels")
        response.raise_for_status()
        for tunnel in response.json().get("tunnels", []):
            if (tunnel.get("config", {}).get("addr") in
                    {"http://localhost:8000", "http://127.0.0.1:8000", "localhost:8000", "8000"}
                    and urlsplit(tunnel.get("public_url", "")).scheme == "https"):
                return tunnel["public_url"].rstrip("/")
    except (httpx.HTTPError, ValueError):
        return None
    return None


def main() -> None:
    env_file = ROOT / ".env"
    if not env_file.is_file():
        raise SystemExit("Create the project's private .env first.")
    values = dotenv_values(env_file)
    with httpx.Client(trust_env=False, timeout=2) as client:
        public_url = running_tunnel(client)
        if not public_url:
            executable = shutil.which("ngrok")
            if not executable:
                raise SystemExit("Install ngrok from https://ngrok.com/download/windows first.")
            token = os.environ.get("NGROK_AUTHTOKEN") or values.get("NGROK_AUTHTOKEN")
            config = Path(os.environ.get("LOCALAPPDATA", "")) / "ngrok" / "ngrok.yml"
            if not token and not config.is_file():
                raise SystemExit("Save NGROK_AUTHTOKEN in your private .env, then rerun. Do not share it in chat.")
            environment = os.environ.copy()
            if token:
                environment["NGROK_AUTHTOKEN"] = token
            with (ROOT / "ngrok-output.log").open("ab") as log:
                process = subprocess.Popen([executable, "http", "http://127.0.0.1:8000", "--log=stdout"],
                    cwd=ROOT, env=environment, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            for _ in range(30):
                public_url = running_tunnel(client)
                if public_url:
                    break
                if process.poll() is not None:
                    raise SystemExit("ngrok could not start. Check its private local log; do not share tokens.")
                time.sleep(0.5)
            if not public_url:
                process.terminate()
                raise SystemExit("ngrok startup timed out. Check account authentication and network access.")
    updates = {
        "TWILIO_WEBHOOK_URL": public_url + "/api/v1/integrations/whatsapp/webhook",
        "BOOKING_PAGE_URL": public_url + "/",
        "SUPPORT_WHATSAPP_STATUS_URL": public_url + "/api/v1/support/whatsapp/status",
    }
    text = env_file.read_text(encoding="utf-8")
    for name, value in updates.items():
        pattern = re.compile(r"^" + re.escape(name) + r"=.*$", re.MULTILINE)
        if len(pattern.findall(text)) > 1:
            raise SystemExit(f"Remove duplicate {name} entries before configuring the tunnel.")
        text = pattern.sub(name + "=" + value, text) if pattern.search(text) else text.rstrip() + "\n" + name + "=" + value + "\n"
    env_file.write_text(text, encoding="utf-8")
    print("Twilio Sandbox: When a message comes in → POST " + updates["TWILIO_WEBHOOK_URL"])
    print("Restart the backend to load these URLs. Leave ngrok running while testing.")
    print("Join the Sandbox from your phone using the join code in the Twilio Console.")


if __name__ == "__main__":
    main()
