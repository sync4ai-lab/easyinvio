"""Allowlisted CDN build and reproducible worker source bundle. No .env access.

Run --bundle after changing runtime sources; the normal Vercel build fails if
the checked-in worker bundle differs from source, preventing split versions.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ('index.html', 'tracking.html', 'tracking-workspace.js',
          'tracking-public.js', 'tracking-ui.css', 'manifest-workflow.js',
          'help-workspace-bridge.js', 'return-workspace.js')
RUNTIME_PATTERNS = ('main.py', 'requirements.txt', 'requirements.lock.txt',
                    'backend/**/*.py', 'certs/*.crt', 'frontend/components/*.html',
                    'frontend/components/*.js', 'frontend/components/*.css',
                    'docs/status_reference.md', 'docs_*.md')


def checked_file(root: Path, path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise ValueError('Build input must be a regular file inside the checkout')
    return resolved


def runtime_files(root: Path) -> dict[str, bytes]:
    files = {}
    for pattern in RUNTIME_PATTERNS:
        for path in sorted(root.glob(pattern)):
            if path.is_file() and '__pycache__' not in path.parts:
                checked_file(root, path)
                # Git normalises these text sources on Linux. Canonicalise here
                # too so a Windows-generated bundle passes the Linux build check.
                files[path.relative_to(root).as_posix()] = path.read_bytes().replace(b'\r\n', b'\n')
    for required in ('main.py', 'backend/worker_runtime.py', 'requirements.lock.txt'):
        if required not in files:
            raise ValueError(f'Missing required worker source: {required}')
    return dict(sorted(files.items()))


def bundle(files: dict[str, bytes]) -> bytes:
    result = io.BytesIO()
    with gzip.GzipFile(fileobj=result, mode='wb', mtime=0, filename='') as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                archive.addfile(info, io.BytesIO(data))
    return result.getvalue()


def prepare(root: Path = ROOT, *, write_bundle: bool = False) -> dict[str, int]:
    files = runtime_files(root)
    archive = bundle(files)
    context = root / 'deployment' / 'worker'
    target = context / 'runtime.tar.gz'
    manifest = context / 'source_manifest.json'
    metadata = json.dumps({name: hashlib.sha256(data).hexdigest()
                           for name, data in files.items()}, indent=2) + '\n'
    if write_bundle:
        context.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive)
        manifest.write_text(metadata, encoding='utf-8', newline='\n')
    elif (not target.is_file() or target.read_bytes() != archive
          or not manifest.is_file() or manifest.read_text(encoding='utf-8') != metadata):
        raise RuntimeError('Worker bundle is stale. Run python scripts/build_vercel.py --bundle and commit it.')
    public = root / 'public'
    public.mkdir(exist_ok=True)
    if public.is_symlink() or public.resolve().parent != root.resolve():
        raise ValueError('public must be a directory inside this checkout')
    for name in ASSETS:
        source = root / name
        checked_file(root, source)
        destination = public / name
        if destination.is_symlink():
            raise ValueError('Public asset must not be a symlink')
        destination.write_bytes(source.read_bytes())
    # Refuse unexpected files rather than accidentally publishing an export,
    # credential, private document or a previous build artifact.
    if {p.name for p in public.iterdir()} != set(ASSETS):
        raise ValueError('Unexpected file in public; only the frontend allowlist may be deployed')
    return {'public_assets': len(ASSETS), 'worker_source_files': len(files)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', action='store_true')
    arguments = parser.parse_args()
    print(json.dumps(prepare(write_bundle=arguments.bundle)))
