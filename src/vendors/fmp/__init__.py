"""Financial Modeling Prep (FMP) market-data client.

One module per dataset, so new data types slot in alongside these:

* ``helpers``  — shared HTTP, throttling, and value-coercion utilities
* ``prices``   — daily OHLCV history
* ``profiles`` — company profiles / ticker universe
"""

from .helpers import DEFAULT_REQUESTS_PER_MINUTE, FMP_BASE_URL, RateLimiter
from .prices import (
    DAILY_PRICES_SCHEMA,
    FMP_DAILY_URL,
    HISTORY_YEARS,
    PRICE_SCHEMA,
    fetch_daily_prices,
)
from .profiles import (
    DEFAULT_SECURITY_TYPES,
    EXCLUDED_INDUSTRIES,
    FMP_PROFILE_BULK_URL,
    PROFILE_BULK_MAX_ATTEMPTS,
    PROFILE_BULK_MAX_PARTS,
    PROFILE_BULK_MIN_INTERVAL_SECONDS,
    PROFILE_BULK_SUGGESTED_INTERVAL_SECONDS,
    SECURITY_TYPES,
    TICKER_UNIVERSE_SCHEMA,
    US_LISTED_EXCHANGES,
    classify_security,
    fetch_profile_bulk_part,
    fetch_ticker_universe,
)

__all__ = [
    "DAILY_PRICES_SCHEMA",
    "DEFAULT_REQUESTS_PER_MINUTE",
    "DEFAULT_SECURITY_TYPES",
    "EXCLUDED_INDUSTRIES",
    "FMP_BASE_URL",
    "FMP_DAILY_URL",
    "FMP_PROFILE_BULK_URL",
    "HISTORY_YEARS",
    "PRICE_SCHEMA",
    "PROFILE_BULK_MAX_ATTEMPTS",
    "PROFILE_BULK_MAX_PARTS",
    "PROFILE_BULK_MIN_INTERVAL_SECONDS",
    "PROFILE_BULK_SUGGESTED_INTERVAL_SECONDS",
    "RateLimiter",
    "SECURITY_TYPES",
    "TICKER_UNIVERSE_SCHEMA",
    "US_LISTED_EXCHANGES",
    "classify_security",
    "fetch_daily_prices",
    "fetch_profile_bulk_part",
    "fetch_ticker_universe",
]
