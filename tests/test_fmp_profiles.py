from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import polars as pl
import pytest

from src.vendors.fmp.profiles import (
    TICKER_UNIVERSE_SCHEMA,
    _profile_row_to_universe,
    classify_security,
    fetch_ticker_universe,
)


def test_profile_row_skips_inactive() -> None:
    last_updated = datetime(2026, 3, 22, tzinfo=timezone.utc)
    row = {
        "symbol": "DEAD",
        "companyName": "Dead Co",
        "isActivelyTrading": False,
        "isEtf": False,
        "isFund": False,
        "isAdr": False,
        "marketCap": 1e9,
    }
    assert _profile_row_to_universe(row, last_updated=last_updated) is None


def test_profile_row_maps_active_equity() -> None:
    last_updated = datetime(2026, 3, 22, tzinfo=timezone.utc)
    row = {
        "symbol": "aapl",
        "companyName": "Apple Inc.",
        "exchange": "NASDAQ",
        "exchangeFullName": "NASDAQ Global Select",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "country": "US",
        "currency": "USD",
        "marketCap": 3e12,
        "beta": 1.1,
        "price": 200.0,
        "ipoDate": "1980-12-12",
        "cik": "0000320193",
        "isin": "US0378331005",
        "cusip": "037833100",
        "isEtf": False,
        "isFund": False,
        "isAdr": False,
        "isActivelyTrading": True,
    }
    mapped = _profile_row_to_universe(row, last_updated=last_updated)
    assert mapped is not None
    assert mapped["symbol"] == "AAPL"
    assert mapped["company_name"] == "Apple Inc."
    assert mapped["is_etf"] is False
    assert mapped["is_adr"] is False
    assert mapped["ipo_date"] == date(1980, 12, 12)
    assert mapped["last_updated"] == last_updated


def test_fetch_ticker_universe_filters_and_dedupes() -> None:
    part0 = [
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "exchange": "NASDAQ",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "country": "US",
            "currency": "USD",
            "marketCap": 3e12,
            "isEtf": False,
            "isFund": False,
            "isAdr": False,
            "isActivelyTrading": True,
        },
        {
            "symbol": "ZZZ",
            "companyName": "Inactive Inc.",
            "isActivelyTrading": False,
        },
    ]
    transport = _bulk_transport(
        {
            0: httpx.Response(200, json=part0),
            1: httpx.Response(200, json=[_active("AAPL")]),  # repeat of part 0
            2: httpx.Response(200, json=[]),  # an empty page ends the pull
        }
    )

    with httpx.Client(transport=transport) as client:
        frame = fetch_ticker_universe("test-key", client=client)

    assert frame.height == 1
    assert frame["symbol"].to_list() == ["AAPL"]
    assert set(frame.columns) == set(TICKER_UNIVERSE_SCHEMA)


def _active(symbol: str, exchange: str = "NASDAQ") -> dict:
    return {
        "symbol": symbol,
        "companyName": f"{symbol} Inc.",
        "exchange": exchange,
        "isEtf": "false",
        "isFund": "false",
        "isAdr": "false",
        "isActivelyTrading": "true",
    }


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        # Ordinary shares, including dashed class lines.
        ("AAPL", "common"),
        ("BRK-B", "common"),
        ("BF-A", "common"),
        ("AKO-B", "common"),
        ("AGM-A", "common"),
        # SPAC complex — the cases that started this.
        ("AACB", "common"),
        ("AACBR", "right"),
        ("AACBU", "unit"),
        ("AAC-UN", "unit"),
        # Warrants: NASDAQ 5th letter and NYSE dashed form.
        ("ARQQW", "warrant"),
        ("ALVOW", "warrant"),
        ("ACHR-WT", "warrant"),
        # Preferred / depositary lines.
        ("ABR-PD", "preferred"),
        ("ACP-PA", "preferred"),
        # Four-character tickers are never suffixed.
        ("SNOW", "common"),
        ("HOUR", "common"),
        ("ACIU", "common"),
    ],
)
def test_classify_security_by_ticker_convention(symbol: str, expected: str) -> None:
    assert classify_security(symbol) == expected


def test_classify_security_disambiguates_trailing_z_by_name() -> None:
    """Trailing Z is a second-series warrant unless the name says preferred."""
    assert (
        classify_security("AGNCZ", company_name="AGNC Investment Corp. 8.75% Series H")
        == "preferred"
    )
    assert classify_security("CORZZ", company_name="Core Scientific, Inc.") == "warrant"


def test_classify_security_fund_flags_win_over_ticker_shape() -> None:
    """An ETF whose symbol ends in a reserved letter is still an ETF."""
    assert classify_security("FOOW", is_etf=True) == "etf"
    assert classify_security("BARU", is_fund=True) == "fund"
    assert classify_security("SPY", is_etf=True) == "etf"


def test_classify_security_ignores_misleading_company_name() -> None:
    """FMP copies the operating company's name onto derivative lines."""
    assert classify_security("ARQQW", company_name="Arqit Quantum Inc.") == "warrant"
    assert classify_security("ABLVW", company_name="Able View Inc.") == "warrant"


def test_profile_row_drops_non_us_exchange() -> None:
    last_updated = datetime(2026, 3, 22, tzinfo=timezone.utc)
    row = _active("0700.HK", exchange="HKSE")
    assert _profile_row_to_universe(row, last_updated=last_updated) is None


def test_profile_row_exchange_match_is_case_insensitive() -> None:
    last_updated = datetime(2026, 3, 22, tzinfo=timezone.utc)
    row = _active("AAPL", exchange="nasdaq")
    mapped = _profile_row_to_universe(row, last_updated=last_updated)
    assert mapped is not None
    assert mapped["symbol"] == "AAPL"


def test_fetch_ticker_universe_keeps_only_us_exchanges() -> None:
    rows = [
        _active("AAPL", "NASDAQ"),
        _active("BRK-B", "NYSE"),
        _active("SPY", "AMEX"),
        _active("0700.HK", "HKSE"),
        _active("SHEL.L", "LSE"),
        _active("PINK", "OTC"),
        _active("000001.SZ", "SHZ"),
    ]
    transport = _bulk_transport({0: httpx.Response(200, json=rows)})

    with httpx.Client(transport=transport) as client:
        frame = fetch_ticker_universe("test-key", client=client)

    assert frame["symbol"].to_list() == ["AAPL", "BRK-B", "SPY"]


def test_fetch_ticker_universe_keeps_only_equities_and_etfs() -> None:
    etf = _active("SPY", "AMEX") | {"isEtf": "true"}
    cef = _active("ACP", "NYSE") | {"isFund": "true"}
    rows = [
        _active("AAPL"),
        etf,
        cef,
        _active("AACBR"),  # rights
        _active("AACBU"),  # units
        _active("ARQQW"),  # warrant
        _active("ABR-PD", "NYSE"),  # preferred
        _active("AAC-UN", "NYSE"),  # unit
    ]
    transport = _bulk_transport({0: httpx.Response(200, json=rows)})

    with httpx.Client(transport=transport) as client:
        frame = fetch_ticker_universe("test-key", client=client)

    assert frame["symbol"].to_list() == ["AAPL", "SPY"]
    assert frame["security_type"].to_list() == ["common", "etf"]


def test_fetch_ticker_universe_drops_shell_companies() -> None:
    rows = [
        _active("AAPL"),
        _active("AACB") | {"industry": "Shell Companies"},
    ]
    transport = _bulk_transport({0: httpx.Response(200, json=rows)})

    with httpx.Client(transport=transport) as client:
        frame = fetch_ticker_universe("test-key", client=client)

    assert frame["symbol"].to_list() == ["AAPL"]


def _bulk_transport(parts: dict[int, httpx.Response]) -> httpx.MockTransport:
    """Serve ``parts`` by index; anything else 400s the way FMP does."""

    def handler(request: httpx.Request) -> httpx.Response:
        part = int(request.url.params["part"])
        if part in parts:
            return parts[part]
        return httpx.Response(
            400, text="Query Error: Invalid or missing query parameter - part"
        )

    return httpx.MockTransport(handler)


def test_fetch_ticker_universe_stops_on_part_out_of_range() -> None:
    """Past the last shard FMP answers 400, not an empty page."""
    transport = _bulk_transport(
        {
            0: httpx.Response(200, json=[_active("AAPL")]),
            1: httpx.Response(200, json=[_active("MSFT")]),
        }
    )

    with httpx.Client(transport=transport) as client:
        frame = fetch_ticker_universe("test-key", client=client)

    assert frame["symbol"].to_list() == ["AAPL", "MSFT"]


def test_fetch_ticker_universe_retries_rate_limited_part() -> None:
    responses = [
        httpx.Response(429, json={"Error Message": "Limit Reach."}),
        httpx.Response(200, json=[_active("AAPL")]),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if int(request.url.params["part"]) != 0:
            return httpx.Response(
                400, text="Query Error: Invalid or missing query parameter - part"
            )
        return responses.pop(0) if responses else httpx.Response(200, json=[])

    lines: list[str] = []
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with patch("src.vendors.fmp.helpers.time.sleep"):
            frame = fetch_ticker_universe(
                "test-key", client=client, notify=lines.append
            )

    assert frame["symbol"].to_list() == ["AAPL"]
    assert any("rate limited" in line for line in lines)


def test_fetch_ticker_universe_reraises_other_http_errors() -> None:
    transport = _bulk_transport({0: httpx.Response(401, text="Invalid API key")})

    with httpx.Client(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            fetch_ticker_universe("bad-key", client=client)

    assert excinfo.value.response.status_code == 401


def test_fetch_ticker_universe_reports_progress_per_part() -> None:
    transport = _bulk_transport({0: httpx.Response(200, json=[_active("AAPL")])})
    lines: list[str] = []

    with httpx.Client(transport=transport) as client:
        fetch_ticker_universe("test-key", client=client, notify=lines.append)

    assert lines == ["part 1: 1 rows → 1 kept"]


def test_write_ticker_universe_keeps_symbol_as_a_column() -> None:
    from src.storage.arctic import TICKER_UNIVERSE, write

    library = MagicMock()
    universe = pl.DataFrame(
        {
            "symbol": ["AAPL"],
            "company_name": ["Apple Inc."],
            "security_type": ["common"],
            "exchange": ["NASDAQ"],
            "exchange_full_name": [None],
            "sector": ["Technology"],
            "industry": ["Consumer Electronics"],
            "country": ["US"],
            "currency": ["USD"],
            "market_cap": [3e12],
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
        schema=TICKER_UNIVERSE_SCHEMA,
    )

    write(library, TICKER_UNIVERSE, universe)

    library.write.assert_called_once()
    symbol_name, pdf = library.write.call_args[0]
    assert symbol_name == "ticker_universe"
    # Only a timestamp index earns ArcticDB anything, so the universe goes to
    # storage on a plain RangeIndex with `symbol` left as an ordinary column.
    assert list(pdf.index.names) == [None]
    assert pdf["symbol"].tolist() == ["AAPL"]
