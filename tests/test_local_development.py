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
