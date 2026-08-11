"""Company profiles / ticker universe from FMP's bulk profile endpoint."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Collection
from datetime import datetime, timezone
from typing import Any

import httpx
import polars as pl

from .helpers import (
    FMP_BASE_URL,
    as_bool,
    as_date,
    as_float,
    as_str,
    field,
    get,
    http_client,
    parse_rows,
)
from .helpers import WaitFn


FMP_PROFILE_BULK_URL = f"{FMP_BASE_URL}/profile-bulk"

# FMP's FAQ suggests one profile-bulk call per 60s, but that is etiquette
# guidance rather than a published quota: the server's own limiter is looser
# and answers 429 when it does object. So pace optimistically by default and
# let the 429 backoff in ``helpers.get`` do the throttling.
PROFILE_BULK_SUGGESTED_INTERVAL_SECONDS = 60.0
PROFILE_BULK_MIN_INTERVAL_SECONDS = 0.0
PROFILE_BULK_MAX_PARTS = 20
PROFILE_BULK_MAX_ATTEMPTS = 5

PROFILE_BULK_TIMEOUT_SECONDS = 120.0

# Asking for a part past the last one is how the feed says "no more data".
PART_OUT_OF_RANGE_MARKER = "invalid or missing query parameter - part"

# profile-bulk is FMP's *global* feed — the bulk of it is OTC, BSE, JPX,
# HKSE, LSE and friends. The warehouse only trades US-listed names.
US_LISTED_EXCHANGES = frozenset({"AMEX", "NASDAQ", "NYSE"})

# Instrument classes, derived from the listing conventions below.
SECURITY_TYPES = ("common", "etf", "fund", "warrant", "unit", "right", "preferred")

#: What the warehouse trades: ordinary shares and exchange-traded funds.
DEFAULT_SECURITY_TYPES = frozenset({"common", "etf"})

#: Blank-check/SPAC vehicles. Their Class A shares are technically common
#: stock, but they are trust accounts with no operating business.
EXCLUDED_INDUSTRIES = frozenset({"Shell Companies"})

# NYSE/AMEX hang a dashed suffix off the root symbol. A bare single letter
# (BF-A, AKO-B, AGM-A) is an ordinary share class and stays.
_DASH_SUFFIX_TYPES: tuple[tuple[str, str], ...] = (
    ("UN", "unit"),
    ("U", "unit"),
    ("WT", "warrant"),
    ("WS", "warrant"),
    ("RT", "right"),
    ("R", "right"),
)

# NASDAQ reserves the 5th letter of a 5-character symbol for the instrument
# class. FMP labels these lines with the *operating company's* name and
# industry (ARQQW reads "Arqit Quantum Inc.", industry "Software"), so the
# symbol is the only reliable signal — never the name.
_FIFTH_LETTER_TYPES: dict[str, str] = {
    "W": "warrant",
    "R": "right",
    "U": "unit",
}

# Trailing Z covers both second-series warrants and preferred lines; the
# name disambiguates only in this one case (e.g. "8.75% Series H Fixed-Rate").
_PREFERRED_NAME_PATTERN = re.compile(
    r"%|\bseries\b|\bcumulative\b|\bpreferred\b|\bdepositary\b", re.IGNORECASE
)

# Progress callback: ``(event, payload)``. Events are "fetching", "part_done",
# "waiting", and "finished"; see ``fetch_ticker_universe``.
ProgressFn = Callable[[str, dict[str, Any]], None]

# How often ``waiting`` is re-emitted while a countdown runs.
_WAIT_TICK_SECONDS = 0.5

TICKER_UNIVERSE_SCHEMA: dict[str, Any] = {
    "symbol": pl.String,
    "company_name": pl.String,
    "security_type": pl.String,
    "exchange": pl.String,
    "exchange_full_name": pl.String,
    "sector": pl.String,
    "industry": pl.String,
    "country": pl.String,
    "currency": pl.String,
    "market_cap": pl.Float64,
    "beta": pl.Float64,
    "price": pl.Float64,
    "ipo_date": pl.Date,
    "cik": pl.String,
    "isin": pl.String,
    "cusip": pl.String,
    "is_etf": pl.Boolean,
    "is_fund": pl.Boolean,
    "is_adr": pl.Boolean,
    "last_updated": pl.Datetime(time_zone="UTC"),
}


def _empty_ticker_universe() -> pl.DataFrame:
    return pl.DataFrame(schema=TICKER_UNIVERSE_SCHEMA)


def _is_actively_trading(row: dict[str, Any]) -> bool:
    return as_bool(field(row, "isActivelyTrading", "is_actively_trading")) is True


def classify_security(
    symbol: str,
    *,
    company_name: str | None = None,
    is_etf: bool = False,
    is_fund: bool = False,
) -> str:
    """Classify a US listing from its ticker convention.

    Fund flags win first, so an ETF with an unusual symbol is never mistaken
    for a derivative. Otherwise the suffix decides: FMP copies the operating
    company's name and industry onto warrant/right/unit lines, so those
    fields cannot be used to tell instruments apart.
    """
    ticker = symbol.upper().strip()
    if is_etf:
        return "etf"
    if is_fund:
        return "fund"

    root, _, suffix = ticker.partition("-")
    if suffix:
        if suffix.startswith("P"):
            return "preferred"
        for marker, security_type in _DASH_SUFFIX_TYPES:
            if suffix == marker:
                return security_type
        # A bare class letter (BF-A, AKO-B) is ordinary stock.
        return "common"

    if len(root) == 5:
        last = root[-1]
        if last == "Z":
            name = company_name or ""
            return "preferred" if _PREFERRED_NAME_PATTERN.search(name) else "warrant"
        if last in _FIFTH_LETTER_TYPES:
            return _FIFTH_LETTER_TYPES[last]

    return "common"


def _profile_row_to_universe(
    row: dict[str, Any],
    *,
    last_updated: datetime,
    exchanges: Collection[str] | None = None,
    security_types: Collection[str] | None = None,
    exclude_industries: Collection[str] | None = None,
) -> dict[str, Any] | None:
    if not _is_actively_trading(row):
        return None

    symbol = as_str(field(row, "symbol"))
    if not symbol:
        return None

    exchange = as_str(
        field(row, "exchangeShortName", "exchange_short_name", "exchange")
    )
    if exchanges is not None:
        if exchange is None or exchange.upper() not in exchanges:
            return None

    industry = as_str(field(row, "industry"))
    if exclude_industries and industry in exclude_industries:
        return None

    company_name = as_str(field(row, "companyName", "company_name"))
    is_etf = as_bool(field(row, "isEtf", "is_etf")) is True
    is_fund = as_bool(field(row, "isFund", "is_fund")) is True
    security_type = classify_security(
        symbol, company_name=company_name, is_etf=is_etf, is_fund=is_fund
    )
    if security_types is not None and security_type not in security_types:
        return None

    return {
        "symbol": symbol.upper(),
        "company_name": company_name,
        "security_type": security_type,
        "exchange": exchange,
        "exchange_full_name": as_str(
            field(row, "exchangeFullName", "exchange_full_name")
        ),
        "sector": as_str(field(row, "sector")),
        "industry": industry,
        "country": as_str(field(row, "country")),
        "currency": as_str(field(row, "currency")),
        "market_cap": as_float(field(row, "marketCap", "market_cap", "mktCap")),
        "beta": as_float(field(row, "beta")),
        "price": as_float(field(row, "price")),
        "ipo_date": as_date(field(row, "ipoDate", "ipo_date")),
        "cik": as_str(field(row, "cik")),
        "isin": as_str(field(row, "isin")),
        "cusip": as_str(field(row, "cusip")),
        "is_etf": is_etf,
        "is_fund": is_fund,
        "is_adr": as_bool(field(row, "isAdr", "is_adr")) is True,
        "last_updated": last_updated,
    }


def _countdown(
    seconds: float,
    on_progress: ProgressFn | None,
    **payload: Any,
) -> None:
    """Sleep ``seconds``, emitting a ``waiting`` countdown if asked to."""
    if seconds <= 0:
        return
    if on_progress is None:
        time.sleep(seconds)
        return

    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        on_progress(
            "waiting",
            {"seconds_left": remaining, "seconds_total": seconds, **payload},
        )
        time.sleep(min(_WAIT_TICK_SECONDS, remaining))


def _backoff_reporter(part: int, on_progress: ProgressFn | None) -> WaitFn:
    """A :data:`WaitFn` that renders a 429 backoff as a countdown."""

    def report(seconds: float, attempt: int) -> None:
        _countdown(
            seconds,
            on_progress,
            part=part,
            attempt=attempt,
            reason="rate_limit",
        )

    return report


def _is_part_out_of_range(error: httpx.HTTPStatusError) -> bool:
    """True when FMP rejected ``part`` because the feed has no such shard."""
    response = error.response
    if response.status_code != 400:
        return False
    return PART_OUT_OF_RANGE_MARKER in response.text.strip().lower()


def fetch_profile_bulk_part(
    api_key: str,
    part: int,
    *,
    client: httpx.Client | None = None,
    max_attempts: int = PROFILE_BULK_MAX_ATTEMPTS,
    wait: WaitFn | None = None,
) -> list[dict[str, Any]]:
    """Fetch one shard of FMP ``/stable/profile-bulk``.

    Retries rate-limit and gateway responses up to ``max_attempts`` times;
    ``wait`` is forwarded to :func:`helpers.get` to render the backoff.
    """
    response = get(
        FMP_PROFILE_BULK_URL,
        {"part": part, "apikey": api_key},
        client=client,
        timeout=PROFILE_BULK_TIMEOUT_SECONDS,
        max_attempts=max_attempts,
        wait=wait,
    )
    return parse_rows(response, context="profile-bulk")


def fetch_ticker_universe(
    api_key: str,
    *,
    max_parts: int = PROFILE_BULK_MAX_PARTS,
    part_interval_seconds: float = PROFILE_BULK_MIN_INTERVAL_SECONDS,
    max_attempts: int = PROFILE_BULK_MAX_ATTEMPTS,
    exchanges: Collection[str] | None = US_LISTED_EXCHANGES,
    security_types: Collection[str] | None = DEFAULT_SECURITY_TYPES,
    exclude_industries: Collection[str] | None = EXCLUDED_INDUSTRIES,
    client: httpx.Client | None = None,
    on_progress: ProgressFn | None = None,
) -> pl.DataFrame:
    """Build the tradable ticker universe from FMP profile-bulk.

    Pulls every ``part`` until the feed runs out (or ``max_parts``) and keeps
    the rows that survive four filters, mapped to ``TICKER_UNIVERSE_SCHEMA``:

    ``isActivelyTrading``
        Always applied; delisted and inactive tickers never appear.
    ``exchanges``
        The three US venues by default (``US_LISTED_EXCHANGES``). ``None``
        keeps FMP's full global feed — roughly seven times larger and
        dominated by OTC and non-US listings.
    ``security_types``
        Ordinary shares and ETFs by default (``DEFAULT_SECURITY_TYPES``),
        classified by :func:`classify_security`. ``None`` keeps warrants,
        units, rights, preferred lines, and closed-end funds as well.
    ``exclude_industries``
        Blank-check shells by default (``EXCLUDED_INDUSTRIES``).

    Parts are requested back to back by default. When FMP pushes back with a
    429 the request is retried with exponential backoff (``max_attempts``),
    which is both faster and more correct than sleeping a fixed interval that
    the server may not require.

    ``on_progress`` is called with ``(event, payload)`` as the pull advances:

    - ``"fetching"``: ``part``, ``max_parts``, ``kept``
    - ``"part_done"``: ``part``, ``max_parts``, ``part_rows``, ``kept``
    - ``"waiting"``: ``seconds_left``, ``seconds_total``, ``part``, ``reason``
      (``"rate_limit"`` for a 429 backoff, ``"interval"`` for the optional
      fixed spacing), and ``attempt`` for rate-limit waits
    - ``"finished"``: ``parts``, ``kept``
    """
    if max_parts < 1:
        raise ValueError("max_parts must be >= 1")

    last_updated = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    parts_fetched = 0

    with http_client(client, timeout=PROFILE_BULK_TIMEOUT_SECONDS) as http:
        for part in range(max_parts):
            if part > 0 and part_interval_seconds > 0:
                _countdown(
                    part_interval_seconds,
                    on_progress,
                    part=part,
                    reason="interval",
                )

            if on_progress is not None:
                on_progress(
                    "fetching",
                    {"part": part, "max_parts": max_parts, "kept": len(rows)},
                )

            try:
                bulk_rows = fetch_profile_bulk_part(
                    api_key,
                    part,
                    client=http,
                    max_attempts=max_attempts,
                    wait=_backoff_reporter(part, on_progress),
                )
            except httpx.HTTPStatusError as error:
                # Past the last shard FMP answers 400, not an empty page.
                if _is_part_out_of_range(error):
                    break
                raise

            if not bulk_rows:
                break

            parts_fetched += 1
            for raw in bulk_rows:
                mapped = _profile_row_to_universe(
                    raw,
                    last_updated=last_updated,
                    exchanges=exchanges,
                    security_types=security_types,
                    exclude_industries=exclude_industries,
                )
                if mapped is not None:
                    rows.append(mapped)

            if on_progress is not None:
                on_progress(
                    "part_done",
                    {
                        "part": part,
                        "max_parts": max_parts,
                        "part_rows": len(bulk_rows),
                        "kept": len(rows),
                    },
                )

    if on_progress is not None:
        on_progress("finished", {"parts": parts_fetched, "kept": len(rows)})

    if not rows:
        return _empty_ticker_universe()

    frame = pl.DataFrame(rows, schema=TICKER_UNIVERSE_SCHEMA, strict=False)
    return (
        frame.unique(subset=["symbol"], keep="last")
        .sort("symbol")
        .select(list(TICKER_UNIVERSE_SCHEMA))
    )
