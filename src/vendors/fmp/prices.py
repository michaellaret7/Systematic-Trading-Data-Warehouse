"""Daily OHLCV price history from FMP."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

import httpx
import polars as pl

from .helpers import (
    DEFAULT_REQUESTS_PER_MINUTE,
    FMP_BASE_URL,
    RateLimiter,
    get,
    http_client,
    normalize_symbols,
)


FMP_DAILY_URL = f"{FMP_BASE_URL}/historical-price-eod/full"

# Full OHLCV history; one HTTP call per symbol on the stable API.
# (FMP's multi-symbol historical endpoint is legacy and capped at 3 symbols.)
HISTORY_YEARS = 15

# Raw payload types; `date` arrives as a string and is cast below.
PRICE_SCHEMA: dict[str, Any] = {
    "symbol": pl.String,
    "date": pl.String,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Int64,
}

# Shape returned to callers.
DAILY_PRICES_SCHEMA: dict[str, Any] = {**PRICE_SCHEMA, "date": pl.Date}


def _empty_prices() -> pl.DataFrame:
    return pl.DataFrame(schema=DAILY_PRICES_SCHEMA)


def _history_start(years: int = HISTORY_YEARS, *, as_of: date | None = None) -> date:
    today = as_of or date.today()
    # date.replace can fail on Feb 29; timedelta is safer for long ranges.
    return today - timedelta(days=365 * years + years // 4)


def _rows_to_frame(symbol: str, rows: list[dict[str, Any]]) -> pl.DataFrame:
    if not rows:
        return _empty_prices()

    return pl.DataFrame(
        [
            {
                "symbol": symbol.upper(),
                "date": row["date"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            }
            for row in rows
        ],
        schema=PRICE_SCHEMA,
        strict=False,
    ).with_columns(pl.col("date").str.to_date())


def _fetch_symbol_prices(
    symbol: str,
    api_key: str,
    *,
    start: date | None = None,
    end: date | None = None,
    client: httpx.Client | None = None,
) -> pl.DataFrame:
    """Fetch one symbol's daily OHLCV from ``GET /stable/historical-price-eod/full``."""
    params: dict[str, str] = {"symbol": symbol.upper(), "apikey": api_key}
    if start is not None:
        params["from"] = start.isoformat()
    if end is not None:
        params["to"] = end.isoformat()

    rows = get(FMP_DAILY_URL, params, client=client).json()
    if not isinstance(rows, list):
        raise RuntimeError(f"Unexpected FMP response for {symbol}: {rows}")

    return _rows_to_frame(symbol, rows)


def fetch_daily_prices(
    tickers: str | Iterable[str],
    api_key: str,
    *,
    years: int = HISTORY_YEARS,
    start: date | None = None,
    end: date | None = None,
    requests_per_minute: float = DEFAULT_REQUESTS_PER_MINUTE,
    client: httpx.Client | None = None,
    on_error: str = "raise",
) -> pl.DataFrame:
    """Pull up to ``years`` of daily OHLCV for every ticker, rate-limited.

    FMP's stable daily history API is one symbol per request
    (``/stable/historical-price-eod/full``), so this walks the ticker list
    and calls that endpoint once per symbol, spacing requests to stay under
    ``requests_per_minute``. There is no separate single-symbol function:
    pass one ticker to fetch one symbol.

    Parameters
    ----------
    tickers:
        Equity symbols to download. A bare string counts as one ticker.
        Duplicates and casing differences are collapsed.
    api_key:
        FMP API key.
    years:
        Lookback window when ``start`` is omitted (default 15).
    start, end:
        Optional explicit date range. If ``start`` is None, it is derived
        from ``years`` (relative to ``end`` or today).
    requests_per_minute:
        Client-side throttle (default 250, under common paid plan caps).
    client:
        Optional shared ``httpx.Client`` (connection reuse).
    on_error:
        ``"raise"`` (default) re-raises HTTP/parse errors.
        ``"skip"`` logs nothing and continues with other symbols.

    Returns
    -------
    Polars DataFrame with columns:
    ``symbol, date, open, high, low, close, volume``.
    """
    if on_error not in {"raise", "skip"}:
        raise ValueError("on_error must be 'raise' or 'skip'")

    symbols = normalize_symbols(tickers)
    if not symbols:
        return _empty_prices()

    window_end = end or date.today()
    window_start = start if start is not None else _history_start(years, as_of=window_end)

    limiter = RateLimiter(requests_per_minute)
    frames: list[pl.DataFrame] = []

    with http_client(client) as http:
        for symbol in symbols:
            limiter.wait()
            try:
                frame = _fetch_symbol_prices(
                    symbol,
                    api_key,
                    start=window_start,
                    end=window_end,
                    client=http,
                )
            except Exception:
                if on_error == "raise":
                    raise
                continue
            if frame.height:
                frames.append(frame)

    if not frames:
        return _empty_prices()
    return pl.concat(frames, how="vertical_relaxed")
