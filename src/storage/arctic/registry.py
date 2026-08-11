"""Concrete dataset declarations for the market_data library."""

from __future__ import annotations

from typing import Any

from src.storage.arctic.dataset import Dataset
from src.vendors.fmp import (
    BALANCE_SHEET_SCHEMA,
    CASH_FLOW_SCHEMA,
    DAILY_PRICES_SCHEMA,
    INCOME_STATEMENT_SCHEMA,
    RATIOS_SCHEMA,
    TICKER_UNIVERSE_SCHEMA,
)


# ====================================
# --> Helper funcs
# ====================================


def _by_cadence(name: str, schema: dict[str, Any]) -> tuple[Dataset, Dataset]:
    """The annual and quarterly tables for one financial statement.

    Both cadences share a schema and are keyed on the period end date, so the
    only thing that differs is the symbol they are stored under.
    """
    return tuple(
        Dataset(
            symbol=f"{name}_{cadence}", 
            schema=schema, 
            key=("date", "symbol")
        )
        for cadence in ("annual", "quarterly")
    )


# ====================================
# --> Dataset declarations
# ====================================


DAILY_PRICES = Dataset(
    symbol="daily_prices",
    schema=DAILY_PRICES_SCHEMA,
    key=("date", "symbol"),
)

TICKER_UNIVERSE = Dataset(
    symbol="ticker_universe",
    schema=TICKER_UNIVERSE_SCHEMA,
    key=("symbol",),
)

INCOME_STATEMENT_ANNUAL, INCOME_STATEMENT_QUARTERLY = _by_cadence(
    "income_statement", 
    INCOME_STATEMENT_SCHEMA
)
BALANCE_SHEET_ANNUAL, BALANCE_SHEET_QUARTERLY = _by_cadence(
    "balance_sheet", 
    BALANCE_SHEET_SCHEMA
)
CASH_FLOW_ANNUAL, CASH_FLOW_QUARTERLY = _by_cadence("cash_flow", CASH_FLOW_SCHEMA)
RATIOS_ANNUAL, RATIOS_QUARTERLY = _by_cadence("ratios", RATIOS_SCHEMA)
