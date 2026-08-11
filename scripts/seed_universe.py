"""Seed the ticker universe from FMP profile-bulk into ArcticDB."""

from __future__ import annotations

import os
import sys
from typing import Any

from dotenv import load_dotenv

# Allow `uv run python scripts/seed_universe.py` from the repo root.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.storage.arctic import (  # noqa: E402
    TICKER_UNIVERSE_SYMBOL,
    connect,
    write_ticker_universe,
)
from src.vendors.fmp import fetch_ticker_universe  # noqa: E402

load_dotenv()

BAR_WIDTH = 24


def _bar(fraction: float, width: int = BAR_WIDTH) -> str:
    filled = int(round(max(0.0, min(1.0, fraction)) * width))
    return "█" * filled + "░" * (width - filled)


class ProgressPrinter:
    """Render ``fetch_ticker_universe`` progress on a single live line.

    The number of parts is only known once FMP returns an empty page, so the
    bar tracks the rate-limit wait (the part of the run that actually takes
    time) while parts and kept-row counts tick up alongside it.
    """

    def __init__(self, stream: Any = sys.stdout) -> None:
        self._stream = stream
        self._width = 0
        self._live = stream.isatty()

    def _write(self, line: str, *, keep: bool = False) -> None:
        if not self._live:
            if keep:
                print(line, file=self._stream, flush=True)
            return
        padding = " " * max(0, self._width - len(line))
        end = "\n" if keep else ""
        self._stream.write(f"\r{line}{padding}{end}")
        self._stream.flush()
        self._width = 0 if keep else len(line)

    def __call__(self, event: str, data: dict[str, Any]) -> None:
        if event == "fetching":
            self._write(
                f"part {data['part'] + 1}/{data['max_parts']}  "
                f"downloading…  {data['kept']:,} tickers"
            )
        elif event == "part_done":
            self._write(
                f"part {data['part'] + 1}/{data['max_parts']}  "
                f"+{data['part_rows']:,} rows  →  {data['kept']:,} tickers",
                keep=True,
            )
        elif event == "waiting":
            left = data["seconds_left"]
            total = data["seconds_total"]
            if data.get("reason") == "rate_limit":
                label = f"rate limited, retry {data['attempt'] + 1}"
            else:
                label = f"pacing part {data['part'] + 1}"
            self._write(f"{label}  [{_bar(1 - left / total)}]  {left:3.0f}s")
        elif event == "finished":
            self._write("", keep=self._width > 0)


def main() -> None:
    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        raise RuntimeError("Set FMP_API_KEY before running seed_universe")

    bucket = os.environ.get("S3_BUCKET")
    if not bucket:
        raise RuntimeError("Set S3_BUCKET before running seed_universe")

    region = os.environ.get("AWS_DEFAULT_REGION")
    if not region:
        raise RuntimeError("Set AWS_DEFAULT_REGION before running seed_universe")

    print("Fetching FMP profile-bulk (actively trading only)...")
    universe = fetch_ticker_universe(api_key, on_progress=ProgressPrinter())
    print(f"Loaded {universe.height} actively trading tickers")

    library = connect(bucket, region)
    write_ticker_universe(library, universe)
    print(
        f"Wrote {universe.height} rows to ArcticDB library "
        f"'market_data' symbol '{TICKER_UNIVERSE_SYMBOL}'"
    )


if __name__ == "__main__":
    main()
