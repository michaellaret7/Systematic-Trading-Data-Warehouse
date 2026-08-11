from datetime import date
from pathlib import Path

import polars as pl
import pytest
from arcticdb import Arctic, OutputFormat
from fastapi.testclient import TestClient

from src.api.dependencies import get_library
from src.api.main import app
from src.storage.arctic import DAILY_PRICES, write


def library(path: Path):
    arctic = Arctic(f"lmdb://{path}", output_format=OutputFormat.POLARS)
    return arctic.get_library("market_data", create_if_missing=True)


def prices(*rows: tuple[str, str, float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": [symbol for symbol, _, _ in rows],
            "date": [date.fromisoformat(day) for _, day, _ in rows],
            "open": [close - 1 for _, _, close in rows],
            "high": [close + 1 for _, _, close in rows],
            "low": [close - 2 for _, _, close in rows],
            "close": [close for _, _, close in rows],
            "adj_close": [close - 0.5 for _, _, close in rows],
            "volume": [100] * len(rows),
        },
        schema=DAILY_PRICES.schema,
    )


@pytest.fixture
def api(tmp_path: Path):
    market_data = library(tmp_path / "arcticdb")
    app.dependency_overrides[get_library] = lambda: market_data

    with TestClient(app) as client:
        yield client, market_data

    app.dependency_overrides.clear()


def test_health(api) -> None:
    client, _ = api

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_daily_prices_filters_symbols_and_dates(api) -> None:
    client, market_data = api
    write(
        market_data,
        DAILY_PRICES,
        prices(
            ("AAPL", "2025-01-02", 100),
            ("MSFT", "2025-01-02", 200),
            ("AAPL", "2025-01-03", 101),
            ("AAPL", "2025-01-06", 106),
        ),
    )

    response = client.get(
        "/v1/daily-prices",
        params=[
            ("symbols", "aapl"),
            ("symbols", "msft"),
            ("start", "2025-01-02"),
            ("end", "2025-01-03"),
        ],
    )

    assert response.status_code == 200
    assert response.json() == {
        "count": 3,
        "data": [
            {
                "symbol": "AAPL",
                "date": "2025-01-02",
                "open": 99.0,
                "high": 101.0,
                "low": 98.0,
                "close": 100.0,
                "adj_close": 99.5,
                "volume": 100,
            },
            {
                "symbol": "MSFT",
                "date": "2025-01-02",
                "open": 199.0,
                "high": 201.0,
                "low": 198.0,
                "close": 200.0,
                "adj_close": 199.5,
                "volume": 100,
            },
            {
                "symbol": "AAPL",
                "date": "2025-01-03",
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "adj_close": 100.5,
                "volume": 100,
            },
        ],
    }


def test_daily_prices_returns_an_empty_result_for_unknown_symbol(api) -> None:
    client, _ = api

    response = client.get("/v1/daily-prices", params={"symbols": "UNKNOWN"})

    assert response.status_code == 200
    assert response.json() == {"count": 0, "data": []}


def test_daily_prices_requires_a_symbol(api) -> None:
    client, _ = api

    response = client.get("/v1/daily-prices")

    assert response.status_code == 422


def test_daily_prices_rejects_an_inverted_date_range(api) -> None:
    client, _ = api

    response = client.get(
        "/v1/daily-prices",
        params={
            "symbols": "AAPL",
            "start": "2025-01-03",
            "end": "2025-01-02",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "start must be on or before end"}
