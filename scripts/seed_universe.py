"""Seed the ticker universe from FMP profile-bulk into ArcticDB.

Run as ``uv run python -m scripts.seed_universe`` from the repo root.
"""

from __future__ import annotations

from src.config import require
from src.storage.arctic import TICKER_UNIVERSE, connect, write
from src.vendors.fmp import fetch_ticker_universe


def main() -> None:
    (api_key,) = require("FMP_API_KEY")

    print("Fetching FMP profile-bulk (actively trading US common stock and ETFs)...")
    universe = fetch_ticker_universe(api_key, notify=print)

    write(connect(), TICKER_UNIVERSE, universe)

    print(f"Wrote {universe.height:,} rows to '{TICKER_UNIVERSE.symbol}'")


if __name__ == "__main__":
    main()
