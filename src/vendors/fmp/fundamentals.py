"""Financial statements and ratios from FMP's bulk fundamentals endpoints.

FMP serves one CSV per ``(statement, fiscal year, period)`` covering every
symbol it tracks, so a full history costs a few hundred calls rather than one
per ticker. The feed is global — the caller passes the symbols it wants and
the rest is dropped before anything accumulates.

The four statements differ only in their endpoint and their numeric columns,
so each is declared as a ``Statement`` and served by one fetch pair.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

import httpx
import polars as pl

from .helpers import (
    FMP_BASE_URL,
    Notify,
    RateLimiter,
    get,
    normalize_symbols,
    parse_frame,
)


ANNUAL_PERIODS = ("FY",)
QUARTERLY_PERIODS = ("Q1", "Q2", "Q3", "Q4")

# Bulk fundamentals answer 13-55 MB per call and FMP guards them with a
# separate, much tighter limit than the per-symbol endpoints: a handful of
# back-to-back calls already earns a 429. Pace slowly and let the backoff in
# ``helpers.get`` absorb the rest.
BULK_REQUESTS_PER_MINUTE = 6.0
MAX_ATTEMPTS = 8
TIMEOUT_SECONDS = 300.0


# ====================================
# --> Helper funcs
# ====================================


# Splits camelCase into words, keeping acronyms whole: `netIncomePerEBT`
# becomes `net_income_per_ebt`, not `net_income_per_e_b_t`.
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _snake(name: str) -> str:
    """Convert one of FMP's camelCase field names to snake_case."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def _schema(*, filed: bool, fields: tuple[str, ...]) -> dict[str, Any]:
    """Build a statement schema: identity columns, then every field as a float.

    ``fields`` are FMP's camelCase names, which double as the source of the
    snake_case column names — one list, so the two cannot drift apart.
    """
    schema: dict[str, Any] = {
        "date": pl.Date,
        "symbol": pl.String,
        "fiscal_year": pl.Int32,
        "period": pl.String,
        "reported_currency": pl.String,
    }

    if filed:
        # When the filing reached EDGAR, which is what a point-in-time read
        # has to key off — `date` is the period end, knowable only in hindsight.
        schema |= {
            "cik": pl.String,
            "filing_date": pl.Date,
            "accepted_date": pl.Datetime("us"),
        }

    return schema | {_snake(name): pl.Float64 for name in fields}


def _cast(frame: pl.DataFrame, schema: dict[str, Any]) -> pl.DataFrame:
    """Rename an all-text CSV frame to snake_case and cast it to ``schema``.

    Renaming through ``_snake`` is what keeps the schema and the payload in
    step: both sides derive their names from FMP's field, so neither can
    drift. Columns FMP left out come back as nulls of the declared type.
    """
    frame = frame.rename(_snake)
    columns = []

    for name, dtype in schema.items():
        if name not in frame.columns:
            columns.append(pl.lit(None).cast(dtype).alias(name))
            continue

        text = pl.col(name)

        # Temporal text goes through `str.to_*`: casting String to Date is
        # deprecated, and a plain cast never understood the
        # "YYYY-MM-DD HH:MM:SS" form FMP uses for `acceptedDate` at all.
        if dtype == pl.Date:
            columns.append(text.str.to_date(strict=False).alias(name))
        elif isinstance(dtype, pl.Datetime):
            columns.append(text.str.to_datetime(strict=False).cast(dtype).alias(name))
        else:
            columns.append(text.cast(dtype, strict=False).alias(name))

    return frame.select(columns)


# ====================================
# --> Statement declarations
# ====================================


@dataclass(frozen=True)
class Statement:
    """One bulk fundamentals endpoint: its FMP path and its Polars schema."""

    name: str
    endpoint: str
    schema: dict[str, Any]

    @property
    def url(self) -> str:
        return f"{FMP_BASE_URL}/{self.endpoint}"


INCOME_STATEMENT = Statement(
    name="income_statement",
    endpoint="income-statement-bulk",
    schema=_schema(
        filed=True,
        fields=(
            "revenue",
            "costOfRevenue",
            "grossProfit",
            "researchAndDevelopmentExpenses",
            "generalAndAdministrativeExpenses",
            "sellingAndMarketingExpenses",
            "sellingGeneralAndAdministrativeExpenses",
            "otherExpenses",
            "operatingExpenses",
            "costAndExpenses",
            "netInterestIncome",
            "interestIncome",
            "interestExpense",
            "depreciationAndAmortization",
            "ebitda",
            "ebit",
            "nonOperatingIncomeExcludingInterest",
            "operatingIncome",
            "totalOtherIncomeExpensesNet",
            "incomeBeforeTax",
            "incomeTaxExpense",
            "netIncomeFromContinuingOperations",
            "netIncomeFromDiscontinuedOperations",
            "otherAdjustmentsToNetIncome",
            "netIncome",
            "netIncomeDeductions",
            "bottomLineNetIncome",
            "eps",
            "epsDiluted",
            "weightedAverageShsOut",
            "weightedAverageShsOutDil",
        ),
    ),
)

BALANCE_SHEET = Statement(
    name="balance_sheet",
    endpoint="balance-sheet-statement-bulk",
    schema=_schema(
        filed=True,
        fields=(
            "cashAndCashEquivalents",
            "shortTermInvestments",
            "cashAndShortTermInvestments",
            "netReceivables",
            "accountsReceivables",
            "otherReceivables",
            "inventory",
            "prepaids",
            "otherCurrentAssets",
            "totalCurrentAssets",
            "propertyPlantEquipmentNet",
            "goodwill",
            "intangibleAssets",
            "goodwillAndIntangibleAssets",
            "longTermInvestments",
            "taxAssets",
            "otherNonCurrentAssets",
            "totalNonCurrentAssets",
            "otherAssets",
            "totalAssets",
            "totalPayables",
            "accountPayables",
            "otherPayables",
            "accruedExpenses",
            "shortTermDebt",
            "capitalLeaseObligationsCurrent",
            "taxPayables",
            "deferredRevenue",
            "otherCurrentLiabilities",
            "totalCurrentLiabilities",
            "longTermDebt",
            "capitalLeaseObligationsNonCurrent",
            "deferredRevenueNonCurrent",
            "deferredTaxLiabilitiesNonCurrent",
            "otherNonCurrentLiabilities",
            "totalNonCurrentLiabilities",
            "otherLiabilities",
            "capitalLeaseObligations",
            "totalLiabilities",
            "treasuryStock",
            "preferredStock",
            "commonStock",
            "retainedEarnings",
            "additionalPaidInCapital",
            "accumulatedOtherComprehensiveIncomeLoss",
            "otherTotalStockholdersEquity",
            "totalStockholdersEquity",
            "totalEquity",
            "minorityInterest",
            "totalLiabilitiesAndTotalEquity",
            "totalInvestments",
            "totalDebt",
            "netDebt",
        ),
    ),
)

CASH_FLOW = Statement(
    name="cash_flow",
    endpoint="cash-flow-statement-bulk",
    schema=_schema(
        filed=True,
        fields=(
            "netIncome",
            "depreciationAndAmortization",
            "deferredIncomeTax",
            "stockBasedCompensation",
            "changeInWorkingCapital",
            "accountsReceivables",
            "inventory",
            "accountsPayables",
            "otherWorkingCapital",
            "otherNonCashItems",
            "netCashProvidedByOperatingActivities",
            "investmentsInPropertyPlantAndEquipment",
            "acquisitionsNet",
            "purchasesOfInvestments",
            "salesMaturitiesOfInvestments",
            "otherInvestingActivities",
            "netCashProvidedByInvestingActivities",
            "netDebtIssuance",
            "longTermNetDebtIssuance",
            "shortTermNetDebtIssuance",
            "netStockIssuance",
            "netCommonStockIssuance",
            "commonStockIssuance",
            "commonStockRepurchased",
            "netPreferredStockIssuance",
            "netDividendsPaid",
            "commonDividendsPaid",
            "preferredDividendsPaid",
            "otherFinancingActivities",
            "netCashProvidedByFinancingActivities",
            "effectOfForexChangesOnCash",
            "netChangeInCash",
            "cashAtEndOfPeriod",
            "cashAtBeginningOfPeriod",
            "operatingCashFlow",
            "capitalExpenditure",
            "freeCashFlow",
            "incomeTaxesPaid",
            "interestPaid",
        ),
    ),
)

# Ratios are derived, not filed: FMP sends no CIK or filing dates with them.
RATIOS = Statement(
    name="ratios",
    endpoint="ratios-bulk",
    schema=_schema(
        filed=False,
        fields=(
            "grossProfitMargin",
            "ebitMargin",
            "ebitdaMargin",
            "operatingProfitMargin",
            "pretaxProfitMargin",
            "continuousOperationsProfitMargin",
            "netProfitMargin",
            "bottomLineProfitMargin",
            "receivablesTurnover",
            "payablesTurnover",
            "inventoryTurnover",
            "fixedAssetTurnover",
            "assetTurnover",
            "currentRatio",
            "quickRatio",
            "solvencyRatio",
            "cashRatio",
            "priceToEarningsRatio",
            "priceToEarningsGrowthRatio",
            "forwardPriceToEarningsGrowthRatio",
            "priceToEarningsDilutedRatio",
            "priceToEarningsDilutedGrowthRatio",
            "priceToBookRatio",
            "priceToSalesRatio",
            "priceToFreeCashFlowRatio",
            "priceToOperatingCashFlowRatio",
            "debtToAssetsRatio",
            "debtToEquityRatio",
            "debtToCapitalRatio",
            "longTermDebtToCapitalRatio",
            "financialLeverageRatio",
            "workingCapitalTurnoverRatio",
            "operatingCashFlowRatio",
            "operatingCashFlowSalesRatio",
            "freeCashFlowOperatingCashFlowRatio",
            "debtServiceCoverageRatio",
            "interestCoverageRatio",
            "shortTermOperatingCashFlowCoverageRatio",
            "operatingCashFlowCoverageRatio",
            "capitalExpenditureCoverageRatio",
            "dividendPaidAndCapexCoverageRatio",
            "dividendPayoutRatio",
            "dividendYield",
            "dividendYieldPercentage",
            "revenuePerShare",
            "netIncomePerShare",
            "interestDebtPerShare",
            "cashPerShare",
            "bookValuePerShare",
            "tangibleBookValuePerShare",
            "shareholdersEquityPerShare",
            "operatingCashFlowPerShare",
            "capexPerShare",
            "freeCashFlowPerShare",
            "netIncomePerEBT",
            "ebtPerEbit",
            "priceToFairValue",
            "debtToMarketCap",
            "effectiveTaxRate",
            "enterpriseValueMultiple",
            "dividendPerShare",
        ),
    ),
)

INCOME_STATEMENT_SCHEMA = INCOME_STATEMENT.schema
BALANCE_SHEET_SCHEMA = BALANCE_SHEET.schema
CASH_FLOW_SCHEMA = CASH_FLOW.schema
RATIOS_SCHEMA = RATIOS.schema


# ====================================
# --> Fetch
# ====================================


def fetch_statement(
    statement: Statement,
    api_key: str,
    *,
    year: int,
    period: str,
    symbols: Iterable[str] | None = None,
    client: httpx.Client | None = None,
    notify: Notify | None = None,
) -> pl.DataFrame:
    """Fetch one statement for one fiscal year and period, for every symbol.

    ``symbols`` narrows the global feed before the rows are returned; pass it
    unless you really want every exchange FMP tracks.
    """
    say = notify or (lambda message: None)

    session = nullcontext(client) if client else httpx.Client(timeout=TIMEOUT_SECONDS)

    with session as http:
        response = get(
            statement.url,
            {"year": year, "period": period, "apikey": api_key},
            client=http,
            timeout=TIMEOUT_SECONDS,
            max_attempts=MAX_ATTEMPTS,
            wait=lambda seconds, attempt: say(
                f"{statement.name} {year} {period}: rate limited, "
                f"retry {attempt} in {seconds:.0f}s"
            ),
        )

    raw = parse_frame(response)
    if raw.is_empty():
        return pl.DataFrame(schema=statement.schema)

    frame = _cast(raw, statement.schema).with_columns(
        pl.col("symbol").str.to_uppercase().str.strip_chars()
    )

    if symbols is not None:
        frame = frame.filter(pl.col("symbol").is_in(normalize_symbols(symbols)))

    return (
        frame.drop_nulls(["date", "symbol"])
        # FMP occasionally repeats a period after a restatement; the storage
        # key is (date, symbol), so collapse to the last one it sent.
        .unique(subset=["date", "symbol"], keep="last")
        .sort(["date", "symbol"])
    )


def fetch_statements(
    statement: Statement,
    api_key: str,
    *,
    years: Iterable[int],
    periods: Iterable[str],
    symbols: Iterable[str] | None = None,
    requests_per_minute: float = BULK_REQUESTS_PER_MINUTE,
    client: httpx.Client | None = None,
    notify: Notify | None = None,
) -> pl.DataFrame:
    """Fetch one statement across every ``years`` x ``periods`` pair, rate-limited.

    Each part is narrowed to ``symbols`` before it is kept, so memory tracks
    the requested universe rather than FMP's global feed.
    """
    say = notify or (lambda message: None)
    wanted = None if symbols is None else normalize_symbols(symbols)

    limiter = RateLimiter(requests_per_minute)
    session = nullcontext(client) if client else httpx.Client(timeout=TIMEOUT_SECONDS)
    frames: list[pl.DataFrame] = []

    with session as http:
        for year in years:
            for period in periods:
                limiter.wait()

                part = fetch_statement(
                    statement,
                    api_key,
                    year=year,
                    period=period,
                    symbols=wanted,
                    client=http,
                    notify=notify,
                )

                frames.append(part)

                say(f"{statement.name} {year} {period}: {part.height:,} rows kept")

    if not frames:
        return pl.DataFrame(schema=statement.schema)

    return (
        pl.concat(frames)
        # FMP's `year` is a bucket, not the period end: a July-year-end filer
        # asked for under 2011 comes back dated 2010-07-31, so neighbouring
        # years overlap and the storage key would collide without this.
        .unique(subset=["date", "symbol"], keep="last")
        .sort(["date", "symbol"])
    )
