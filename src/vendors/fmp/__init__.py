"""Financial Modeling Prep (FMP) market-data client.

One module per dataset, so new data types slot in alongside these:

* ``helpers``      — shared HTTP, throttling, and value-coercion utilities
* ``prices``       — daily OHLCV history
* ``profiles``     — company profiles / ticker universe
* ``fundamentals`` — income, balance sheet, cash flow, and ratios
"""

from .fundamentals import (
    ANNUAL_PERIODS,
    BALANCE_SHEET,
    BALANCE_SHEET_SCHEMA,
    CASH_FLOW,
    CASH_FLOW_SCHEMA,
    INCOME_STATEMENT,
    INCOME_STATEMENT_SCHEMA,
    QUARTERLY_PERIODS,
    RATIOS,
    RATIOS_SCHEMA,
    fetch_statements,
)
from .prices import DAILY_PRICES_SCHEMA, fetch_daily_prices
from .profiles import TICKER_UNIVERSE_SCHEMA, fetch_ticker_universe

__all__ = [
    "ANNUAL_PERIODS",
    "BALANCE_SHEET",
    "BALANCE_SHEET_SCHEMA",
    "CASH_FLOW",
    "CASH_FLOW_SCHEMA",
    "DAILY_PRICES_SCHEMA",
    "INCOME_STATEMENT",
    "INCOME_STATEMENT_SCHEMA",
    "QUARTERLY_PERIODS",
    "RATIOS",
    "RATIOS_SCHEMA",
    "TICKER_UNIVERSE_SCHEMA",
    "fetch_daily_prices",
    "fetch_statements",
    "fetch_ticker_universe",
]
