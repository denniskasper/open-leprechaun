"""What asking each data provider came to (ticket 55), recorded where the
asking happens so the health panel can say which provider is failing — and
since when it last answered — without anyone opening a log.

A provider is known here by its name alone. A failure keeps the two
conditions the price ports name apart (ADR-0018): a rate limit asks for
patience, an outage for a look. The sentence stored is the port's own for a
failure it named; anything else a provider raised is recorded by its type,
because a stray exception's message promises nothing about what it carries
(ADR-0003).
"""

from collections.abc import Callable, Collection, Mapping
from datetime import UTC, datetime

from sqlalchemy import Engine

from open_leprechaun.ports.crypto_prices import ProviderOutageError, RateLimitedError
from open_leprechaun.repositories import provider_status


def ask[Answer](
    engine: Engine, provider: str, call: Callable[[], Answer], *, about_one_instrument: bool = False
) -> Answer:
    """Make one call to a provider and record how it went. Whatever the call
    raises is raised on unchanged — recording never decides what a failure
    means to the caller.

    A request `about_one_instrument` — its history, say — fails like an
    outage when the provider merely does not know that Instrument, so such a
    failure is not put on the provider's record; a rate limit is the
    provider's word whatever was asked, and always is."""
    try:
        answer = call()
    except Exception as failure:
        if not about_one_instrument or isinstance(failure, RateLimitedError):
            failed(engine, provider, failure)
        raise
    answered(engine, provider)
    return answer


def answered(engine: Engine, provider: str) -> None:
    provider_status.record_success(engine, provider, at=datetime.now(UTC))


def failed(engine: Engine, provider: str, failure: Exception) -> None:
    named = isinstance(failure, (RateLimitedError, ProviderOutageError)) and str(failure)
    provider_status.record_failure(
        engine,
        provider,
        condition="rate_limited" if isinstance(failure, RateLimitedError) else "outage",
        error=str(failure) if named else f"{provider} failed with {type(failure).__name__}.",
        at=datetime.now(UTC),
    )


def state_affected(engine: Engine, left_stale: Mapping[str, Collection[int]]) -> None:
    """What a price refresh found, per provider it could have asked: the
    Instruments left without a fresh price while that provider was failing —
    none for a provider that answered, or that the refresh never needed."""
    for provider, instrument_ids in left_stale.items():
        provider_status.replace_affected(engine, provider, instrument_ids)
