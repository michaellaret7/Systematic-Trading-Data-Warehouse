from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl
import pytest
from arcticdb import Arctic, OutputFormat
from fastapi.testclient import TestClient

from src.api.dependencies import get_library
from src.api.main import app
from src.storage.arctic import TICKER_UNIVERSE, write


LAST_UPDATED = datetime(2025, 1, 6, 12, 0, tzinfo=timezone.utc)


def library(path: Path):
    arctic = Arctic(f"lmdb://{path}", output_format=OutputFormat.POLARS)
    return arctic.get_library("market_data", create_if_missing=True)


def ticker(
    symbol: str,
    name: str,
    security_type: str,
    *,
    exchange: str = "NASDAQ",
    sector: str = "Technology",
    industry: str = "Consumer Electronics",
    country: str = "US",
    is_adr: bool = False,
) -> dict:
    return {
        "symbol": symbol,
        "company_name": name,
        "security_type": security_type,
        "exchange": exchange,
        "exchange_full_name": "NASDAQ Global Select",
        "sector": sector,
        "industry": industry,
        "country": country,
        "currency": "USD",
        "market_cap": 1_000.0,
        "beta": 1.1,
        "price": 100.0,
        "ipo_date": date(1980, 12, 12),
        "cik": "0000320193",
        "isin": None,
        "cusip": None,
        "is_etf": security_type == "etf",
        "is_fund": security_type == "fund",
        "is_adr": is_adr,
        "last_updated": LAST_UPDATED,
    }


def universe(*rows: dict) -> pl.DataFrame:
    return pl.DataFrame(list(rows), schema=TICKER_UNIVERSE.schema)


@pytest.fixture
def api(tmp_path: Path):
    market_data = library(tmp_path / "arcticdb")
    app.dependency_overrides[get_library] = lambda: market_data

    with TestClient(app) as client:
        yield client, market_data

    app.dependency_overrides.clear()


def seed(market_data) -> None:
    write(
        market_data,
        TICKER_UNIVERSE,
        universe(
            ticker("AAPL", "Apple Inc.", "common"),
            ticker("MSFT", "Microsoft Corporation", "common", industry="Software"),
            ticker(
                "XOM",
                "Exxon Mobil Corporation",
                "common",
                exchange="NYSE",
                sector="Energy",
                industry="Oil & Gas Integrated",
            ),
            ticker(
                "SPY",
                "SPDR S&P 500 ETF Trust",
                "etf",
                exchange="AMEX",
                sector="Financial Services",
                industry="Asset Management",
            ),
            ticker(
                "BABA",
                "Alibaba Group Holding Limited",
                "common",
                exchange="NYSE",
                sector="Consumer Cyclical",
                industry="Internet Retail",
                country="CN",
                is_adr=True,
            ),
        ),
    )


def symbols_of(response) -> list[str]:
    return [row["symbol"] for row in response.json()["data"]]


def test_universe_returns_every_stored_ticker(api) -> None:
    client, market_data = api
    seed(market_data)

    response = client.get("/v1/universe")

    assert response.status_code == 200
    assert response.json()["count"] == 5
    assert symbols_of(response) == ["AAPL", "BABA", "MSFT", "SPY", "XOM"]


def test_universe_filters_symbols(api) -> None:
    client, market_data = api
    seed(market_data)

    response = client.get("/v1/universe", params=[("symbols", "spy")])

    assert response.status_code == 200
    assert response.json() == {
        "count": 1,
        "data": [
            {
                "symbol": "SPY",
                "company_name": "SPDR S&P 500 ETF Trust",
                "security_type": "etf",
                "exchange": "AMEX",
                "exchange_full_name": "NASDAQ Global Select",
                "sector": "Financial Services",
                "industry": "Asset Management",
                "country": "US",
                "currency": "USD",
                "market_cap": 1000.0,
                "beta": 1.1,
                "price": 100.0,
                "ipo_date": "1980-12-12",
                "cik": "0000320193",
                "isin": None,
                "cusip": None,
                "is_etf": True,
                "is_fund": False,
                "is_adr": False,
                "last_updated": "2025-01-06T12:00:00Z",
            }
        ],
    }


def test_universe_filters_flags(api) -> None:
    client, market_data = api
    seed(market_data)

    assert symbols_of(client.get("/v1/universe", params={"is_etf": "true"})) == ["SPY"]
    assert symbols_of(client.get("/v1/universe", params={"is_adr": "true"})) == ["BABA"]
    assert symbols_of(client.get("/v1/universe", params={"is_fund": "true"})) == []
    assert symbols_of(client.get("/v1/universe", params={"is_etf": "false"})) == [
        "AAPL",
        "BABA",
        "MSFT",
        "XOM",
    ]


def test_universe_filters_accept_several_values(api) -> None:
    client, market_data = api
    seed(market_data)

    response = client.get(
        "/v1/universe",
        params=[("sector", "Technology"), ("sector", "Energy")],
    )

    assert response.status_code == 200
    assert symbols_of(response) == ["AAPL", "MSFT", "XOM"]


def test_universe_ands_different_filters_together(api) -> None:
    client, market_data = api
    seed(market_data)

    response = client.get(
        "/v1/universe",
        params={
            "security_type": "common",
            "exchange": "NYSE",
            "country": "US",
            "is_adr": "false",
        },
    )

    assert response.status_code == 200
    assert symbols_of(response) == ["XOM"]


def test_universe_filters_industry(api) -> None:
    client, market_data = api
    seed(market_data)

    response = client.get("/v1/universe", params={"industry": "Software"})

    assert response.status_code == 200
    assert symbols_of(response) == ["MSFT"]


def test_universe_returns_an_empty_result_for_unknown_symbol(api) -> None:
    client, market_data = api
    seed(market_data)

    response = client.get("/v1/universe", params={"symbols": "UNKNOWN"})

    assert response.status_code == 200
    assert response.json() == {"count": 0, "data": []}


def test_universe_returns_an_empty_result_before_the_table_exists(api) -> None:
    client, _ = api

    response = client.get("/v1/universe")

    assert response.status_code == 200
    assert response.json() == {"count": 0, "data": []}
