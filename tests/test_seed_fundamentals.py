from datetime import date
from pathlib import Path

import polars as pl
import pytest

from scripts import seed_fundamentals as seed
from src.vendors.fmp.fundamentals import INCOME_STATEMENT
from src.vendors.fmp.helpers import RateLimiter


UNTHROTTLED = RateLimiter(60_000.0)


def income_part(symbol: str, day: str) -> pl.DataFrame:
    """One row shaped exactly like a fetched statement part."""
    filled = {"date": date.fromisoformat(day), "symbol": symbol, "revenue": 1.0}

    return pl.DataFrame(
        {name: [filled.get(name)] for name in INCOME_STATEMENT.schema},
        schema=INCOME_STATEMENT.schema,
    )


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(seed, "CACHE_DIR", tmp_path / "fundamentals")

    return tmp_path / "fundamentals"


def stub_fetch(monkeypatch: pytest.MonkeyPatch, frame: pl.DataFrame) -> list[tuple]:
    """Replace the network call, recording every (year, period) it was asked for."""
    calls: list[tuple] = []

    def fake(statement, api_key, *, year, period, symbols=None, notify=None):
        calls.append((year, period))

        return frame

    monkeypatch.setattr(seed, "fetch_statement", fake)

    return calls


def test_first_run_fetches_and_writes_the_part(
    cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = stub_fetch(monkeypatch, income_part("AAPL", "2011-09-24"))

    frame = seed.cached_part(
        INCOME_STATEMENT,
        "key",
        year=2011,
        period="FY",
        symbols=["AAPL"],
        limiter=UNTHROTTLED,
    )

    assert calls == [(2011, "FY")]
    assert (cache / "income_statement_2011_FY.parquet").exists()
    assert frame["symbol"].to_list() == ["AAPL"]


def test_rerun_replays_the_cache_instead_of_the_network(
    cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = stub_fetch(monkeypatch, income_part("AAPL", "2011-09-24"))

    first = seed.cached_part(
        INCOME_STATEMENT,
        "key",
        year=2011,
        period="FY",
        symbols=["AAPL"],
        limiter=UNTHROTTLED,
    )
    second = seed.cached_part(
        INCOME_STATEMENT,
        "key",
        year=2011,
        period="FY",
        symbols=["AAPL"],
        limiter=UNTHROTTLED,
    )

    # This is the whole point: an interrupted seed costs one call, not two.
    assert calls == [(2011, "FY")]
    assert second.equals(first)


def test_a_crash_partway_leaves_finished_parts_on_disk(
    cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    part = income_part("AAPL", "2011-09-24")
    calls: list[tuple] = []

    def fails_on_the_third(
        statement, api_key, *, year, period, symbols=None, notify=None
    ):
        calls.append((year, period))
        if len(calls) == 3:
            raise RuntimeError("429 Too Many Requests")

        return part

    monkeypatch.setattr(seed, "fetch_statement", fails_on_the_third)

    with pytest.raises(RuntimeError):
        seed.collect(
            INCOME_STATEMENT,
            "key",
            years=range(2011, 2015),
            periods=("FY",),
            symbols=["AAPL"],
            limiter=UNTHROTTLED,
        )

    # The two parts that landed before the throttle are still there...
    assert sorted(p.name for p in cache.iterdir()) == [
        "income_statement_2011_FY.parquet",
        "income_statement_2012_FY.parquet",
    ]

    # ...so a rerun only pays for the three that never completed.
    calls.clear()
    monkeypatch.setattr(seed, "fetch_statement", lambda *a, **k: part)
    seed.collect(
        INCOME_STATEMENT,
        "key",
        years=range(2011, 2015),
        periods=("FY",),
        symbols=["AAPL"],
        limiter=UNTHROTTLED,
    )
    assert len(list(cache.iterdir())) == 4


def test_collect_dedupes_periods_that_span_two_year_buckets(
    cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A July-year-end filer comes back under both 2011 and 2012.
    stub_fetch(monkeypatch, income_part("AAPL", "2011-07-31"))

    frame = seed.collect(
        INCOME_STATEMENT,
        "key",
        years=range(2011, 2013),
        periods=("FY",),
        symbols=["AAPL"],
        limiter=UNTHROTTLED,
    )

    assert frame.height == 1
