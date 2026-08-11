"""Financial Modeling Prep (FMP) market-data client.

One module per dataset, so new data types slot in alongside these:

* ``helpers``  — shared HTTP, throttling, and value-coercion utilities
* ``prices``   — daily OHLCV history
* ``profiles`` — company profiles / ticker universe
"""

from .prices import DAILY_PRICES_SCHEMA, fetch_daily_prices
from .profiles import TICKER_UNIVERSE_SCHEMA, fetch_ticker_universe

__all__ = [
    "DAILY_PRICES_SCHEMA",
    "TICKER_UNIVERSE_SCHEMA",
    "fetch_daily_prices",
    "fetch_ticker_universe",
]
