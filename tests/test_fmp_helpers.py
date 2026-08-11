import httpx
import pytest

from src.vendors.fmp.helpers import get, parse_rows


def _csv_response(body: str) -> httpx.Response:
    return httpx.Response(
        200, text=body, headers={"content-type": "text/csv; charset=utf-8"}
    )


def test_parse_rows_keeps_mixed_numeric_columns_as_text() -> None:
    """FMP reports fractional FTE counts, which break an inferred int column."""
    body = "\n".join(
        ["symbol,fullTimeEmployees"]
        + [f"S{i},{i}" for i in range(50)]
        + ["FRAC,165.8"]
    )

    rows = parse_rows(_csv_response(body))

    assert len(rows) == 51
    assert rows[-1] == {"symbol": "FRAC", "fullTimeEmployees": "165.8"}
    assert rows[0]["fullTimeEmployees"] == "0"


def test_parse_rows_handles_empty_body() -> None:
    assert parse_rows(_csv_response("")) == []


def test_get_retries_rate_limit_then_succeeds() -> None:
    codes = [429, 429, 200]
    waits: list[tuple[float, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(codes.pop(0), json=[{"ok": True}])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = get(
            "https://example.test/bulk",
            {},
            client=client,
            max_attempts=5,
            wait=lambda seconds, attempt: waits.append((seconds, attempt)),
        )

    assert response.status_code == 200
    assert waits == [(10.0, 1), (20.0, 2)]  # doubling backoff


def test_get_honours_retry_after_header() -> None:
    codes = [429, 200]
    waits: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        code = codes.pop(0)
        headers = {"retry-after": "3"} if code == 429 else {}
        return httpx.Response(code, json=[], headers=headers)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        get(
            "https://example.test/bulk",
            {},
            client=client,
            max_attempts=3,
            wait=lambda seconds, attempt: waits.append(seconds),
        )

    assert waits == [3.0]


def test_get_raises_after_exhausting_attempts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"Error Message": "Limit Reach."})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            get(
                "https://example.test/bulk",
                {},
                client=client,
                max_attempts=2,
                wait=lambda seconds, attempt: None,
            )

    assert excinfo.value.response.status_code == 429


def test_get_does_not_retry_by_default() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, json={})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            get("https://example.test/bulk", {}, client=client)

    assert calls == 1


def test_get_does_not_retry_client_errors() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, text="Query Error")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            get(
                "https://example.test/bulk",
                {},
                client=client,
                max_attempts=5,
                wait=lambda seconds, attempt: None,
            )

    assert calls == 1
