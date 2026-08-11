from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl
import pytest
from arcticdb import Arctic, OutputFormat

from src.storage.arctic import (
    DAILY_PRICES,
    TICKER_UNIVERSE,
    read_daily_prices,
    read_table,
    read_ticker_universe,
    upsert_table,
    write_table,
)


def library(path: Path):
    arctic = Arctic(f"lmdb://{path}", output_format=OutputFormat.POLARS)
    return arctic.get_library("market_data", create_if_missing=True)


def universe_row(symbol: str, market_cap: float) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": [symbol],
            "company_name": [f"{symbol} Inc."],
            "security_type": ["common"],
            "exchange": ["NASDAQ"],
            "exchange_full_name": [None],
            "sector": ["Technology"],
            "industry": ["Consumer Electronics"],
            "country": ["US"],
            "currency": ["USD"],
            "market_cap": [market_cap],
            "beta": [1.0],
            "price": [200.0],
            "ipo_date": [date(1980, 12, 12)],
            "cik": ["0000320193"],
            "isin": ["US0378331005"],
            "cusip": ["037833100"],
            "is_etf": [False],
            "is_fund": [False],
            "is_adr": [False],
            "last_updated": [datetime(2026, 3, 22, tzinfo=timezone.utc)],
        },
        schema=TICKER_UNIVERSE.schema,
    )


def prices(symbol: str, day: str, close: float) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": [symbol],
            "date": [date.fromisoformat(day)],
            "open": [close],
            "high": [close],
            "low": [close],
            "close": [close],
            "volume": [100],
        },
        schema=DAILY_PRICES.schema,
    )


def test_read_missing_table_returns_typed_empty_frame(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")

    frame = read_table(market_data, TICKER_UNIVERSE)

    assert frame.is_empty()
    assert frame.schema == pl.Schema(TICKER_UNIVERSE.schema)


def test_universe_round_trips_dtypes_and_index(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")

    write_table(market_data, TICKER_UNIVERSE, universe_row("AAPL", 3e12))
    stored = read_table(market_data, TICKER_UNIVERSE)

    # The index column comes back named, and Date / tz-aware Datetime survive.
    assert stored.columns == TICKER_UNIVERSE.columns
    assert stored.schema == pl.Schema(TICKER_UNIVERSE.schema)
    assert stored["symbol"].item() == "AAPL"
    assert stored["ipo_date"].item() == date(1980, 12, 12)
    assert stored["last_updated"].item() == datetime(2026, 3, 22, tzinfo=timezone.utc)


def test_upsert_replaces_rows_sharing_a_key(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")

    upsert_table(market_data, DAILY_PRICES, prices("AAPL", "2025-01-02", 100))
    merged = upsert_table(market_data, DAILY_PRICES, prices("AAPL", "2025-01-02", 101))

    assert merged.height == 1
    assert read_table(market_data, DAILY_PRICES)["close"].item() == 101


def test_upsert_appends_new_keys_and_sorts(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")

    upsert_table(market_data, DAILY_PRICES, prices("MSFT", "2025-01-03", 200))
    upsert_table(market_data, DAILY_PRICES, prices("AAPL", "2025-01-02", 100))

    stored = read_table(market_data, DAILY_PRICES)
    assert stored.height == 2
    assert stored["symbol"].to_list() == ["AAPL", "MSFT"]  # sorted by (date, symbol)


def test_upsert_with_empty_frame_leaves_table_untouched(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")

    upsert_table(market_data, DAILY_PRICES, prices("AAPL", "2025-01-02", 100))
    result = upsert_table(
        market_data, DAILY_PRICES, pl.DataFrame(schema=DAILY_PRICES.schema)
    )

    assert result.height == 1
    assert result["close"].item() == 100


def multi_symbol_history(tmp_path: Path):
    market_data = library(tmp_path / "arcticdb")
    days = pl.date_range(date(2024, 1, 1), date(2024, 3, 31), "1d", eager=True)
    frame = pl.concat(
        [
            pl.DataFrame(
                {
                    "symbol": [sym] * len(days),
                    "date": days,
                    "open": [1.0] * len(days),
                    "high": [2.0] * len(days),
                    "low": [0.5] * len(days),
                    "close": [float(i)] * len(days),
                    "volume": [100] * len(days),
                },
                schema=DAILY_PRICES.schema,
            )
            for i, sym in enumerate(("AAPL", "MSFT", "NVDA"))
        ]
    )
    write_table(market_data, DAILY_PRICES, frame)
    return market_data, len(days)


def test_symbols_filter_is_pushed_down(tmp_path: Path) -> None:
    market_data, n_days = multi_symbol_history(tmp_path)

    frame = read_table(market_data, DAILY_PRICES, symbols="aapl")

    assert frame["symbol"].unique().to_list() == ["AAPL"]
    assert frame.height == n_days
    assert frame.columns == DAILY_PRICES.columns


def test_date_range_filter_is_pushed_down(tmp_path: Path) -> None:
    market_data, _ = multi_symbol_history(tmp_path)

    frame = read_table(
        market_data, DAILY_PRICES, date_range=(date(2024, 2, 1), date(2024, 2, 29))
    )

    assert frame["date"].min() == date(2024, 2, 1)
    assert frame["date"].max() == date(2024, 2, 29)
    assert frame.height == 29 * 3  # 2024 is a leap year, 3 symbols


def test_open_ended_date_range(tmp_path: Path) -> None:
    market_data, _ = multi_symbol_history(tmp_path)

    frame = read_daily_prices(market_data, start=date(2024, 3, 1))

    assert frame["date"].min() == date(2024, 3, 1)
    assert frame["date"].max() == date(2024, 3, 31)


def test_filters_combine(tmp_path: Path) -> None:
    market_data, _ = multi_symbol_history(tmp_path)

    frame = read_daily_prices(
        market_data,
        symbols=["AAPL", "NVDA"],
        start=date(2024, 1, 1),
        end=date(2024, 1, 10),
        columns=["close"],
    )

    assert sorted(frame["symbol"].unique().to_list()) == ["AAPL", "NVDA"]
    assert frame.height == 10 * 2
    # Index columns come back too, but unrequested data columns are not read.
    assert frame.columns == ["symbol", "date", "close"]


def test_unknown_column_raises(tmp_path: Path) -> None:
    market_data, _ = multi_symbol_history(tmp_path)

    with pytest.raises(ValueError, match="no column"):
        read_table(market_data, DAILY_PRICES, columns=["close", "typo"])


def test_date_range_on_non_time_indexed_table_raises(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")
    write_table(market_data, TICKER_UNIVERSE, universe_row("AAPL", 3e12))

    with pytest.raises(ValueError, match="not a time index"):
        read_table(market_data, TICKER_UNIVERSE, date_range=(date(2024, 1, 1), None))


def test_empty_symbols_list_short_circuits(tmp_path: Path) -> None:
    market_data, _ = multi_symbol_history(tmp_path)

    frame = read_table(market_data, DAILY_PRICES, symbols=[])

    assert frame.is_empty()
    assert frame.schema == pl.Schema(DAILY_PRICES.schema)


def test_symbols_filter_on_universe(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")
    write_table(
        market_data,
        TICKER_UNIVERSE,
        pl.concat([universe_row("AAPL", 3e12), universe_row("MSFT", 2e12)]),
    )

    frame = read_ticker_universe(market_data, symbols="MSFT", columns=["market_cap"])

    assert frame["symbol"].to_list() == ["MSFT"]
    assert frame.columns == ["symbol", "market_cap"]
