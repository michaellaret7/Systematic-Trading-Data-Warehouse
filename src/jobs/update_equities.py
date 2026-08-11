"""Fetch daily OHLCV from FMP and merge it into the `daily_prices` table.

Run as ``uv run python -m src.jobs.update_equities AAPL MSFT``. One call
covers every ticker passed.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable

from arcticdb.version_store.library import Library
from dotenv import load_dotenv

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
    load_dotenv()

    if not argv:
        raise SystemExit(
            "Usage: python -m src.jobs.update_equities TICKER [TICKER ...]"
        )

    missing = [
        name
        for name in ("FMP_API_KEY", "S3_BUCKET", "AWS_DEFAULT_REGION")
        if not os.environ.get(name)
    ]
    if missing:
        raise RuntimeError(f"Set {', '.join(missing)} before running update_equities")

    library = connect(os.environ["S3_BUCKET"], os.environ["AWS_DEFAULT_REGION"])

    rows = update_daily_prices(argv, os.environ["FMP_API_KEY"], library)

    print(
        f"Upserted {rows:,} rows into '{DAILY_PRICES.symbol}' for {len(argv)} ticker(s)"
    )


if __name__ == "__main__":
    main(sys.argv[1:])
