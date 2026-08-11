"""Shared plumbing for the FMP vendor modules.

Everything here is dataset-agnostic: HTTP access, throttling, and the
coercion helpers used to normalize FMP's loosely typed JSON/CSV payloads.
Dataset-specific endpoints, schemas, and parsing live in sibling modules
(``prices``, ``profiles``, ...).
"""

from __future__ import annotations

import io
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any

import httpx
import polars as pl


FMP_BASE_URL = "https://financialmodelingprep.com/stable"

# Conservative default under Starter (300/min) and Premium (750/min) plans.
DEFAULT_REQUESTS_PER_MINUTE = 250.0

DEFAULT_TIMEOUT_SECONDS = 60.0

# FMP answers with 429 when a bulk endpoint is hit too often, and its own docs
# note bulk endpoints can throw 502 under load. Both are worth retrying.
RETRY_STATUS_CODES = frozenset({429, 502, 503, 504})

DEFAULT_BACKOFF_SECONDS = 10.0
MAX_BACKOFF_SECONDS = 65.0

# ``(seconds, attempt)`` — lets callers render the wait instead of blocking mutely.
WaitFn = Callable[[float, int], None]


class RateLimiter:
    """Enforce a maximum number of acquisitions per rolling minute."""

    def __init__(self, requests_per_minute: float) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        self._min_interval = 60.0 / requests_per_minute
        self._next_allowed = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delay = self._next_allowed - now
        if delay > 0:
            time.sleep(delay)
            now = time.monotonic()
        self._next_allowed = now + self._min_interval


@contextmanager
def http_client(
    client: httpx.Client | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Iterator[httpx.Client]:
    """Yield ``client`` if given, else an owned client closed on exit."""
    if client is not None:
        yield client
        return
    owned = httpx.Client(timeout=timeout)
    try:
        yield owned
    finally:
        owned.close()


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Seconds from a ``Retry-After`` header, if the server sent a usable one."""
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        # The date form of Retry-After is legal but FMP does not use it.
        return None
    return seconds if seconds >= 0 else None


def _default_wait(seconds: float, attempt: int) -> None:  # noqa: ARG001
    time.sleep(seconds)


def get(
    url: str,
    params: dict[str, Any],
    *,
    client: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_attempts: int = 1,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    max_backoff_seconds: float = MAX_BACKOFF_SECONDS,
    wait: WaitFn | None = None,
) -> httpx.Response:
    """GET ``url`` (optionally on a shared client) and raise on HTTP errors.

    With ``max_attempts`` above 1, responses in ``RETRY_STATUS_CODES`` are
    retried with exponential backoff (honouring ``Retry-After`` when present)
    instead of raising. ``wait`` receives ``(seconds, attempt)`` and defaults
    to a plain sleep; pass one to render the delay or to skip it in tests.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    sleeper = wait or _default_wait
    delay = backoff_seconds

    for attempt in range(1, max_attempts + 1):
        if client is None:
            response = httpx.get(url, params=params, timeout=timeout)
        else:
            response = client.get(url, params=params, timeout=timeout)

        retryable = response.status_code in RETRY_STATUS_CODES
        if not retryable or attempt == max_attempts:
            response.raise_for_status()
            return response

        sleeper(_retry_after_seconds(response) or delay, attempt)
        delay = min(delay * 2, max_backoff_seconds)

    raise AssertionError("unreachable")  # pragma: no cover


def parse_rows(response: httpx.Response, *, context: str) -> list[dict[str, Any]]:
    """Parse an FMP response that may be JSON or CSV into a list of rows.

    Bulk endpoints return CSV; most others return JSON. ``context`` only
    labels the error message when the payload is neither.
    """
    text = response.text.strip()
    if not text:
        return []

    content_type = response.headers.get("content-type", "").lower()
    if "json" in content_type or text[:1] in {"[", "{"}:
        payload = response.json()
        if isinstance(payload, list):
            return payload
        # Error payloads come back as JSON objects.
        raise RuntimeError(f"Unexpected FMP {context} payload: {payload}")

    # Read every column as text and let the ``as_*`` coercers below decide the
    # types. Inferring from a sample is fragile on these feeds: FMP reports
    # `fullTimeEmployees` as a decimal FTE count ("165.8") for some issuers,
    # which blows up an int column inferred from the first N rows.
    frame = pl.read_csv(io.StringIO(text), infer_schema_length=0)
    if frame.is_empty():
        return []
    return frame.to_dicts()


def normalize_symbols(tickers: str | Iterable[str]) -> list[str]:
    """Upper-case, strip, and de-duplicate tickers, preserving order.

    A bare string is treated as a single ticker rather than an iterable of
    characters, so ``"AAPL"`` and ``["AAPL"]`` behave the same.
    """
    if isinstance(tickers, str):
        tickers = [tickers]

    seen: set[str] = set()
    out: list[str] = []
    for raw in tickers:
        symbol = str(raw).upper().strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def field(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """First non-empty value among ``keys`` (FMP mixes camelCase/snake_case)."""
    for key in keys:
        if key not in row:
            continue
        value = row[key]
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return default


def as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
