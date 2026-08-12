from datetime import date, datetime
from pathlib import Path

import polars as pl
import pytest
from arcticdb import Arctic, OutputFormat
from fastapi.testclient import TestClient

from src.api.dependencies import get_library
from src.api.main import app
from src.storage.arctic import (
    BALANCE_SHEET_ANNUAL,
    CASH_FLOW_ANNUAL,
    INCOME_STATEMENT_ANNUAL,
    INCOME_STATEMENT_QUARTERLY,
    RATIOS_ANNUAL,
    Dataset,
    write,
)


def library(path: Path):
    arctic = Arctic(f"lmdb://{path}", output_format=OutputFormat.POLARS)
    return arctic.get_library("market_data", create_if_missing=True)


def statement(dataset: Dataset, symbol: str, day: str, **values) -> pl.DataFrame:
    filled = {
        "date": date.fromisoformat(day),
        "symbol": symbol,
        "fiscal_year": 2011,
        "period": "FY",
        "reported_currency": "USD",
        "cik": "0000320193",
        "filing_date": date(2011, 10, 26),
        "accepted_date": datetime(2011, 10, 26, 16, 35, 25),
        **values,
    }

    return pl.DataFrame(
        {name: [filled.get(name)] for name in dataset.schema},
        schema=dataset.schema,
    )


@pytest.fixture
def api(tmp_path: Path):
    market_data = library(tmp_path / "arcticdb")
    app.dependency_overrides[get_library] = lambda: market_data

    with TestClient(app) as client:
        yield client, market_data

    app.dependency_overrides.clear()


def test_income_statements_filters_symbols_and_dates(api) -> None:
    client, market_data = api
    write(
        market_data,
        INCOME_STATEMENT_ANNUAL,
        pl.concat(
            [
                statement(INCOME_STATEMENT_ANNUAL, "AAPL", "2010-09-25", revenue=1.0),
                statement(INCOME_STATEMENT_ANNUAL, "MSFT", "2011-06-30", revenue=2.0),
                statement(INCOME_STATEMENT_ANNUAL, "AAPL", "2011-09-24", revenue=3.0),
                statement(INCOME_STATEMENT_ANNUAL, "AAPL", "2012-09-29", revenue=4.0),
            ]
        ),
    )

    response = client.get(
        "/v1/income-statements",
        params={
            "symbols": "AAPL",
            "cadence": "annual",
            "start": "2011-01-01",
            "end": "2011-12-31",
        },
    )

    assert response.status_code == 200
    assert response.json()["count"] == 1

    row = response.json()["data"][0]

    assert row["symbol"] == "AAPL"
    assert row["date"] == "2011-09-24"
    assert row["fiscal_year"] == 2011
    assert row["period"] == "FY"
    assert row["revenue"] == 3.0
    assert row["filing_date"] == "2011-10-26"
    assert row["accepted_date"] == "2011-10-26T16:35:25"
    assert set(row) == set(INCOME_STATEMENT_ANNUAL.schema)


def test_cadence_selects_the_annual_or_quarterly_table(api) -> None:
    client, market_data = api
    write(
        market_data,
        INCOME_STATEMENT_ANNUAL,
        statement(INCOME_STATEMENT_ANNUAL, "AAPL", "2011-09-24", revenue=1.0),
    )
    write(
        market_data,
        INCOME_STATEMENT_QUARTERLY,
        statement(
            INCOME_STATEMENT_QUARTERLY,
            "AAPL",
            "2011-12-31",
            period="Q1",
            revenue=0.3,
        ),
    )

    annual = client.get(
        "/v1/income-statements",
        params={"symbols": "AAPL", "cadence": "annual"},
    )
    quarterly = client.get(
        "/v1/income-statements",
        params={"symbols": "AAPL", "cadence": "quarterly"},
    )

    assert annual.json()["count"] == 1
    assert annual.json()["data"][0]["revenue"] == 1.0
    assert annual.json()["data"][0]["period"] == "FY"

    assert quarterly.json()["count"] == 1
    assert quarterly.json()["data"][0]["revenue"] == 0.3
    assert quarterly.json()["data"][0]["period"] == "Q1"


@pytest.mark.parametrize(
    ("path", "dataset", "column", "value"),
    [
        ("/v1/income-statements", INCOME_STATEMENT_ANNUAL, "revenue", 10.0),
        ("/v1/balance-sheets", BALANCE_SHEET_ANNUAL, "total_assets", 20.0),
        ("/v1/cash-flows", CASH_FLOW_ANNUAL, "free_cash_flow", 30.0),
        ("/v1/ratios", RATIOS_ANNUAL, "net_profit_margin", 0.4),
    ],
)
def test_each_statement_route_reads_its_own_table(
    api, path, dataset, column, value
) -> None:
    client, market_data = api
    write(market_data, dataset, statement(dataset, "AAPL", "2011-09-24", **{column: value}))

    response = client.get(path, params={"symbols": "AAPL", "cadence": "annual"})

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["data"][0][column] == value
    assert set(response.json()["data"][0]) == set(dataset.schema)


def test_income_statements_returns_an_empty_result_for_unknown_symbol(api) -> None:
    client, _ = api

    response = client.get(
        "/v1/income-statements",
        params={"symbols": "UNKNOWN", "cadence": "annual"},
    )

    assert response.status_code == 200
    assert response.json() == {"count": 0, "data": []}


def test_income_statements_requires_a_symbol(api) -> None:
    client, _ = api

    response = client.get("/v1/income-statements", params={"cadence": "annual"})

    assert response.status_code == 422


def test_income_statements_requires_cadence(api) -> None:
    client, _ = api

    response = client.get("/v1/income-statements", params={"symbols": "AAPL"})

    assert response.status_code == 422


def test_income_statements_rejects_an_unknown_cadence(api) -> None:
    client, _ = api

    response = client.get(
        "/v1/income-statements",
        params={"symbols": "AAPL", "cadence": "monthly"},
    )

    assert response.status_code == 422


def test_income_statements_returns_only_the_requested_columns(api) -> None:
    client, market_data = api
    write(
        market_data,
        INCOME_STATEMENT_ANNUAL,
        statement(INCOME_STATEMENT_ANNUAL, "AAPL", "2011-09-24", revenue=3.0, eps=1.5),
    )

    response = client.get(
        "/v1/income-statements",
        params=[
            ("symbols", "AAPL"),
            ("cadence", "annual"),
            ("columns", "revenue"),
            ("columns", "eps"),
        ],
    )

    assert response.status_code == 200
    assert response.json() == {
        "count": 1,
        "data": [
            {
                "date": "2011-09-24",
                "symbol": "AAPL",
                "revenue": 3.0,
                "eps": 1.5,
            }
        ],
    }


def test_income_statements_rejects_an_unknown_column(api) -> None:
    client, _ = api

    response = client.get(
        "/v1/income-statements",
        params=[
            ("symbols", "AAPL"),
            ("cadence", "annual"),
            ("columns", "revnue"),
        ],
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "income_statement_annual has no column(s): ['revnue']",
    }


def test_income_statements_rejects_an_inverted_date_range(api) -> None:
    client, _ = api

    response = client.get(
        "/v1/income-statements",
        params={
            "symbols": "AAPL",
            "cadence": "annual",
            "start": "2012-01-01",
            "end": "2011-01-01",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "start must be on or before end"}
