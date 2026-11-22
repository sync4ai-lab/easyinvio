"""Launcher guardrails, without starting providers or using private settings."""
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_whatsapp_worker_requires_exclusive_queue_acknowledgement():
    result=subprocess.run([sys.executable,str(ROOT/'scripts/dev.py'),'--whatsapp'],capture_output=True,text=True)
    assert result.returncode==2
    assert 'Pause hosted WhatsApp consumers first' in result.stderr


def test_help_explains_modes_without_requiring_credentials():
    result=subprocess.run([sys.executable,str(ROOT/'scripts/dev.py'),'--help'],capture_output=True,text=True)
    assert result.returncode==0
    for name in ['--preview','--lan','--public-url','--whatsapp','--env-file']:assert name in result.stdout


# Local links must stay on the developer's machine. Public callbacks remain HTTPS.
import pytest
from main import Settings


@pytest.mark.parametrize('url', ['http://127.0.0.1:8000', 'http://localhost:8000', 'http://[::1]:8000', 'https://uat.easyinvio.com'])
def test_booking_links_accept_loopback_and_https(url):
    assert Settings.booking_origin(url) == url


@pytest.mark.parametrize('url', ['http://easyinvio.com', 'http://192.168.1.2:8000', 'http://localhost.evil.test', 'https://user:password@example.test', 'http://localhost:8000?redirect=evil', 'http://localhost:8000#fragment'])
def test_booking_links_reject_public_http_credentials_and_redirect_fragments(url):
    with pytest.raises(ValueError):
        Settings.booking_origin(url)


def test_public_webhook_still_requires_https():
    with pytest.raises(ValueError):
        Settings.fixed_https_url('http://127.0.0.1:8000/api/v1/integrations/whatsapp/webhook')


def test_tunnel_preserves_explicit_uat_booking_origin():
    from scripts.dev import booking_url
    assert booking_url('https://uat.easyinvio.com','https://tunnel.ngrok-free.dev')=='https://uat.easyinvio.com'
    assert booking_url('https://easyinvio.com','https://tunnel.ngrok-free.dev')=='https://easyinvio.com'
    assert booking_url('http://127.0.0.1:8000','https://tunnel.ngrok-free.dev')=='https://tunnel.ngrok-free.dev'
