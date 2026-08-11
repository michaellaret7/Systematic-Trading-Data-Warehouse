from datetime import date
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.vendors.fmp.helpers import RateLimiter
from src.vendors.fmp.prices import (
    HISTORY_YEARS,
    _history_start,
    fetch_daily_prices,
)


def _eod_payload(days: list[tuple[str, float]]) -> list[dict]:
    return [
        {
            "date": day,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1_000,
        }
        for day, close in days
    ]


def _mock_response(payload: list[dict], status_code: int = 200) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = payload
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error",
            request=MagicMock(),
            response=response,
        )
    return response


def test_history_start_is_about_fifteen_years() -> None:
    start = _history_start(HISTORY_YEARS, as_of=date(2026, 8, 10))
    # 15*365 + 15//4 leap-day padding = 5478 days → 2011-08-11
    assert start == date(2011, 8, 11)
    assert (date(2026, 8, 10) - start).days >= 15 * 365


def test_rate_limiter_spaces_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    clock = {"t": 0.0}

    monkeypatch.setattr("src.vendors.fmp.helpers.time.monotonic", lambda: clock["t"])
    monkeypatch.setattr(
        "src.vendors.fmp.helpers.time.sleep",
        lambda s: sleeps.append(s) or clock.update(t=clock["t"] + s),
    )

    limiter = RateLimiter(requests_per_minute=60)  # 1 request / second
    limiter.wait()
    clock["t"] += 0.25
    limiter.wait()

    assert sleeps == [0.75]


def test_single_ticker_sends_from_and_to() -> None:
    response = _mock_response(_eod_payload([("2025-01-02", 100.0)]))
    client = MagicMock(spec=httpx.Client)
    client.get.return_value = response

    frame = fetch_daily_prices(
        ["aapl"],
        "test-key",
        start=date(2011, 1, 1),
        end=date(2026, 1, 1),
        client=client,
    )

    client.get.assert_called_once()
    _, kwargs = client.get.call_args
    assert kwargs["params"] == {
        "symbol": "AAPL",
        "apikey": "test-key",
        "from": "2011-01-01",
        "to": "2026-01-01",
    }
    assert frame.height == 1
    assert frame["symbol"].item() == "AAPL"
    assert frame["close"].item() == 100.0


def test_bare_string_is_treated_as_one_ticker() -> None:
    client = MagicMock(spec=httpx.Client)
    client.get.return_value = _mock_response(_eod_payload([("2025-01-02", 100.0)]))

    frame = fetch_daily_prices("aapl", "test-key", client=client)

    assert client.get.call_count == 1
    assert frame["symbol"].to_list() == ["AAPL"]


def test_rate_limits_each_ticker() -> None:
    payloads = {
        "AAPL": _eod_payload([("2025-01-02", 100.0), ("2025-01-03", 101.0)]),
        "MSFT": _eod_payload([("2025-01-02", 200.0)]),
    }

    def fake_get(url: str, params: dict, timeout: float = 60):
        return _mock_response(payloads[params["symbol"]])

    client = MagicMock(spec=httpx.Client)
    client.get.side_effect = fake_get

    with patch("src.vendors.fmp.prices.RateLimiter") as limiter_cls:
        limiter = MagicMock()
        limiter_cls.return_value = limiter
        frame = fetch_daily_prices(
            ["AAPL", "MSFT", "aapl"],  # dedupes
            "test-key",
            years=15,
            requests_per_minute=100,
            client=client,
        )

    assert limiter.wait.call_count == 2
    assert client.get.call_count == 2
    assert set(frame["symbol"].unique().to_list()) == {"AAPL", "MSFT"}
    assert frame.height == 3

    # Every call asks for a ~15y window via from=
    for call in client.get.call_args_list:
        params = call.kwargs["params"]
        assert "from" in params
        assert params["apikey"] == "test-key"


def test_empty_list() -> None:
    frame = fetch_daily_prices([], "test-key")
    assert frame.is_empty()
    assert frame.columns == ["symbol", "date", "open", "high", "low", "close", "volume"]


def test_retries_transient_errors() -> None:
    """A 429 mid-backfill is retried rather than killing the run."""
    statuses = [429, 503, 200]
    waits: list[tuple[float, int]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        status = statuses.pop(0)
        payload = _eod_payload([("2025-01-02", 100.0)]) if status == 200 else []
        return httpx.Response(status, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        frame = fetch_daily_prices(
            "AAPL",
            "test-key",
            client=client,
            wait=lambda seconds, attempt: waits.append((seconds, attempt)),
        )

    assert statuses == []  # all three responses consumed
    assert waits == [(10.0, 1), (20.0, 2)]  # exponential backoff, no real sleep
    assert frame["close"].to_list() == [100.0]


def test_delisted_ticker_yields_no_rows() -> None:
    """FMP answers `200 []` for unknown/delisted symbols instead of erroring."""
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    ) as client:
        frame = fetch_daily_prices("LEHMQ", "test-key", client=client)

    assert frame.is_empty()
    assert frame.columns == ["symbol", "date", "open", "high", "low", "close", "volume"]
