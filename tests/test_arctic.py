from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl
import pytest
from arcticdb import Arctic, OutputFormat, QueryBuilder

from src.storage.arctic import (
    DAILY_PRICES,
    TICKER_UNIVERSE,
    read,
    upsert,
    write,
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


def test_read_missing_dataset_returns_typed_empty_frame(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")

    frame = read(market_data, TICKER_UNIVERSE)

    assert frame.is_empty()
    assert frame.schema == pl.Schema(TICKER_UNIVERSE.schema)


def test_universe_round_trips_dtypes(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")

    write(market_data, TICKER_UNIVERSE, universe_row("AAPL", 3e12))
    stored = read(market_data, TICKER_UNIVERSE)

    # ArcticDB widens every temporal column to naive datetime[ns]; Date and the
    # tz-aware timestamp have to survive the cast back.
    assert stored.columns == TICKER_UNIVERSE.columns
    assert stored.schema == pl.Schema(TICKER_UNIVERSE.schema)
    assert stored["symbol"].item() == "AAPL"
    assert stored["ipo_date"].item() == date(1980, 12, 12)
    assert stored["last_updated"].item() == datetime(2026, 3, 22, tzinfo=timezone.utc)


def test_prices_round_trip_keeps_date_as_a_named_column(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")

    write(market_data, DAILY_PRICES, prices("AAPL", "2025-01-02", 100))
    stored = read(market_data, DAILY_PRICES)

    # `date` is the pandas index on the way in and must come back under its own
    # name, not as `index` / `level_0`.
    assert stored.columns == DAILY_PRICES.columns
    assert stored.schema == pl.Schema(DAILY_PRICES.schema)
    assert stored["date"].item() == date(2025, 1, 2)


def test_upsert_replaces_rows_sharing_a_key(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")

    upsert(market_data, DAILY_PRICES, prices("AAPL", "2025-01-02", 100))
    upsert(market_data, DAILY_PRICES, prices("AAPL", "2025-01-02", 101))

    stored = read(market_data, DAILY_PRICES)
    assert stored.height == 1
    assert stored["close"].item() == 101


def test_upsert_appends_new_keys_and_sorts(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")

    upsert(market_data, DAILY_PRICES, prices("MSFT", "2025-01-03", 200))
    upsert(market_data, DAILY_PRICES, prices("AAPL", "2025-01-02", 100))

    stored = read(market_data, DAILY_PRICES)
    assert stored.height == 2
    assert stored["symbol"].to_list() == ["AAPL", "MSFT"]  # sorted by (date, symbol)


def test_upsert_leaves_rows_outside_the_touched_range_alone(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")
    write(
        market_data,
        DAILY_PRICES,
        pl.concat(
            [
                prices("AAPL", "2025-01-02", 100),
                prices("MSFT", "2025-01-02", 200),
                prices("AAPL", "2025-01-06", 106),
            ]
        ),
    )

    # Refreshing AAPL on the 2nd must not evict MSFT, which shares that date.
    upsert(market_data, DAILY_PRICES, prices("AAPL", "2025-01-02", 999))

    stored = read(market_data, DAILY_PRICES)
    assert stored.height == 3
    assert stored.filter(pl.col("symbol") == "MSFT")["close"].item() == 200
    assert stored.filter(pl.col("date") == date(2025, 1, 6))["close"].item() == 106


def test_upsert_of_the_universe_merges_on_symbol(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")

    upsert(market_data, TICKER_UNIVERSE, universe_row("AAPL", 3e12))
    upsert(market_data, TICKER_UNIVERSE, universe_row("MSFT", 2e12))
    upsert(market_data, TICKER_UNIVERSE, universe_row("AAPL", 4e12))

    stored = read(market_data, TICKER_UNIVERSE)
    assert stored["symbol"].to_list() == ["AAPL", "MSFT"]
    assert stored.filter(pl.col("symbol") == "AAPL")["market_cap"].item() == 4e12


def test_upsert_with_empty_frame_leaves_dataset_untouched(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")

    upsert(market_data, DAILY_PRICES, prices("AAPL", "2025-01-02", 100))
    upsert(market_data, DAILY_PRICES, pl.DataFrame(schema=DAILY_PRICES.schema))

    stored = read(market_data, DAILY_PRICES)
    assert stored.height == 1
    assert stored["close"].item() == 100


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
    write(market_data, DAILY_PRICES, frame)
    return market_data, len(days)


def test_symbols_filter_is_pushed_down(tmp_path: Path) -> None:
    market_data, n_days = multi_symbol_history(tmp_path)

    frame = read(market_data, DAILY_PRICES, symbols="aapl")

    assert frame["symbol"].unique().to_list() == ["AAPL"]
    assert frame.height == n_days
    assert frame.columns == DAILY_PRICES.columns


def test_date_range_filter_is_pushed_down(tmp_path: Path) -> None:
    market_data, _ = multi_symbol_history(tmp_path)

    frame = read(
        market_data, DAILY_PRICES, start=date(2024, 2, 1), end=date(2024, 2, 29)
    )

    assert frame["date"].min() == date(2024, 2, 1)
    assert frame["date"].max() == date(2024, 2, 29)
    assert frame.height == 29 * 3  # 2024 is a leap year, 3 symbols


def test_open_ended_date_range(tmp_path: Path) -> None:
    market_data, _ = multi_symbol_history(tmp_path)

    frame = read(market_data, DAILY_PRICES, start=date(2024, 3, 1))

    assert frame["date"].min() == date(2024, 3, 1)
    assert frame["date"].max() == date(2024, 3, 31)


def test_filters_combine(tmp_path: Path) -> None:
    market_data, _ = multi_symbol_history(tmp_path)

    frame = read(
        market_data,
        DAILY_PRICES,
        symbols=["AAPL", "NVDA"],
        start=date(2024, 1, 1),
        end=date(2024, 1, 10),
        columns=["close"],
    )

    assert sorted(frame["symbol"].unique().to_list()) == ["AAPL", "NVDA"]
    assert frame.height == 10 * 2
    # Key columns come back too, but unrequested data columns are not read.
    assert frame.columns == ["symbol", "date", "close"]


def test_where_takes_a_raw_query_builder(tmp_path: Path) -> None:
    market_data, _ = multi_symbol_history(tmp_path)

    builder = QueryBuilder()
    frame = read(market_data, DAILY_PRICES, where=builder[builder["close"] > 1.0])

    assert frame["symbol"].unique().to_list() == ["NVDA"]  # close == 2.0


def test_where_combines_with_symbols(tmp_path: Path) -> None:
    market_data, _ = multi_symbol_history(tmp_path)

    builder = QueryBuilder()
    frame = read(
        market_data,
        DAILY_PRICES,
        symbols=["AAPL", "NVDA"],
        where=builder[builder["close"] > 1.0],
    )

    assert frame["symbol"].unique().to_list() == ["NVDA"]


def test_unknown_column_raises(tmp_path: Path) -> None:
    market_data, _ = multi_symbol_history(tmp_path)

    with pytest.raises(ValueError, match="no column"):
        read(market_data, DAILY_PRICES, columns=["close", "typo"])


def test_date_range_on_dataset_without_a_time_index_raises(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")
    write(market_data, TICKER_UNIVERSE, universe_row("AAPL", 3e12))

    with pytest.raises(ValueError, match="not a time index"):
        read(market_data, TICKER_UNIVERSE, start=date(2024, 1, 1))


def test_empty_symbols_list_short_circuits(tmp_path: Path) -> None:
    market_data, _ = multi_symbol_history(tmp_path)

    frame = read(market_data, DAILY_PRICES, symbols=[])

    assert frame.is_empty()
    assert frame.schema == pl.Schema(DAILY_PRICES.schema)


def test_symbols_filter_on_universe(tmp_path: Path) -> None:
    market_data = library(tmp_path / "arcticdb")
    write(
        market_data,
        TICKER_UNIVERSE,
        pl.concat([universe_row("AAPL", 3e12), universe_row("MSFT", 2e12)]),
    )

    frame = read(market_data, TICKER_UNIVERSE, symbols="MSFT", columns=["market_cap"])

    assert frame["symbol"].to_list() == ["MSFT"]
    assert frame.columns == ["symbol", "market_cap"]
