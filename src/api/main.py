"""HTTP application for the stored market data."""

from __future__ import annotations

from fastapi import FastAPI

from src.api.daily_prices import router as daily_prices_router


app = FastAPI(title="Systematic Trading Data API")

app.include_router(daily_prices_router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Report that the API process is running."""
    return {"status": "ok"}
