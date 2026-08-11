from datetime import date
from pathlib import Path
from unittest.mock import patch

import polars as pl
from arcticdb import Arctic, OutputFormat

from src.jobs.update_equities import update_daily_prices
from src.storage.arctic import DAILY_PRICES_SYMBOL, read_daily_prices


def prices(*rows: tuple[str, str, float]) -> pl.DataFrame:
    """Build a price frame shaped like fetch_daily_prices' batch output."""
    return pl.DataFrame(
        {
            "symbol": [symbol for symbol, _, _ in rows],
            "date": [date.fromisoformat(day) for _, day, _ in rows],
            "open": [close for _, _, close in rows],
            "high": [close for _, _, close in rows],
            "low": [close for _, _, close in rows],
            "close": [close for _, _, close in rows],
            "volume": [100] * len(rows),
        }
    )


def library(path: Path):
    arctic = Arctic(f"lmdb://{path}", output_format=OutputFormat.POLARS)
    return arctic.get_library("market_data", create_if_missing=True)


def test_all_tickers_are_written_to_one_arcticdb_symbol(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")

    batch = prices(("AAPL", "2025-01-02", 100), ("MSFT", "2025-01-02", 200))
    with patch(
        "src.jobs.update_equities.fetch_daily_prices",
        return_value=batch,
    ) as fetch:
        update_daily_prices(["AAPL", "MSFT"], "test-key", market_data)

    # One batch call covers every ticker.
    assert fetch.call_count == 1
    assert fetch.call_args.args[0] == ["AAPL", "MSFT"]

    stored = read_daily_prices(market_data)
    assert stored.height == 2
    assert set(stored["symbol"]) == {"AAPL", "MSFT"}
    assert market_data.list_symbols() == [DAILY_PRICES_SYMBOL]


def test_update_replaces_the_same_ticker_and_date(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")

    with patch(
        "src.jobs.update_equities.fetch_daily_prices",
        side_effect=[
            prices(("AAPL", "2025-01-02", 100)),
            prices(("AAPL", "2025-01-02", 101)),
        ],
    ):
        update_daily_prices("AAPL", "test-key", market_data)  # single ticker
        update_daily_prices("AAPL", "test-key", market_data)

    stored = read_daily_prices(market_data)
    assert stored.height == 1
    assert stored["close"].item() == 101
