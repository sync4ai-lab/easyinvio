"""Offline safety checks for the local checkout-move utility."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.repair_renamed_venv import environment, launcher_specs


def test_environment_rejects_system_python_and_other_checkouts(tmp_path):
    root = tmp_path / 'easyinvio'
    python = root / '.venv' / 'Scripts' / 'python.exe'
    python.parent.mkdir(parents=True)
    python.write_bytes(b'synthetic launcher location; never executed')
    prefix = str(root / '.venv')
    assert environment(root, prefix, str(tmp_path / 'base-python')) == Path(prefix)
    for actual, base in [(prefix, prefix), (str(tmp_path / 'other' / '.venv'), str(tmp_path / 'base-python'))]:
        with pytest.raises(RuntimeError):
            environment(root, actual, base)
    python.unlink()
    with pytest.raises(RuntimeError):
        environment(root, prefix, str(tmp_path / 'base-python'))


def test_only_existing_entry_points_are_rebuilt_and_gui_intent_is_preserved(tmp_path):
    for name in ('uvicorn', 'desktop-tool'):
        (tmp_path / f'{name}.exe').write_bytes(b'synthetic; never executed')
    entries = [SimpleNamespace(name='uvicorn', module='uvicorn.main', attr='main', group='console_scripts'),
        SimpleNamespace(name='absent-tool', module='sample', attr='main', group='console_scripts'),
        SimpleNamespace(name='desktop-tool', module='sample', attr='window', group='gui_scripts')]
    assert launcher_specs(tmp_path, entries) == [
        ('desktop-tool = sample:window', True), ('uvicorn = uvicorn.main:main', False)]
    assert (tmp_path / 'uvicorn.exe').read_bytes() == b'synthetic; never executed'


@pytest.mark.parametrize('name', ['../outside', '..\\outside', '/absolute', 'C:\\outside', 'bad name'])
def test_installed_metadata_cannot_escape_the_scripts_directory(tmp_path, name):
    with pytest.raises(RuntimeError):
        launcher_specs(tmp_path, [SimpleNamespace(name=name, attr='main', module='sample', group='console_scripts')])
