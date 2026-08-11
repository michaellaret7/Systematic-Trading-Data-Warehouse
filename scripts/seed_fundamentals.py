"""Seed the eight fundamentals tables from FMP's bulk statement endpoints.

Run as ``uv run python -m scripts.seed_fundamentals`` from the repo root.

Reads `ticker_universe` for US common stock (no ETFs, funds, or ADRs), then
pulls income, balance sheet, cash flow, and ratios for every fiscal year in
the window, annually and quarterly. Each table is written whole: this is a
seed, so it *replaces* the eight tables rather than merging into them.

Roughly 300 bulk calls of 13-55 MB each. The bulk endpoints are tightly
rate-limited, so expect this to run for hours.
"""

from __future__ import annotations

from datetime import date

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
    fetch_statements,
)
from src.vendors.fmp.fundamentals import Statement


#: Matches HISTORY_YEARS in the price vendor, so fundamentals line up with
#: the stored daily history.
HISTORY_YEARS = 15

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


# ====================================
# --> Seed
# ====================================


def main() -> None:
    api_key, bucket, region = require("FMP_API_KEY", "S3_BUCKET", "AWS_DEFAULT_REGION")

    library = connect(bucket, region)
    symbols = equity_symbols(library)
    years = fiscal_years(HISTORY_YEARS, as_of=date.today())

    if not symbols:
        raise SystemExit("ticker_universe is empty — run scripts.seed_universe first")

    print(
        f"Seeding {len(SEEDS)} tables for {len(symbols):,} US equities, "
        f"fiscal years {years.start}-{years.stop - 1}"
    )

    for statement, periods, dataset in SEEDS:
        frame: pl.DataFrame = fetch_statements(
            statement,
            api_key,
            years=years,
            periods=periods,
            symbols=symbols,
            notify=print,
        )

        write(library, dataset, frame)

        print(f"Wrote {frame.height:,} rows to '{dataset.symbol}'")


if __name__ == "__main__":
    main()
