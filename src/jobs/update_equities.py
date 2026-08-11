"""Fetch daily OHLCV from FMP and merge it into the `daily_prices` table.

Run as ``uv run python -m src.jobs.update_equities AAPL MSFT``. One call
covers every ticker passed.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable

from arcticdb.version_store.library import Library

from src.config import require
from src.storage.arctic import DAILY_PRICES, connect, upsert
from src.vendors.fmp import fetch_daily_prices


def update_daily_prices(
    tickers: str | Iterable[str],
    api_key: str,
    library: Library,
) -> int:
    """Fetch daily OHLCV for ``tickers`` and upsert it on ``(date, symbol)``.

    Returns the number of rows fetched. A bare string counts as one ticker.
    """
    prices = fetch_daily_prices(tickers, api_key)

    upsert(library, DAILY_PRICES, prices)

    return prices.height


def main(argv: list[str]) -> None:
    if not argv:
        raise SystemExit(
            "Usage: python -m src.jobs.update_equities TICKER [TICKER ...]"
        )

    (api_key,) = require("FMP_API_KEY")

    rows = update_daily_prices(argv, api_key, connect())

    print(
        f"Upserted {rows:,} rows into '{DAILY_PRICES.symbol}' for {len(argv)} ticker(s)"
    )


if __name__ == "__main__":
    main(sys.argv[1:])
