"""Read-only HTTP endpoints for stored financial statements and ratios."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any

import polars as pl
from arcticdb.version_store.library import Library
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, create_model

from src.api.dependencies import get_library
from src.storage.arctic import (
    BALANCE_SHEET_ANNUAL,
    BALANCE_SHEET_QUARTERLY,
    CASH_FLOW_ANNUAL,
    CASH_FLOW_QUARTERLY,
    INCOME_STATEMENT_ANNUAL,
    INCOME_STATEMENT_QUARTERLY,
    RATIOS_ANNUAL,
    RATIOS_QUARTERLY,
    Dataset,
    read,
)


router = APIRouter(prefix="/v1", tags=["fundamentals"])


class Cadence(StrEnum):
    ANNUAL = "annual"
    QUARTERLY = "quarterly"


# ====================================
# --> Helper funcs
# ====================================


def _annotation(dtype: Any) -> type:
    """Python type for one Polars column on the wire."""
    if dtype == pl.Date:
        return date | None
    if dtype == pl.String:
        return str | None
    if dtype == pl.Int32:
        return int | None
    if dtype == pl.Float64:
        return float | None
    if isinstance(dtype, pl.Datetime):
        return datetime | None

    raise TypeError(f"no HTTP type for {dtype}")


def _row_model(name: str, schema: dict[str, Any]) -> type[BaseModel]:
    """A response row whose fields track the stored statement schema."""
    return create_model(
        name,
        **{column: (_annotation(dtype), None) for column, dtype in schema.items()},
    )


def _table(annual: Dataset, quarterly: Dataset, cadence: Cadence) -> Dataset:
    return quarterly if cadence is Cadence.QUARTERLY else annual


def _respond(
    library: Library,
    dataset: Dataset,
    row: type[BaseModel],
    response: type[BaseModel],
    symbols: list[str],
    start: date | None,
    end: date | None,
    columns: list[str] | None,
) -> BaseModel:
    """Read one statement table and wrap it in ``{count, data}``."""
    if start is not None and end is not None and start > end:
        raise HTTPException(
            status_code=422,
            detail="start must be on or before end",
        )

    try:
        frame = read(
            library,
            dataset,
            symbols=symbols,
            start=start,
            end=end,
            columns=columns,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return response(
        count=frame.height,
        data=[row(**record) for record in frame.to_dicts()],
    )


# ====================================
# --> Models
# ====================================


IncomeStatement = _row_model("IncomeStatement", INCOME_STATEMENT_ANNUAL.schema)
BalanceSheet = _row_model("BalanceSheet", BALANCE_SHEET_ANNUAL.schema)
CashFlow = _row_model("CashFlow", CASH_FLOW_ANNUAL.schema)
Ratios = _row_model("Ratios", RATIOS_ANNUAL.schema)


class IncomeStatementsResponse(BaseModel):
    """Income-statement rows and their count."""

    count: int
    data: list[IncomeStatement]


class BalanceSheetsResponse(BaseModel):
    """Balance-sheet rows and their count."""

    count: int
    data: list[BalanceSheet]


class CashFlowsResponse(BaseModel):
    """Cash-flow rows and their count."""

    count: int
    data: list[CashFlow]


class RatiosResponse(BaseModel):
    """Ratio rows and their count."""

    count: int
    data: list[Ratios]


# ====================================
# --> Endpoints
# ====================================


@router.get(
    "/income-statements",
    response_model=IncomeStatementsResponse,
    response_model_exclude_unset=True,
)
def get_income_statements(
    symbols: Annotated[list[str], Query(min_length=1)],
    cadence: Cadence,
    start: date | None = None,
    end: date | None = None,
    columns: Annotated[list[str] | None, Query()] = None,
    library: Library = Depends(get_library),
) -> IncomeStatementsResponse:
    """Return stored income statements for one or more symbols.

    ``cadence`` selects the annual or quarterly table. ``start`` and ``end``
    are inclusive period-end dates when present. Repeat ``columns`` to return
    only those fields; key columns are always included.
    """
    return _respond(
        library,
        _table(INCOME_STATEMENT_ANNUAL, INCOME_STATEMENT_QUARTERLY, cadence),
        IncomeStatement,
        IncomeStatementsResponse,
        symbols,
        start,
        end,
        columns,
    )


@router.get(
    "/balance-sheets",
    response_model=BalanceSheetsResponse,
    response_model_exclude_unset=True,
)
def get_balance_sheets(
    symbols: Annotated[list[str], Query(min_length=1)],
    cadence: Cadence,
    start: date | None = None,
    end: date | None = None,
    columns: Annotated[list[str] | None, Query()] = None,
    library: Library = Depends(get_library),
) -> BalanceSheetsResponse:
    """Return stored balance sheets for one or more symbols.

    ``cadence`` selects the annual or quarterly table. ``start`` and ``end``
    are inclusive period-end dates when present. Repeat ``columns`` to return
    only those fields; key columns are always included.
    """
    return _respond(
        library,
        _table(BALANCE_SHEET_ANNUAL, BALANCE_SHEET_QUARTERLY, cadence),
        BalanceSheet,
        BalanceSheetsResponse,
        symbols,
        start,
        end,
        columns,
    )


@router.get(
    "/cash-flows",
    response_model=CashFlowsResponse,
    response_model_exclude_unset=True,
)
def get_cash_flows(
    symbols: Annotated[list[str], Query(min_length=1)],
    cadence: Cadence,
    start: date | None = None,
    end: date | None = None,
    columns: Annotated[list[str] | None, Query()] = None,
    library: Library = Depends(get_library),
) -> CashFlowsResponse:
    """Return stored cash-flow statements for one or more symbols.

    ``cadence`` selects the annual or quarterly table. ``start`` and ``end``
    are inclusive period-end dates when present. Repeat ``columns`` to return
    only those fields; key columns are always included.
    """
    return _respond(
        library,
        _table(CASH_FLOW_ANNUAL, CASH_FLOW_QUARTERLY, cadence),
        CashFlow,
        CashFlowsResponse,
        symbols,
        start,
        end,
        columns,
    )


@router.get(
    "/ratios",
    response_model=RatiosResponse,
    response_model_exclude_unset=True,
)
def get_ratios(
    symbols: Annotated[list[str], Query(min_length=1)],
    cadence: Cadence,
    start: date | None = None,
    end: date | None = None,
    columns: Annotated[list[str] | None, Query()] = None,
    library: Library = Depends(get_library),
) -> RatiosResponse:
    """Return stored financial ratios for one or more symbols.

    ``cadence`` selects the annual or quarterly table. ``start`` and ``end``
    are inclusive period-end dates when present. Repeat ``columns`` to return
    only those fields; key columns are always included.
    """
    return _respond(
        library,
        _table(RATIOS_ANNUAL, RATIOS_QUARTERLY, cadence),
        Ratios,
        RatiosResponse,
        symbols,
        start,
        end,
        columns,
    )
