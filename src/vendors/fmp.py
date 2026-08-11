from datetime import date

import httpx
import polars as pl


FMP_URL = "https://financialmodelingprep.com/stable/historical-price-eod/full"


def fetch_daily_prices(
    symbol: str,
    api_key: str,
    start: date | None = None,
) -> pl.DataFrame:
    """Fetch one symbol's daily OHLCV history from FMP."""
    params = {"symbol": symbol.upper(), "apikey": api_key}
    if start:
        params["from"] = start.isoformat()

    response = httpx.get(FMP_URL, params=params, timeout=30)
    response.raise_for_status()

    rows = response.json()
    if not isinstance(rows, list):
        raise RuntimeError(f"Unexpected FMP response: {rows}")

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
        schema={
            "symbol": pl.String,
            "date": pl.String,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Int64,
        },
        strict=False,
    ).with_columns(pl.col("date").str.to_date())
