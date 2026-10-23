"""Process roles and supervised continuous jobs, independent of provider logic."""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Mapping
from typing import Any, Literal

RuntimeRole = Literal['AUTO', 'COMBINED', 'WEB', 'WORKER']


def resolve_role(role: RuntimeRole, environment: Mapping[str, str]) -> RuntimeRole:
    if role != 'AUTO':
        return role
    return 'WEB' if environment.get('VERCEL') == '1' else 'COMBINED'


def pool_options(role: RuntimeRole, configured_max: int, worker_max: int) -> dict[str, Any]:
    if role == 'WEB':
        # Session locks must remain on the SAME acquired connection. Close that
        # connection only on release; never switch this app to transaction mode.
        return {'min_size': 0, 'max_size': min(2, configured_max),
                'max_queries': 1, 'max_inactive_connection_lifetime': 5.0}
    if role == 'WORKER':
        return {'min_size': 1, 'max_size': worker_max,
                'max_inactive_connection_lifetime': 30.0}
    return {'min_size': 1, 'max_size': max(2, configured_max - 1)}


class BackgroundJobs:
    """Do not even construct worker coroutines in web processes."""

    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.tasks: list[asyncio.Task[None]] = []

    def start(self, name: str, factory: Callable[[], Coroutine[Any, Any, None]],
              *, enabled: bool = True) -> None:
        if self.enabled and enabled:
            self.tasks.append(asyncio.create_task(factory(), name=name))

    async def close(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()

    async def wait_for_failure(self) -> None:
        if not self.tasks:
            raise RuntimeError('No background jobs were started')
        completed, _ = await asyncio.wait(self.tasks, return_when=asyncio.FIRST_COMPLETED)
        task = next(iter(completed))
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                raise RuntimeError(f'Background job stopped: {task.get_name()}') from error
        raise RuntimeError(f'Background job stopped: {task.get_name()}')
