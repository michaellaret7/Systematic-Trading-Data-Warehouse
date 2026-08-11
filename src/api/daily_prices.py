"""Read-only HTTP endpoint for stored daily equity prices."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from arcticdb.version_store.library import Library
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.dependencies import get_library
from src.storage.arctic import DAILY_PRICES, read


router = APIRouter(prefix="/v1/daily-prices", tags=["daily-prices"])


class DailyPrice(BaseModel):
    """One stored daily OHLCV row."""

    symbol: str
    date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    adj_close: float | None
    volume: int | None


class DailyPricesResponse(BaseModel):
    """Daily price rows and their count."""

    count: int
    data: list[DailyPrice]


@router.get("", response_model=DailyPricesResponse)
def get_daily_prices(
    symbols: Annotated[list[str], Query(min_length=1)],
    start: date | None = None,
    end: date | None = None,
    library: Library = Depends(get_library),
) -> DailyPricesResponse:
    """Return stored daily prices for one or more symbols.

    ``start`` and ``end`` are inclusive when present. Repeat the ``symbols``
    query parameter to request more than one ticker.
    """
    if start is not None and end is not None and start > end:
        raise HTTPException(
            status_code=422,
            detail="start must be on or before end",
        )

    frame = read(
        library,
        DAILY_PRICES,
        symbols=symbols,
        start=start,
        end=end,
    )

    return DailyPricesResponse(
        count=frame.height,
        data=[DailyPrice(**row) for row in frame.to_dicts()],
    )
