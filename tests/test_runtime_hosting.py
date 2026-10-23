"""Offline hosting safety: worker ownership, teardown and private build inputs."""
import asyncio
import io
import json
from pathlib import Path
import tarfile
from contextlib import asynccontextmanager

import pytest

from backend.runtime_hosting import BackgroundJobs, pool_options, resolve_role
from scripts.build_vercel import ASSETS, bundle, prepare, runtime_files


def test_hosted_http_does_not_construct_or_run_background_jobs():
    async def scenario():
        jobs = BackgroundJobs(False)

        def forbidden():
            raise AssertionError('HTTP process must not construct a worker coroutine')

        jobs.start('purchase', forbidden)
        assert not jobs.tasks
        await jobs.close()

    asyncio.run(scenario())
    assert resolve_role('AUTO', {'VERCEL': '1'}) == 'WEB'
    assert resolve_role('AUTO', {}) == 'COMBINED'
    assert resolve_role('WORKER', {'VERCEL': '1'}) == 'WORKER'


def test_worker_failure_is_observable_and_remaining_jobs_are_cancelled():
    async def scenario():
        cleaned = asyncio.Event()
        entered = asyncio.Event()
        jobs = BackgroundJobs(True)

        async def persistent():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        async def failed():
            await entered.wait()
            raise ValueError('synthetic crash')

        jobs.start('persistent', persistent)
        jobs.start('failed', failed)
        with pytest.raises(RuntimeError, match='Background job stopped: failed'):
            await asyncio.wait_for(jobs.wait_for_failure(), 1)
        await jobs.close()
        assert cleaned.is_set()
        assert not jobs.tasks

    asyncio.run(scenario())


def test_disabled_optional_worker_is_not_constructed():
    jobs = BackgroundJobs(True)
    jobs.start('disabled', lambda: pytest.fail('disabled factory called'), enabled=False)
    assert not jobs.tasks


def test_web_sessions_close_only_on_release_and_local_pool_is_preserved():
    options = pool_options('WEB', 10, 8)
    assert options['min_size'] == 0 and options['max_size'] == 2
    # asyncpg closes after the acquired unit of work is RELEASED, preserving
    # session advisory locks across its transactions and external API calls.
    assert options['max_queries'] == 1
    assert pool_options('COMBINED', 10, 8) == {'min_size': 1, 'max_size': 9}
    assert pool_options('WORKER', 2, 8)['max_size'] == 8


def fixture_checkout(root):
    for name in ASSETS:
        (root / name).write_text('synthetic public file', encoding='utf-8')
    (root / 'main.py').write_text('app = None', encoding='utf-8')
    (root / 'requirements.lock.txt').write_text('', encoding='utf-8')
    (root / 'backend').mkdir()
    (root / 'backend' / 'worker_runtime.py').write_text('# synthetic worker', encoding='utf-8')
    (root / '.env').write_text('PRIVATE=must-not-be-published', encoding='utf-8')
    (root / 'output').mkdir()
    (root / 'output' / 'private.json').write_text('{"private":true}', encoding='utf-8')


def test_build_publishes_only_allowlisted_assets_and_blocks_stale_worker(tmp_path):
    fixture_checkout(tmp_path)
    result = prepare(tmp_path, write_bundle=True)
    assert result['public_assets'] == len(ASSETS)
    assert {p.name for p in (tmp_path / 'public').iterdir()} == set(ASSETS)
    data = (tmp_path / 'deployment/worker/runtime.tar.gz').read_bytes()
    assert data == bundle(runtime_files(tmp_path))
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        assert set(archive.getnames()) == {'main.py', 'requirements.lock.txt', 'backend/worker_runtime.py'}
        assert all(item.isfile() and not Path(item.name).is_absolute() for item in archive.getmembers())
    prepare(tmp_path)
    (tmp_path / 'main.py').write_text('app = changed', encoding='utf-8')
    with pytest.raises(RuntimeError, match='stale'):
        prepare(tmp_path)


def test_build_refuses_unexpected_public_files(tmp_path):
    fixture_checkout(tmp_path)
    prepare(tmp_path, write_bundle=True)
    (tmp_path / 'public/private.txt').write_text('not public', encoding='utf-8')
    with pytest.raises(ValueError, match='Unexpected file'):
        prepare(tmp_path)


def test_vercel_configuration_keeps_api_routes_out_of_cdn_rewrites():
    root = Path(__file__).resolve().parents[1]
    configuration = json.loads((root / 'vercel.json').read_text(encoding='utf-8'))
    assert {r['source'] for r in configuration['rewrites']} == {'/', '/set-password', '/track'}
    daemon = configuration['daemons']['logistics-worker']
    assert daemon['instances'] == {'lhr1': 1}
    assert daemon['root'] != '.'
    assert configuration['env']['RUNTIME_ROLE'] == 'WEB'


def test_real_web_lifespan_initialises_services_without_queue_consumers(monkeypatch):
    import main
    from fastapi import FastAPI

    class Database:
        closed = False

        @asynccontextmanager
        async def acquire(self):
            yield self

        async def fetchrow(self, *_):
            return {'bypass': True, 'can_set_role': True}

        async def fetchval(self, *_):
            return True

        async def execute(self, *_):
            return 'SELECT 0'

        async def close(self):
            self.closed = True

    database = Database()
    options = {}

    async def create_pool(**kwargs):
        options.update(kwargs)
        return database

    settings = main.Settings(_env_file=None, supabase_url='https://synthetic.supabase.co',
        supabase_publishable_key='synthetic', supabase_service_role_key='synthetic',
        database_url='postgresql://synthetic.invalid/fixture',
        regional_allowed_origins=['https://synthetic.invalid'], runtime_role='WEB',
        stripe_enabled=False, twilio_enabled=False, credential_keys={})
    monkeypatch.setattr(main, 'Settings', lambda: settings)
    monkeypatch.setattr(main.asyncpg, 'create_pool', create_pool)
    # Any accidental network call must fail the test, even if an optional
    # integration has been enabled in the developer's local configuration.
    async def no_network(*_, **__):
        raise AssertionError('No network allowed in the lifespan fixture')
    monkeypatch.setattr(main.httpx.AsyncClient, 'send', no_network)

    async def scenario():
        application = FastAPI()
        async with main.deterministic_lifespan(application):
            assert application.state.runtime_role == 'WEB'
            assert not application.state.background_jobs.tasks
            assert application.state.partner_lifecycle is not None
            assert application.state.payment_snapshots is not None
            assert application.state.dispatch_updates is not None
        assert database.closed

    asyncio.run(scenario())
    assert options['max_queries'] == 1 and options['min_size'] == 0


def test_bundle_is_stable_across_windows_and_linux_line_endings(tmp_path):
    fixture_checkout(tmp_path)
    source = tmp_path / 'main.py'
    source.write_bytes(b'app = None\r\n')
    first = bundle(runtime_files(tmp_path))
    source.write_bytes(b'app = None\n')
    assert bundle(runtime_files(tmp_path)) == first


def test_daemon_entrypoint_forces_worker_role_and_cleans_up_on_failure(monkeypatch):
    import os
    import sys
    from types import SimpleNamespace
    from backend.worker_runtime import serve

    closed = []
    monkeypatch.setenv('RUNTIME_ROLE', 'WEB')

    async def scenario():
        jobs = BackgroundJobs(True)

        async def failed():
            raise ValueError('synthetic worker failure')

        @asynccontextmanager
        async def lifecycle(application):
            assert os.environ['RUNTIME_ROLE'] == 'WORKER'
            jobs.start('synthetic', failed)
            try:
                yield
            finally:
                await jobs.close()
                closed.append(True)

        application = SimpleNamespace(state=SimpleNamespace(background_jobs=jobs),
                                      router=SimpleNamespace(lifespan_context=lifecycle))
        monkeypatch.setitem(sys.modules, 'main', SimpleNamespace(app=application))
        with pytest.raises(RuntimeError, match='Background job stopped'):
            await serve()
        assert closed == [True]

    asyncio.run(scenario())


def test_bundle_accepts_different_compression_of_identical_sources(tmp_path):
    import gzip

    fixture_checkout(tmp_path)
    prepare(tmp_path, write_bundle=True)
    target = tmp_path / 'deployment/worker/runtime.tar.gz'
    original = target.read_bytes()
    target.write_bytes(gzip.compress(gzip.decompress(original), compresslevel=1, mtime=123))
    assert target.read_bytes() != original
    prepare(tmp_path)


@pytest.mark.parametrize('fault', ['changed', 'missing', 'extra', 'duplicate', 'symlink', 'traversal', 'manifest', 'corrupt'])
def test_bundle_rejects_changed_contents_and_unsafe_members(tmp_path, fault):
    fixture_checkout(tmp_path)
    prepare(tmp_path, write_bundle=True)
    target = tmp_path / 'deployment/worker/runtime.tar.gz'
    files = runtime_files(tmp_path)
    if fault == 'manifest':
        (target.parent / 'source_manifest.json').write_text('{}', encoding='utf-8')
    elif fault == 'corrupt':
        target.write_bytes(b'not gzip')
    else:
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:gz') as archive:
            for name, data in files.items():
                if fault == 'missing' and name == 'main.py':
                    continue
                if fault == 'changed' and name == 'main.py':
                    data = b'x' * len(data)
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            if fault in {'extra', 'duplicate', 'symlink', 'traversal'}:
                name = {'extra': 'private.txt', 'duplicate': 'main.py',
                        'symlink': 'main.py', 'traversal': '../main.py'}[fault]
                member = tarfile.TarInfo(name)
                if fault == 'symlink':
                    member.type = tarfile.SYMTYPE
                    member.linkname = '/etc/passwd'
                archive.addfile(member, io.BytesIO(b''))
        target.write_bytes(output.getvalue())
    with pytest.raises(RuntimeError, match='stale or invalid'):
        prepare(tmp_path)
