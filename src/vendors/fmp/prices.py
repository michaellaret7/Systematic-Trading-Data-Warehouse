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
    RateLimiter,
    WaitFn,
    get,
    normalize_symbols,
)


# The one place this vendor reaches outside `/stable`. The stable EOD endpoint
# omits adjClose entirely, and its dividend-adjusted sibling returns *only*
# adjusted columns — so staying on stable would cost a second request per
# symbol. Legacy v3 returns raw OHLCV and adjClose together, halving a
# 9,400-ticker backfill. Its raw `close` matches stable's to the cent (verified
# across AAPL's full 15y history), so the unadjusted columns are unaffected by
# the choice. If FMP retires v3, switch to
# `/stable/historical-price-eod/{full,dividend-adjusted}` and join on date.
FMP_DAILY_URL = "https://financialmodelingprep.com/api/v3/historical-price-full"

# Full OHLCV history; one HTTP call per symbol.
#
# There is no bulk alternative for a multi-year backfill. FMP's `eod-bulk`
# endpoint serves one *date* at a time (no from/to — it 400s on a range), and
# the multi-symbol form of this endpoint takes at most 5 symbols and silently
# truncates any window to the trailing year, ignoring from/to without erroring.
HISTORY_YEARS = 15

# Unknown and delisted symbols come back as an empty `200 {}` rather than an
# error, so retries here are only ever about transient 429/502s on a long run.
MAX_ATTEMPTS = 5

DAILY_PRICES_SCHEMA: dict[str, Any] = {
    "symbol": pl.String,
    "date": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    #: Split- *and* dividend-adjusted close. `close` is only split-adjusted, so
    #: a total-return series has to be built from this column, not from `close`.
    "adj_close": pl.Float64,
    "volume": pl.Int64,
}

# The payload names this field in camelCase and hands `date` over as a string;
# both are fixed on the way in.
_RAW_SCHEMA = {
    **{
        name: dtype
        for name, dtype in DAILY_PRICES_SCHEMA.items()
        if name != "adj_close"
    },
    "date": pl.String,
    "adjClose": pl.Float64,
}


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
    max_attempts: int,
    wait: WaitFn | None,
) -> pl.DataFrame:
    """Fetch one symbol's daily OHLCV and adjusted close from FMP."""
    payload = get(
        f"{FMP_DAILY_URL}/{symbol}",
        {
            "apikey": api_key,
            "from": start.isoformat(),
            "to": end.isoformat(),
        },
        client=client,
        max_attempts=max_attempts,
        wait=wait,
    ).json()

    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected FMP response for {symbol}: {payload}")

    # An unknown or delisted symbol answers with a bare `{}`, not an error.
    rows = payload.get("historical", [])

    return (
        pl.DataFrame(rows, schema=_RAW_SCHEMA, strict=False)
        .with_columns(
            pl.lit(symbol).alias("symbol"),
            pl.col("date").str.to_date(),
        )
        .rename({"adjClose": "adj_close"})
        .select(list(DAILY_PRICES_SCHEMA))
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
    max_attempts: int = MAX_ATTEMPTS,
    wait: WaitFn | None = None,
) -> pl.DataFrame:
    """Pull up to ``years`` of daily OHLCV and adjusted close per ticker.

    Usable multi-symbol and bulk forms do not exist (see ``FMP_DAILY_URL``), so
    this calls the endpoint once per ticker, rate-limited; a bare string counts
    as one ticker.
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
                    symbol,
                    api_key,
                    start=window_start,
                    end=window_end,
                    client=http,
                    max_attempts=max_attempts,
                    wait=wait,
                )
            )

    return pl.concat(frames)
