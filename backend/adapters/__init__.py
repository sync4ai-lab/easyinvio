"""Direct carrier extension points. No unverified carrier endpoint is registered."""
from dataclasses import dataclass
from typing import Any, Callable, Literal


@dataclass(frozen=True)
class DirectRegistration:
    code: Literal['royal_mail', 'evri']
    endpoint: str
    strategy_factory: Callable[..., Any]


# Intentionally empty until an issued carrier contract has a tested wire implementation.
# Environment switches alone cannot register a transport or bypass certification.
DIRECT_REGISTRATIONS: tuple[DirectRegistration, ...] = ()


def direct_registration(endpoint: str) -> DirectRegistration | None:
    return next((item for item in DIRECT_REGISTRATIONS if item.endpoint == endpoint.rstrip('/')), None)
