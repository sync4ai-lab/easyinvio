r"""Repair this checkout's Windows venv launchers after moving the folder.

Run with .venv\Scripts\python.exe. Default: inspect only; --apply regenerates
activation scripts and existing entry points offline, without reinstalling packages.
For a different Python installation/platform, recreate the environment instead.
"""
from __future__ import annotations

import argparse
from importlib.metadata import entry_points
from pathlib import Path
import re
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def environment(root: Path, prefix: str, base_prefix: str) -> Path:
    expected = (root / '.venv').resolve()
    actual = Path(prefix).resolve()
    if actual != expected or actual == Path(base_prefix).resolve():
        raise RuntimeError('Run this script with this checkout\'s .venv/Scripts/python.exe; the system Python will not be modified.')
    if not (expected / 'Scripts' / 'python.exe').is_file():
        raise RuntimeError('A Windows virtual environment is required; recreate the venv on other platforms.')
    return expected


def launcher_specs(target: Path, entries) -> list[tuple[str, bool]]:
    specs = []
    for entry in entries:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', entry.name):
            raise RuntimeError('An installed entry point has an unsafe launcher name')
        if not entry.attr:
            raise RuntimeError('An installed entry point has no callable')
        names = [entry.name]
        if entry.name == 'pip':
            names += [f'pip{sys.version_info.major}', f'pip{sys.version_info.major}.{sys.version_info.minor}']
        for name in names:
            if (target / f'{name}.exe').is_file():
                specs.append((f'{name} = {entry.module}:{entry.attr}', entry.group == 'gui_scripts'))
    return sorted(set(specs))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Regenerate local activation scripts and existing launchers')
    args = parser.parse_args(argv)
    try:
        active = environment(ROOT, sys.prefix, sys.base_prefix)
        target = active / 'Scripts'
        entries = list(entry_points(group='console_scripts')) + list(entry_points(group='gui_scripts'))
        specs = launcher_specs(target, entries)
        print(f'Environment: {active}')
        print(f'Existing package launchers: {len(specs)}')
        if not args.apply:
            print('Inspection only. Add --apply to repair; installed package versions are preserved.')
            return 0
        # Validate dependency availability before making any local change.
        from pip._vendor.distlib.scripts import ScriptMaker
        builder = venv.EnvBuilder(with_pip=False, clear=False)
        context = builder.ensure_directories(str(active))
        builder.setup_scripts(context)
        builder.create_configuration(context)
        maker = ScriptMaker(None, str(target))
        maker.executable = str(target / 'python.exe')
        maker.clobber = True
        maker.variants = {''}
        for spec, gui in specs:
            maker.make(spec, options={'gui': gui})
        print('Repaired activation and launchers offline. Open a new terminal or reactivate this venv.')
        return 0
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
