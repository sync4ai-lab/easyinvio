"""Bounded direct-first routing without sacrificing uncovered carrier options."""
import asyncio
from typing import Any, Callable, Awaitable

from backend.adapters import direct_registration
from backend.aggregator_registry import identify_aggregator
from backend.carrier_consolidation import carrier_identity, service_identity
from backend.integration_policy import integration_code


def service_key(rate: Any) -> tuple[str, str, str]:
    return (carrier_identity(rate.carrier_code), service_identity(rate.carrier_code, rate.service_code), rate.currency)


async def run_tiered_providers(
    strategies: list[Any], physical_request: Any, billable_request: Any,
    run_provider: Callable[..., Awaitable[tuple[list[Any], Any]]], deadline: float,
) -> list[tuple[list[Any], Any]]:
    primary, secondary = [], []
    for strategy in strategies:
        endpoint = getattr(strategy.account, 'base_url', '')
        (primary if direct_registration(endpoint) or integration_code(endpoint) in {'royal_mail', 'evri'} else secondary).append(strategy)

    # Shared wall-clock tier budget, including semaphore admission. run_provider
    # owns each timeout and converts failures into the existing diagnostic model.
    results = list(await asyncio.gather(*(
        run_provider(strategy, physical_request, min(2.2, deadline)) for strategy in primary
    )))
    direct_keys = {
        service_key(rate)
        for rates, _ in results for rate in rates
    }
    fallback = await asyncio.gather(*(
        run_provider(strategy,
                     physical_request if identify_aggregator(getattr(strategy.account, 'base_url', '')) else billable_request,
                     deadline)
        for strategy in secondary
    ))
    # Multi-carrier aggregator APIs do not generally accept service exclusion
    # lists. Keep querying them for uncovered services, but drop exact native
    # equivalents. Never suppress an entire aggregator because one carrier worked.
    for rates, issue in fallback:
        results.append(([rate for rate in rates if
                         service_key(rate) not in direct_keys], issue))
    return results
