"""Company profiles / ticker universe from FMP's bulk profile endpoint."""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import nullcontext
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
    parse_rows,
)


FMP_PROFILE_BULK_URL = f"{FMP_BASE_URL}/profile-bulk"

# The feed's shard count is unknown up front: pagination ends when a part comes
# back empty, or when FMP rejects the part number with a 400 carrying this text.
MAX_PARTS = 20
PART_OUT_OF_RANGE_MARKER = "invalid or missing query parameter - part"

# FMP's FAQ suggests one profile-bulk call per 60s, but that is etiquette
# guidance rather than a published quota: the server's own limiter is looser
# and answers 429 when it does object. So pace optimistically and let the 429
# backoff in ``helpers.get`` do the throttling.
MAX_ATTEMPTS = 5
TIMEOUT_SECONDS = 120.0

# profile-bulk is FMP's *global* feed — the bulk of it is OTC, BSE, JPX,
# HKSE, LSE and friends. The warehouse only trades US-listed names.
US_LISTED_EXCHANGES = frozenset({"AMEX", "NASDAQ", "NYSE"})

#: What the warehouse trades: ordinary shares and exchange-traded funds.
TRADED_SECURITY_TYPES = frozenset({"common", "etf"})

#: Blank-check/SPAC vehicles. Their Class A shares are technically common
#: stock, but they are trust accounts with no operating business.
EXCLUDED_INDUSTRIES = frozenset({"Shell Companies"})

# NYSE/AMEX hang a dashed suffix off the root symbol. A bare single letter
# (BF-A, AKO-B, AGM-A) is an ordinary share class and stays.
_DASH_SUFFIX_TYPES: dict[str, str] = {
    "UN": "unit",
    "U": "unit",
    "WT": "warrant",
    "WS": "warrant",
    "RT": "right",
    "R": "right",
}

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

# Progress callback: receives one ready-to-print line per part or retry.
Notify = Callable[[str], None]

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


# ====================================
# --> Helper funcs
# ====================================


def _profile_row_to_universe(
    row: dict[str, Any],
    *,
    last_updated: datetime,
) -> dict[str, Any] | None:
    """Map one profile-bulk row to the universe schema, or None if filtered out."""
    if as_bool(field(row, "isActivelyTrading", "is_actively_trading")) is not True:
        return None

    symbol = as_str(field(row, "symbol"))
    if not symbol:
        return None

    exchange = as_str(
        field(row, "exchangeShortName", "exchange_short_name", "exchange")
    )
    if exchange is None or exchange.upper() not in US_LISTED_EXCHANGES:
        return None

    industry = as_str(field(row, "industry"))
    if industry in EXCLUDED_INDUSTRIES:
        return None

    company_name = as_str(field(row, "companyName", "company_name"))
    is_etf = as_bool(field(row, "isEtf", "is_etf")) is True
    is_fund = as_bool(field(row, "isFund", "is_fund")) is True

    security_type = classify_security(
        symbol, company_name=company_name, is_etf=is_etf, is_fund=is_fund
    )
    if security_type not in TRADED_SECURITY_TYPES:
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


def _is_last_part(error: httpx.HTTPStatusError) -> bool:
    """True when FMP rejected ``part`` because the feed has no such shard."""
    return (
        error.response.status_code == 400
        and PART_OUT_OF_RANGE_MARKER in error.response.text.lower()
    )


# ====================================
# --> Classification
# ====================================


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
    if is_etf:
        return "etf"
    if is_fund:
        return "fund"

    root, _, suffix = symbol.upper().strip().partition("-")

    if suffix:
        if suffix.startswith("P"):
            return "preferred"
        # A bare class letter (BF-A, AKO-B) is ordinary stock.
        return _DASH_SUFFIX_TYPES.get(suffix, "common")

    if len(root) == 5:
        last = root[-1]
        if last == "Z":
            name = company_name or ""
            return "preferred" if _PREFERRED_NAME_PATTERN.search(name) else "warrant"
        if last in _FIFTH_LETTER_TYPES:
            return _FIFTH_LETTER_TYPES[last]

    return "common"


# ====================================
# --> Fetch
# ====================================


def fetch_ticker_universe(
    api_key: str,
    *,
    client: httpx.Client | None = None,
    max_parts: int = MAX_PARTS,
    notify: Notify | None = None,
) -> pl.DataFrame:
    """Build the tradable ticker universe from FMP profile-bulk.

    Pulls every shard until the feed runs out and keeps actively trading
    US-listed common stock and ETFs (see the filter constants above).
    ``notify`` receives one progress line per part and per rate-limit retry.
    """
    say = notify or (lambda message: None)
    last_updated = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []

    session = nullcontext(client) if client else httpx.Client(timeout=TIMEOUT_SECONDS)

    with session as http:
        for part in range(max_parts):
            try:
                response = get(
                    FMP_PROFILE_BULK_URL,
                    {"part": part, "apikey": api_key},
                    client=http,
                    timeout=TIMEOUT_SECONDS,
                    max_attempts=MAX_ATTEMPTS,
                    wait=lambda seconds, attempt: say(
                        f"rate limited, retry {attempt} in {seconds:.0f}s"
                    ),
                )
            except httpx.HTTPStatusError as error:
                # Past the last shard FMP answers 400, not an empty page.
                if _is_last_part(error):
                    break
                raise

            part_rows = parse_rows(response)
            if not part_rows:
                break

            for raw in part_rows:
                mapped = _profile_row_to_universe(raw, last_updated=last_updated)
                if mapped is not None:
                    rows.append(mapped)

            say(f"part {part + 1}: {len(part_rows):,} rows → {len(rows):,} kept")

    if not rows:
        return pl.DataFrame(schema=TICKER_UNIVERSE_SCHEMA)

    return (
        pl.DataFrame(rows, schema=TICKER_UNIVERSE_SCHEMA, strict=False)
        .unique(subset=["symbol"], keep="last")
        .sort("symbol")
    )
