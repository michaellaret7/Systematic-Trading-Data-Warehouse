import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx
import polars as pl
import pytest
from arcticdb import Arctic, OutputFormat

from scripts.seed_daily_prices import load, stage
from src.storage.arctic import DAILY_PRICES, read

# Fast enough that the rate limiter never actually sleeps in a test.
UNTHROTTLED = 60_000.0


def library(path: Path):
    arctic = Arctic(f"lmdb://{path}", output_format=OutputFormat.POLARS)
    return arctic.get_library("market_data", create_if_missing=True)


def eod_rows(days: list[str], close: float) -> list[dict]:
    return [
        {
            "date": day,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "adjClose": close * 0.97,
            "volume": 1_000,
        }
        for day in days
    ]


def fmp_handler(
    history: dict[str, list[dict]],
    *,
    fail: set[str] | None = None,
    calls: list[str] | None = None,
):
    """A MockTransport handler serving `history`, 500ing for symbols in `fail`."""
    broken = fail or set()

    def handle(request: httpx.Request) -> httpx.Response:
        # This endpoint carries the symbol in the path, not the query string.
        symbol = request.url.path.rsplit("/", 1)[-1]

        if calls is not None:
            calls.append(symbol)

        if symbol in broken:
            return httpx.Response(500, json={"Error": "boom"})

        rows = history.get(symbol)

        # FMP answers `200 {}` for unknown and delisted tickers.
        if rows is None:
            return httpx.Response(200, json={})

        return httpx.Response(200, json={"symbol": symbol, "historical": rows})

    return handle


def patched_client(handler):
    """Patch the client `stage` opens so requests hit `handler` instead of FMP.

    `httpx.Client` is captured up front: patching the attribute rebinds it on
    the shared `httpx` module, so building the replacement lazily would make
    the factory call itself.
    """
    real_client = httpx.Client

    return patch(
        "scripts.seed_daily_prices.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler)),
    )


def staged(tmp_path: Path) -> pl.DataFrame:
    return pl.read_parquet(sorted(tmp_path.glob("part-*.parquet")))


def manifest_lines(tmp_path: Path) -> list[dict]:
    text = (tmp_path / "manifest.jsonl").read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_stage_writes_shards_and_manifest(tmp_path: Path) -> None:
    history = {
        "AAPL": eod_rows(["2025-01-02", "2025-01-03"], 100.0),
        "MSFT": eod_rows(["2025-01-02"], 200.0),
        "NVDA": eod_rows(["2025-01-02"], 300.0),
    }

    with patched_client(fmp_handler(history)):
        failed = stage(
            ["AAPL", "MSFT", "NVDA"],
            "test-key",
            tmp_path,
            shard_size=2,
            requests_per_minute=UNTHROTTLED,
        )

    assert failed == []
    assert len(list(tmp_path.glob("part-*.parquet"))) == 2

    entries = manifest_lines(tmp_path)
    assert [entry["symbols"] for entry in entries] == [["AAPL", "MSFT"], ["NVDA"]]
    assert [entry["rows"] for entry in entries] == [3, 1]

    assert staged(tmp_path).height == 4


def test_stage_skips_symbols_already_staged(tmp_path: Path) -> None:
    history = {"AAPL": eod_rows(["2025-01-02"], 100.0)}

    with patched_client(fmp_handler(history)):
        stage(["AAPL"], "test-key", tmp_path, requests_per_minute=UNTHROTTLED)

    second: list[str] = []
    with patched_client(fmp_handler(history, calls=second)):
        failed = stage(["AAPL"], "test-key", tmp_path, requests_per_minute=UNTHROTTLED)

    assert second == []  # no second round of HTTP calls
    assert failed == []
    assert len(manifest_lines(tmp_path)) == 1


def test_ticker_with_no_history_is_not_refetched(tmp_path: Path) -> None:
    """A delisted ticker stages zero rows, so only the manifest records it.

    Without the manifest, resume would key off the staged rows and refetch
    these tickers on every single run.
    """
    with patched_client(fmp_handler({})):
        stage(["LEHMQ"], "test-key", tmp_path, requests_per_minute=UNTHROTTLED)

    assert staged(tmp_path).is_empty()
    assert manifest_lines(tmp_path) == [{"part": 0, "symbols": ["LEHMQ"], "rows": 0}]

    calls: list[str] = []
    with patched_client(fmp_handler({}, calls=calls)):
        stage(["LEHMQ"], "test-key", tmp_path, requests_per_minute=UNTHROTTLED)

    assert calls == []


def test_stage_resumes_the_shard_that_failed(tmp_path: Path) -> None:
    history = {
        "AAPL": eod_rows(["2025-01-02"], 100.0),
        "MSFT": eod_rows(["2025-01-02"], 200.0),
        "NVDA": eod_rows(["2025-01-02"], 300.0),
        "TSLA": eod_rows(["2025-01-02"], 400.0),
    }
    symbols = ["AAPL", "MSFT", "NVDA", "TSLA"]

    # NVDA breaks, taking its whole shard down with it.
    with patched_client(fmp_handler(history, fail={"NVDA"})):
        failed = stage(
            symbols,
            "test-key",
            tmp_path,
            shard_size=2,
            requests_per_minute=UNTHROTTLED,
        )

    assert failed == ["NVDA", "TSLA"]
    assert len(manifest_lines(tmp_path)) == 1
    assert set(staged(tmp_path)["symbol"]) == {"AAPL", "MSFT"}

    retried: list[str] = []
    with patched_client(fmp_handler(history, calls=retried)):
        failed = stage(
            symbols,
            "test-key",
            tmp_path,
            shard_size=2,
            requests_per_minute=UNTHROTTLED,
        )

    assert failed == []
    assert retried == ["NVDA", "TSLA"]  # only the missing shard
    assert set(staged(tmp_path)["symbol"]) == {"AAPL", "MSFT", "NVDA", "TSLA"}


def test_load_upserts_every_year_into_arctic(tmp_path: Path) -> None:
    history = {
        "AAPL": eod_rows(["2024-06-03", "2025-01-02", "2026-01-02"], 100.0),
        "MSFT": eod_rows(["2025-01-02"], 200.0),
    }
    staging = tmp_path / "staging"

    with patched_client(fmp_handler(history)):
        stage(
            ["AAPL", "MSFT"],
            "test-key",
            staging,
            shard_size=1,
            requests_per_minute=UNTHROTTLED,
        )

    lib = library(tmp_path / "arctic")
    rows = load(lib, staging)

    assert rows == 4

    stored = read(lib, DAILY_PRICES)
    assert stored.height == 4
    assert stored["date"].to_list() == [
        date(2024, 6, 3),
        date(2025, 1, 2),
        date(2025, 1, 2),
        date(2026, 1, 2),
    ]
    assert stored.schema == DAILY_PRICES.schema

    apple = stored.filter(pl.col("symbol") == "AAPL")
    assert apple.height == 3
    assert apple["close"].to_list() == [100.0, 100.0, 100.0]


def test_load_is_idempotent(tmp_path: Path) -> None:
    """Rerunning the seed after a partial stage must not duplicate rows."""
    history = {"AAPL": eod_rows(["2025-01-02", "2025-01-03"], 100.0)}
    staging = tmp_path / "staging"

    with patched_client(fmp_handler(history)):
        stage(["AAPL"], "test-key", staging, requests_per_minute=UNTHROTTLED)

    lib = library(tmp_path / "arctic")
    load(lib, staging)
    load(lib, staging)

    assert read(lib, DAILY_PRICES).height == 2


def test_load_without_staged_shards_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="No staged shards"):
        load(library(tmp_path / "arctic"), tmp_path / "empty")
