"""Read-only HTTP endpoint for the stored ticker universe."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated

from arcticdb import QueryBuilder
from arcticdb.version_store.library import Library
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.dependencies import get_library
from src.storage.arctic import TICKER_UNIVERSE, read


router = APIRouter(prefix="/v1/universe", tags=["universe"])


# ====================================
# --> Helper funcs
# ====================================


def _where(
    categories: dict[str, list[str] | None],
    flags: dict[str, bool | None],
    ipo_start: date | None = None,
    ipo_end: date | None = None,
) -> QueryBuilder | None:
    """Combine the supplied filters into one pushed-down predicate, or None.

    Chained ``QueryBuilder`` predicates AND together; unset filters are skipped
    so an unfiltered request still reads the table without a query at all.
    """
    query: QueryBuilder | None = None

    for column, values in categories.items():
        if not values:
            continue

        query = QueryBuilder() if query is None else query
        query = query[query[column].isin(values)]

    for column, flag in flags.items():
        if flag is None:
            continue

        query = QueryBuilder() if query is None else query
        query = query[query[column] == flag]

    # ArcticDB stores Date columns as naive datetime[ns]; compare as midnight.
    if ipo_start is not None:
        query = QueryBuilder() if query is None else query
        query = query[query["ipo_date"] >= datetime.combine(ipo_start, time.min)]

    if ipo_end is not None:
        query = QueryBuilder() if query is None else query
        query = query[query["ipo_date"] <= datetime.combine(ipo_end, time.min)]

    return query


# ====================================
# --> Models
# ====================================


class UniverseTicker(BaseModel):
    """One stored ticker-universe row."""

    symbol: str
    company_name: str | None
    security_type: str | None
    exchange: str | None
    exchange_full_name: str | None
    sector: str | None
    industry: str | None
    country: str | None
    currency: str | None
    market_cap: float | None
    beta: float | None
    price: float | None
    ipo_date: date | None
    cik: str | None
    isin: str | None
    cusip: str | None
    is_etf: bool | None
    is_fund: bool | None
    is_adr: bool | None
    last_updated: datetime | None


class UniverseResponse(BaseModel):
    """Ticker-universe rows and their count."""

    count: int
    data: list[UniverseTicker]


# ====================================
# --> Endpoint
# ====================================


@router.get("", response_model=UniverseResponse)
def get_universe(
    symbols: Annotated[list[str] | None, Query()] = None,
    security_type: Annotated[list[str] | None, Query()] = None,
    exchange: Annotated[list[str] | None, Query()] = None,
    sector: Annotated[list[str] | None, Query()] = None,
    industry: Annotated[list[str] | None, Query()] = None,
    country: Annotated[list[str] | None, Query()] = None,
    is_etf: bool | None = None,
    is_fund: bool | None = None,
    is_adr: bool | None = None,
    ipo_start: date | None = None,
    ipo_end: date | None = None,
    library: Library = Depends(get_library),
) -> UniverseResponse:
    """Return the stored ticker universe, narrowed by the given filters.

    Omit every filter to get the whole universe. Repeat a query parameter to
    accept several values (``?sector=Technology&sector=Energy``); different
    parameters AND together. Values other than ``symbols`` match exactly as
    the vendor spells them — ``Technology``, ``NASDAQ``, ``common``.
    ``ipo_start`` / ``ipo_end`` are inclusive IPO-date bounds.
    """
    if ipo_start is not None and ipo_end is not None and ipo_start > ipo_end:
        raise HTTPException(
            status_code=422,
            detail="ipo_start must be on or before ipo_end",
        )

    where = _where(
        {
            "security_type": security_type,
            "exchange": exchange,
            "sector": sector,
            "industry": industry,
            "country": country,
        },
        {"is_etf": is_etf, "is_fund": is_fund, "is_adr": is_adr},
        ipo_start=ipo_start,
        ipo_end=ipo_end,
    )

    frame = read(library, TICKER_UNIVERSE, symbols=symbols, where=where)

    return UniverseResponse(
        count=frame.height,
        data=[UniverseTicker(**row) for row in frame.to_dicts()],
    )
