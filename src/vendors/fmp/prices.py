"""Daily OHLCV price history from FMP."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import nullcontext
from datetime import date, timedelta
from typing import Any

import httpx
import polars as pl

from .helpers import (
    DEFAULT_REQUESTS_PER_MINUTE,
    DEFAULT_TIMEOUT_SECONDS,
    FMP_BASE_URL,
    RateLimiter,
    get,
    normalize_symbols,
)


FMP_DAILY_URL = f"{FMP_BASE_URL}/historical-price-eod/full"

# Full OHLCV history; one HTTP call per symbol on the stable API.
# (FMP's multi-symbol historical endpoint is legacy and capped at 3 symbols.)
HISTORY_YEARS = 15

DAILY_PRICES_SCHEMA: dict[str, Any] = {
    "symbol": pl.String,
    "date": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Int64,
}

# `date` arrives from the payload as a string and is cast on the way in.
_RAW_SCHEMA = {**DAILY_PRICES_SCHEMA, "date": pl.String}


# ====================================
# --> Helper funcs
# ====================================


def _history_start(years: int, *, as_of: date) -> date:
    # date.replace can fail on Feb 29; timedelta is safer for long ranges.
    return as_of - timedelta(days=365 * years + years // 4)


def _fetch_symbol(
    symbol: str,
    api_key: str,
    *,
    start: date,
    end: date,
    client: httpx.Client,
) -> pl.DataFrame:
    """Fetch one symbol's daily OHLCV from ``/stable/historical-price-eod/full``."""
    rows = get(
        FMP_DAILY_URL,
        {
            "symbol": symbol,
            "apikey": api_key,
            "from": start.isoformat(),
            "to": end.isoformat(),
        },
        client=client,
    ).json()

    if not isinstance(rows, list):
        raise RuntimeError(f"Unexpected FMP response for {symbol}: {rows}")

    return pl.DataFrame(rows, schema=_RAW_SCHEMA, strict=False).with_columns(
        pl.lit(symbol).alias("symbol"),
        pl.col("date").str.to_date(),
    )


# ====================================
# --> Fetch
# ====================================


def fetch_daily_prices(
    tickers: str | Iterable[str],
    api_key: str,
    *,
    years: int = HISTORY_YEARS,
    start: date | None = None,
    end: date | None = None,
    requests_per_minute: float = DEFAULT_REQUESTS_PER_MINUTE,
    client: httpx.Client | None = None,
) -> pl.DataFrame:
    """Pull up to ``years`` of daily OHLCV for every ticker, rate-limited.

    FMP's stable daily-history endpoint takes one symbol per request, so this
    calls it once per ticker; a bare string counts as one ticker.
    """
    symbols = normalize_symbols(tickers)
    if not symbols:
        return pl.DataFrame(schema=DAILY_PRICES_SCHEMA)

    window_end = end or date.today()
    window_start = start or _history_start(years, as_of=window_end)

    limiter = RateLimiter(requests_per_minute)
    session = (
        nullcontext(client) if client else httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS)
    )

    with session as http:
        frames = []

        for symbol in symbols:
            limiter.wait()

            frames.append(
                _fetch_symbol(
                    symbol, api_key, start=window_start, end=window_end, client=http
                )
            )

    return pl.concat(frames)
