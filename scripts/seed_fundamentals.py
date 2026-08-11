"""Seed the eight fundamentals tables from FMP's bulk statement endpoints.

Run as ``uv run python -m scripts.seed_fundamentals`` from the repo root.

Reads `ticker_universe` for US common stock (no ETFs, funds, or ADRs), then
pulls income, balance sheet, cash flow, and ratios for every fiscal year in
the window, annually and quarterly. Each table is written whole: this is a
seed, so it *replaces* the eight tables rather than merging into them.

Roughly 300 bulk calls of 13-55 MB each against a feed that throttles on a
rolling window, so expect hours and expect it to be interrupted. **Rerunning
is the recovery path**: every part is cached to `data/fundamentals/` the
moment it arrives, and a rerun re-reads the cache instead of the network.
Delete that directory to force a clean re-fetch.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
from arcticdb import QueryBuilder
from arcticdb.version_store.library import Library

from src.config import require
from src.storage.arctic import (
    BALANCE_SHEET_ANNUAL,
    BALANCE_SHEET_QUARTERLY,
    CASH_FLOW_ANNUAL,
    CASH_FLOW_QUARTERLY,
    INCOME_STATEMENT_ANNUAL,
    INCOME_STATEMENT_QUARTERLY,
    RATIOS_ANNUAL,
    RATIOS_QUARTERLY,
    TICKER_UNIVERSE,
    Dataset,
    connect,
    read,
    write,
)
from src.vendors.fmp import (
    ANNUAL_PERIODS,
    BALANCE_SHEET,
    CASH_FLOW,
    INCOME_STATEMENT,
    QUARTERLY_PERIODS,
    RATIOS,
    fetch_statement,
)
from src.vendors.fmp.fundamentals import (
    BULK_REQUESTS_PER_MINUTE,
    Statement,
)
from src.vendors.fmp.helpers import RateLimiter


#: Matches HISTORY_YEARS in the price vendor, so fundamentals line up with
#: the stored daily history.
HISTORY_YEARS = 15

#: Gitignored. One parquet per (statement, year, period) so an interrupted
#: run resumes instead of re-downloading tens of gigabytes.
CACHE_DIR = Path("data/fundamentals")

#: (statement, FMP period codes, destination table). Eight rows, eight tables.
SEEDS: tuple[tuple[Statement, tuple[str, ...], Dataset], ...] = (
    (INCOME_STATEMENT, ANNUAL_PERIODS, INCOME_STATEMENT_ANNUAL),
    (INCOME_STATEMENT, QUARTERLY_PERIODS, INCOME_STATEMENT_QUARTERLY),
    (BALANCE_SHEET, ANNUAL_PERIODS, BALANCE_SHEET_ANNUAL),
    (BALANCE_SHEET, QUARTERLY_PERIODS, BALANCE_SHEET_QUARTERLY),
    (CASH_FLOW, ANNUAL_PERIODS, CASH_FLOW_ANNUAL),
    (CASH_FLOW, QUARTERLY_PERIODS, CASH_FLOW_QUARTERLY),
    (RATIOS, ANNUAL_PERIODS, RATIOS_ANNUAL),
    (RATIOS, QUARTERLY_PERIODS, RATIOS_QUARTERLY),
)


# ====================================
# --> Helper funcs
# ====================================


def equity_symbols(library: Library) -> list[str]:
    """Every US common-stock ticker in the universe, excluding ADRs.

    ``security_type`` is already 'etf' or 'fund' for those listings, so
    'common' covers both exclusions; ADRs carry their own flag.
    """
    q = QueryBuilder()

    universe = read(
        library,
        TICKER_UNIVERSE,
        columns=["security_type", "is_adr"],
        # `== False` is the QueryBuilder predicate form; `is False` builds nothing.
        where=q[(q["security_type"] == "common") & (q["is_adr"] == False)],
    )

    return universe["symbol"].to_list()


def fiscal_years(years: int, *, as_of: date) -> range:
    """The ``years`` fiscal years ending with the current one."""
    return range(as_of.year - years + 1, as_of.year + 1)


def cached_part(
    statement: Statement,
    api_key: str,
    *,
    year: int,
    period: str,
    symbols: list[str],
    limiter: RateLimiter,
) -> pl.DataFrame:
    """One statement part, from `data/fundamentals/` if it is already there.

    The cache is what makes an interrupted seed cheap to resume: a part costs
    tens of megabytes and a rate-limit window to fetch, and nothing to reread.
    """
    path = CACHE_DIR / f"{statement.name}_{year}_{period}.parquet"

    if path.exists():
        print(f"{statement.name} {year} {period}: cached")

        return pl.read_parquet(path)

    # Only a genuine call is paced; replaying the cache runs at full speed.
    limiter.wait()

    part = fetch_statement(
        statement, api_key, year=year, period=period, symbols=symbols, notify=print
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    part.write_parquet(path)

    print(f"{statement.name} {year} {period}: {part.height:,} rows kept")

    return part


def collect(
    statement: Statement,
    api_key: str,
    *,
    years: range,
    periods: tuple[str, ...],
    symbols: list[str],
    limiter: RateLimiter,
) -> pl.DataFrame:
    """Every part of one statement across ``years`` x ``periods``, concatenated."""
    parts = [
        cached_part(
            statement,
            api_key,
            year=year,
            period=period,
            symbols=symbols,
            limiter=limiter,
        )
        for year in years
        for period in periods
    ]

    return (
        pl.concat(parts)
        # FMP's `year` is a bucket, not the period end: a July-year-end filer
        # asked for under 2011 comes back dated 2010-07-31, so neighbouring
        # years overlap and the storage key would collide without this.
        .unique(subset=["date", "symbol"], keep="last")
        .sort(["date", "symbol"])
    )


# ====================================
# --> Seed
# ====================================


def main() -> None:
    (api_key,) = require("FMP_API_KEY")

    library = connect()
    symbols = equity_symbols(library)
    years = fiscal_years(HISTORY_YEARS, as_of=date.today())

    if not symbols:
        raise SystemExit("ticker_universe is empty — run scripts.seed_universe first")

    limiter = RateLimiter(BULK_REQUESTS_PER_MINUTE)

    print(
        f"Seeding {len(SEEDS)} tables for {len(symbols):,} US equities, "
        f"fiscal years {years.start}-{years.stop - 1}"
    )

    for statement, periods, dataset in SEEDS:
        frame = collect(
            statement,
            api_key,
            years=years,
            periods=periods,
            symbols=symbols,
            limiter=limiter,
        )

        write(library, dataset, frame)

        print(f"Wrote {frame.height:,} rows to '{dataset.symbol}'")


if __name__ == "__main__":
    main()
