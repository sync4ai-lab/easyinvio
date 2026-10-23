"""Dedicated queue consumer. Run with python -m backend.worker_runtime."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from contextlib import suppress


async def serve() -> None:
    # Must precede importing main: the daemon shares Vercel's environment with
    # the HTTP function, but always owns the WORKER role.
    os.environ['RUNTIME_ROLE'] = 'WORKER'
    from main import app

    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    previous = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, shutdown.set)
            installed.append(sig)
        except NotImplementedError:
            previous[sig] = signal.getsignal(sig)
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(shutdown.set))
    try:
        async with app.router.lifespan_context(app):
            logging.getLogger(__name__).info('EasyInvio worker started; continuous jobs=%d',
                                            len(app.state.background_jobs.tasks))
            stop = asyncio.create_task(shutdown.wait())
            failure = asyncio.create_task(app.state.background_jobs.wait_for_failure())
            try:
                done, _ = await asyncio.wait((stop, failure), return_when=asyncio.FIRST_COMPLETED)
                if failure in done:
                    await failure
            finally:
                stop.cancel()
                failure.cancel()
                await asyncio.gather(stop, failure, return_exceptions=True)
    finally:
        for sig in installed:
            loop.remove_signal_handler(sig)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with suppress(KeyboardInterrupt):
        asyncio.run(serve())


if __name__ == '__main__':
    main()
