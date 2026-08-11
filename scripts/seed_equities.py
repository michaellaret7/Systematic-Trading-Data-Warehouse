"""Seed the equity universe from FMP's company screener."""

from __future__ import annotations

import os
import re

import httpx
from dotenv import load_dotenv

load_dotenv()

FMP_SCREENER_URL = "https://financialmodelingprep.com/stable/company-screener"

# Major US listings covered by FMP's company-screener exchange filter.
US_EXCHANGES = ("NASDAQ", "NYSE", "AMEX")

# Minimum market capitalization in USD (exclusive of threshold).
MIN_MARKET_CAP = 2_000_000_000

# Share-class / structured suffixes: preferreds, warrants, rights, units.
# Hyphen classes (BAC-B) are nearly always preferreds on US listings.
# Dot classes keep multi-class common equity (BRK.B / BF.B) but drop .PR/.WS/etc.
_CLASS_NON_EQUITY = re.compile(
    r"""
    (?:
        -(?:[A-Z]|PR[A-Z]?|W|WS|WT|WTS|R|RT|U|UN|V)$
        |
        \.(?:P|PR[A-Z]?|W|WS|WT|WTS|R|RT|U|UN|V)$
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# NASDAQ 5th-letter codes on 5-char tickers: W warrant, R rights, U unit,
# V when-issued, P preferred, Q bankruptcy residual.
_NASDAQ_FIFTH = re.compile(r"^[A-Z]{4}[PRQUVW]$")

# Multi-letter non-equity suffixes stuck on a short root (e.g. XXXWS, XXXWTS).
_STUCK_SUFFIX = re.compile(r"^[A-Z]{1,4}(WS|WW|WTS|WT|RT|UN|PR)$")

# Name tokens for preferreds, bonds, notes, warrants, rights, structured products.
_NON_EQUITY_NAME = re.compile(
    r"""
    \b(
        bond|bonds|note|notes|debenture|debentures|
        warrant|warrants|
        subscription\s+right|rights\s+offering|
        preferred|preference|
        depositary\s+(?:share|shares|preferred)|
        trust\s+certificate|preferred\s+plus|
        senior\s+note|subordinated\s+note|
        structured\s+product|exchangeable\s+note|
        income\s+trust|unit\s+trust
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# American Depositary Receipts / Shares (common name variants in FMP data).
_ADR_NAME = re.compile(
    r"""
    \b(
        adr|ads|
        american\s+deposit(?:a|o)ry(?:\s+receipts?|\s+shares?)?|
        deposit(?:a|o)ry\s+(?:receipts?|shares?)
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _is_non_equity_symbol(symbol: str) -> bool:
    """Return True for warrant/right/unit/preferred/bond-style tickers."""
    if _CLASS_NON_EQUITY.search(symbol):
        return True
    if _NASDAQ_FIFTH.fullmatch(symbol):
        return True
    if _STUCK_SUFFIX.fullmatch(symbol):
        return True
    return False


def _is_common_equity(
    row: dict,
    *,
    min_market_cap: float = MIN_MARKET_CAP,
) -> bool:
    """True when the screener row looks like common stock (not bond/pref/warrant/ADR/etc.)."""
    if row.get("isEtf") or row.get("isFund"):
        return False
    if row.get("isAdr") is True:
        return False

    symbol = str(row.get("symbol") or "").upper().strip()
    if not symbol:
        return False
    if _is_non_equity_symbol(symbol):
        return False

    name = str(row.get("companyName") or "")
    if _NON_EQUITY_NAME.search(name) or _ADR_NAME.search(name):
        return False

    # Bonds and structured products often lack a real sector / market cap.
    sector = row.get("sector")
    if not sector or not str(sector).strip():
        return False

    market_cap = row.get("marketCap")
    if market_cap is None:
        return False
    try:
        if float(market_cap) <= min_market_cap:
            return False
    except (TypeError, ValueError):
        return False

    return True


def fetch_active_us_companies(
    api_key: str,
    *,
    exchanges: tuple[str, ...] = US_EXCHANGES,
    limit: int = 1000,
    min_market_cap: int = MIN_MARKET_CAP,
    exclude_etfs: bool = True,
    exclude_funds: bool = True,
) -> list[str]:
    """Return symbols of actively trading common equities on US exchanges.

    Uses FMP's company screener (`/stable/company-screener`) with
    ``isActivelyTrading=true``, market cap above ``min_market_cap`` (default
    $2B), and the given US exchange list. Pages until the API returns fewer
    rows than ``limit``. Drops ETFs, funds, ADRs, warrants, rights, units,
    preferreds, bonds, and other non-common equities.
    """
    symbols: list[str] = []
    page = 0

    while True:
        params: dict[str, str | int] = {
            "apikey": api_key,
            "exchange": ",".join(exchanges),
            "isActivelyTrading": "true",
            "marketCapMoreThan": min_market_cap,
            "limit": limit,
            "page": page,
        }
        if exclude_etfs:
            params["isEtf"] = "false"
        if exclude_funds:
            params["isFund"] = "false"

        response = httpx.get(FMP_SCREENER_URL, params=params, timeout=60)
        response.raise_for_status()

        rows = response.json()
        if not isinstance(rows, list):
            raise RuntimeError(f"Unexpected FMP screener response: {rows}")
        if not rows:
            break

        for row in rows:
            if not _is_common_equity(row, min_market_cap=min_market_cap):
                continue
            symbols.append(str(row["symbol"]).upper())

        if len(rows) < limit:
            break
        page += 1

    seen: set[str] = set()
    unique: list[str] = []
    for symbol in symbols:
        if symbol not in seen:
            seen.add(symbol)
            unique.append(symbol)
    return unique


def main() -> None:
    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        raise RuntimeError("Set FMP_API_KEY before running the seed")

    symbols = fetch_active_us_companies(api_key)
    print(f"Found {len(symbols)} active US-listed common equities (>$2B, non-ADR)")
    for symbol in symbols:
        print(symbol)


if __name__ == "__main__":
    main()
