from datetime import date, datetime

import httpx
import polars as pl
import pytest

from src.vendors.fmp.fundamentals import (
    ANNUAL_PERIODS,
    BALANCE_SHEET,
    CASH_FLOW,
    INCOME_STATEMENT,
    MAX_ATTEMPTS,
    MAX_BACKOFF_SECONDS,
    QUARTERLY_PERIODS,
    RATIOS,
    _snake,
    fetch_statement,
)


# Real rows lifted from FMP's income-statement-bulk feed for fiscal 2011,
# including a Shenzhen listing to prove the global feed gets narrowed.
INCOME_HEADER = (
    '"date","symbol","reportedCurrency","cik","filingDate","acceptedDate",'
    '"fiscalYear","period","revenue","costOfRevenue","grossProfit",'
    '"researchAndDevelopmentExpenses","netIncome","eps","epsDiluted",'
    '"weightedAverageShsOut"'
)
AAPL_ROW = (
    '"2011-09-24","AAPL","USD","0000320193","2011-10-26","2011-10-26 16:35:25",'
    '"2011","FY",108249000000,64431000000,43818000000,2429000000,25922000000,'
    "1,0.99,25879249879"
)
MSFT_ROW = (
    '"2011-06-30","MSFT","USD","0000789019","2011-07-28","2011-07-28 14:59:09",'
    '"2011","FY",69943000000,15577000000,54366000000,9043000000,23150000000,'
    "2.73,2.69,8490000000"
)
SHENZHEN_ROW = (
    '"2011-12-31","000001.SZ","CNY","0000000000","2011-12-31",'
    '"2011-12-30 19:00:00","2011","FY",56577779000,26979718000,29598061000,0,'
    "10278631000,0.89,0.89,11505408497"
)

INCOME_CSV = "\n".join([INCOME_HEADER, AAPL_ROW, MSFT_ROW, SHENZHEN_ROW])


def csv_client(body: str, *, seen: list[dict] | None = None) -> httpx.Client:
    """An httpx client answering every bulk call with ``body``."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(dict(request.url.params))

        return httpx.Response(200, text=body, headers={"content-type": "text/csv"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_snake_keeps_acronyms_whole() -> None:
    assert _snake("netIncomePerEBT") == "net_income_per_ebt"
    assert _snake("ebitdaMargin") == "ebitda_margin"
    assert _snake("weightedAverageShsOutDil") == "weighted_average_shs_out_dil"
    assert _snake("cik") == "cik"


def test_filed_statements_carry_acceptance_timestamps() -> None:
    for statement in (INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW):
        assert statement.schema["accepted_date"] == pl.Datetime("us")
        assert statement.schema["filing_date"] == pl.Date
        assert statement.schema["cik"] == pl.String

    # Ratios are derived by FMP, not filed, so none of those columns exist.
    assert "accepted_date" not in RATIOS.schema
    assert "cik" not in RATIOS.schema


def test_every_statement_is_keyed_on_date_and_symbol() -> None:
    for statement in (INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW, RATIOS):
        assert list(statement.schema)[:2] == ["date", "symbol"]
        assert statement.schema["date"] == pl.Date
        assert statement.schema["symbol"] == pl.String


def test_fetch_statement_casts_real_payload() -> None:
    with csv_client(INCOME_CSV) as client:
        frame = fetch_statement(
            INCOME_STATEMENT, "key", year=2011, period="FY", client=client
        )

    assert frame.schema == pl.Schema(INCOME_STATEMENT.schema)

    apple = frame.filter(pl.col("symbol") == "AAPL").row(0, named=True)
    assert apple["date"] == date(2011, 9, 24)
    assert apple["fiscal_year"] == 2011
    assert apple["period"] == "FY"
    assert apple["revenue"] == 108_249_000_000.0
    assert apple["eps_diluted"] == 0.99
    # CIK is an identifier, not a number: the leading zeros have to survive.
    assert apple["cik"] == "0000320193"
    assert apple["accepted_date"] == datetime(2011, 10, 26, 16, 35, 25)
    assert apple["filing_date"] == date(2011, 10, 26)


def test_fetch_statement_fills_columns_fmp_omitted() -> None:
    with csv_client(INCOME_CSV) as client:
        frame = fetch_statement(
            INCOME_STATEMENT, "key", year=2011, period="FY", client=client
        )

    # `ebitda` is in the declared schema but not in this payload.
    assert frame["ebitda"].dtype == pl.Float64
    assert frame["ebitda"].null_count() == frame.height


def test_fetch_statement_narrows_the_global_feed() -> None:
    with csv_client(INCOME_CSV) as client:
        everything = fetch_statement(
            INCOME_STATEMENT, "key", year=2011, period="FY", client=client
        )
        narrowed = fetch_statement(
            INCOME_STATEMENT,
            "key",
            year=2011,
            period="FY",
            symbols=["aapl", " msft "],
            client=client,
        )

    assert set(everything["symbol"]) == {"AAPL", "MSFT", "000001.SZ"}
    assert narrowed["symbol"].to_list() == ["MSFT", "AAPL"]  # sorted by date


def test_fetch_statement_collapses_a_repeated_period() -> None:
    restated = AAPL_ROW.replace("25922000000", "25000000000")
    body = "\n".join([INCOME_HEADER, AAPL_ROW, restated])

    with csv_client(body) as client:
        frame = fetch_statement(
            INCOME_STATEMENT, "key", year=2011, period="FY", client=client
        )

    assert frame.height == 1
    assert frame["net_income"][0] == 25_000_000_000.0


def test_fetch_statement_returns_typed_frame_when_feed_is_empty() -> None:
    with csv_client("") as client:
        frame = fetch_statement(RATIOS, "key", year=1995, period="FY", client=client)

    assert frame.is_empty()
    assert frame.schema == pl.Schema(RATIOS.schema)


def test_fetch_statement_raises_on_an_error_payload() -> None:
    with csv_client('{"Error Message": "Limit Reach."}') as client:
        with pytest.raises(RuntimeError, match="Unexpected FMP payload"):
            fetch_statement(
                INCOME_STATEMENT, "key", year=2011, period="FY", client=client
            )


def test_fetch_statement_asks_for_the_year_and_period_given() -> None:
    seen: list[dict] = []

    with csv_client(INCOME_CSV, seen=seen) as client:
        fetch_statement(INCOME_STATEMENT, "key", year=2011, period="Q3", client=client)

    assert seen == [{"year": "2011", "period": "Q3", "apikey": "key"}]


def test_bulk_backoff_ladder_outlasts_the_throttle_window() -> None:
    # The throttle clears after a few idle minutes, so the ladder has to be
    # able to wait that long: 10s doubling to a 600s ceiling over 12 attempts.
    assert MAX_BACKOFF_SECONDS >= 600.0
    assert MAX_ATTEMPTS >= 12


def test_annual_and_quarterly_periods_cover_the_fiscal_calendar() -> None:
    assert ANNUAL_PERIODS == ("FY",)
    assert QUARTERLY_PERIODS == ("Q1", "Q2", "Q3", "Q4")
