"""Shared plumbing for the FMP vendor modules.

Everything here is dataset-agnostic: HTTP access, throttling, and the
coercion helpers used to normalize FMP's loosely typed JSON/CSV payloads.
Dataset-specific endpoints, schemas, and parsing live in sibling modules
(``prices``, ``profiles``, ...).
"""

from __future__ import annotations

import io
import time
from collections.abc import Callable, Iterable
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

BACKOFF_SECONDS = 10.0
MAX_BACKOFF_SECONDS = 65.0

# ``(seconds, attempt)`` — lets callers render the wait instead of blocking mutely.
WaitFn = Callable[[float, int], None]

# Progress callback: receives one ready-to-print line per unit of work.
Notify = Callable[[str], None]


# ====================================
# --> Helper funcs
# ====================================


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Seconds from a ``Retry-After`` header, if the server sent a usable one."""
    try:
        # The date form of Retry-After is legal but FMP does not use it.
        seconds = float(str(response.headers.get("retry-after", "")).strip())
    except (TypeError, ValueError):
        return None

    return seconds if seconds >= 0 else None


# ====================================
# --> HTTP
# ====================================


class RateLimiter:
    """Enforce a maximum number of acquisitions per rolling minute."""

    def __init__(self, requests_per_minute: float) -> None:
        self._min_interval = 60.0 / requests_per_minute
        self._next_allowed = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delay = self._next_allowed - now

        if delay > 0:
            time.sleep(delay)
            now = time.monotonic()

        self._next_allowed = now + self._min_interval


def get(
    url: str,
    params: dict[str, Any],
    *,
    client: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_attempts: int = 1,
    wait: WaitFn | None = None,
) -> httpx.Response:
    """GET ``url`` (optionally on a shared client) and raise on HTTP errors.

    With ``max_attempts`` above 1, responses in ``RETRY_STATUS_CODES`` are
    retried with exponential backoff, honouring ``Retry-After`` when present.
    ``wait`` receives ``(seconds, attempt)``; pass one to render the delay or
    to skip it in tests.
    """
    sleeper = wait or (lambda seconds, attempt: time.sleep(seconds))
    fetch = httpx.get if client is None else client.get
    delay = BACKOFF_SECONDS

    for attempt in range(1, max_attempts + 1):
        response = fetch(url, params=params, timeout=timeout)

        if response.status_code not in RETRY_STATUS_CODES or attempt == max_attempts:
            break

        sleeper(_retry_after_seconds(response) or delay, attempt)
        delay = min(delay * 2, MAX_BACKOFF_SECONDS)

    response.raise_for_status()

    return response


def parse_rows(response: httpx.Response) -> list[dict[str, Any]]:
    """Parse an FMP response into rows. Bulk endpoints return CSV, others JSON."""
    text = response.text.strip()
    if not text:
        return []

    content_type = response.headers.get("content-type", "").lower()
    if "json" in content_type or text[:1] in {"[", "{"}:
        payload = response.json()
        if isinstance(payload, list):
            return payload
        # Error payloads come back as JSON objects.
        raise RuntimeError(f"Unexpected FMP payload: {payload}")

    # Read every column as text and let the ``as_*`` coercers below decide the
    # types. Inferring from a sample is fragile on these feeds: FMP reports
    # `fullTimeEmployees` as a decimal FTE count ("165.8") for some issuers,
    # which blows up an int column inferred from the first N rows.
    return pl.read_csv(io.StringIO(text), infer_schema_length=0).to_dicts()


def parse_frame(response: httpx.Response) -> pl.DataFrame:
    """Parse a bulk CSV response into an all-text frame, empty when there is no data.

    The frame form of ``parse_rows``, for payloads big enough that a list of
    dicts is the wrong shape. Columns stay text for the same reason: the
    caller casts them against a declared schema.
    """
    text = response.text.strip()
    if not text:
        return pl.DataFrame()

    if text[:1] in {"[", "{"}:
        # A bulk endpoint answers CSV; JSON here means an error payload.
        raise RuntimeError(f"Unexpected FMP payload: {text[:200]}")

    return pl.read_csv(io.StringIO(text), infer_schema_length=0)


# ====================================
# --> Coercion
# ====================================


def normalize_symbols(tickers: str | Iterable[str]) -> list[str]:
    """Upper-case, strip, and de-duplicate tickers, preserving order.

    A bare string is one ticker rather than an iterable of characters.
    """
    if isinstance(tickers, str):
        tickers = [tickers]

    cleaned = (str(raw).upper().strip() for raw in tickers)

    return list(dict.fromkeys(symbol for symbol in cleaned if symbol))


def field(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """First non-empty value among ``keys`` (FMP mixes camelCase/snake_case)."""
    for key in keys:
        value = row.get(key)

        if value is None or (isinstance(value, str) and not value.strip()):
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
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_str(value: Any) -> str | None:
    if value is None:
        return None

    return str(value).strip() or None


def as_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError):
        return None
