"""Seed 15 years of daily OHLCV for the whole ticker universe into ArcticDB.

Run as ``uv run python -m scripts.seed_daily_prices`` from the repo root.

There is no bulk shortcut for this backfill (see the note in
``vendors.fmp.prices``), so it costs one HTTP call per ticker — roughly an
hour for the current ~9,400-name universe. A run that long has to survive
being interrupted, so it happens in two phases:

1. **stage** — tickers are fetched a shard at a time and written to local
   parquet. Each finished shard is recorded in a manifest, and a rerun skips
   everything the manifest already lists, so an interrupted seed picks up
   where it stopped instead of starting over.
2. **load** — the staged shards are upserted into `daily_prices` one calendar
   year at a time.

Staging is left on disk afterwards; delete ``data/daily_prices_staging`` once
the load looks right.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import polars as pl
from arcticdb.version_store.library import Library

from src.config import require
from src.storage.arctic import DAILY_PRICES, TICKER_UNIVERSE, connect, read, upsert
from src.vendors.fmp import fetch_daily_prices
from src.vendors.fmp.helpers import DEFAULT_REQUESTS_PER_MINUTE

STAGING_DIR = Path("data/daily_prices_staging")
MANIFEST_NAME = "manifest.jsonl"

# Tickers per shard. Small enough that an interrupted run loses little work,
# large enough that the manifest stays short.
SHARD_SIZE = 100

# A shard holds ~100 tickers x 15y, so the whole seed is ~9,400 calls; the
# per-symbol timeout matters more than the total.
TIMEOUT_SECONDS = 120.0


# ====================================
# --> Helper funcs
# ====================================


def _shards(symbols: list[str], size: int) -> list[list[str]]:
    return [symbols[i : i + size] for i in range(0, len(symbols), size)]


def _staged_symbols(manifest: Path) -> set[str]:
    """Every symbol a previous run finished staging."""
    if not manifest.exists():
        return set()

    done: set[str] = set()

    for line in manifest.read_text().splitlines():
        if line.strip():
            done.update(json.loads(line)["symbols"])

    return done


def _write_shard(path: Path, frame: pl.DataFrame) -> None:
    """Write a shard atomically so a crash mid-write leaves no torn parquet."""
    temporary = path.with_suffix(".tmp")

    frame.write_parquet(temporary)
    os.replace(temporary, path)


def _record(manifest: Path, part: int, symbols: list[str], rows: int) -> None:
    """Append a finished shard to the manifest.

    Written after the parquet lands, never before: a crash in between only
    costs a refetch, whereas the reverse would silently skip missing tickers.
    """
    entry = json.dumps({"part": part, "symbols": symbols, "rows": rows})

    with manifest.open("a") as handle:
        handle.write(entry + "\n")


# ====================================
# --> Phases
# ====================================


def stage(
    symbols: list[str],
    api_key: str,
    staging: Path,
    *,
    shard_size: int = SHARD_SIZE,
    requests_per_minute: float = DEFAULT_REQUESTS_PER_MINUTE,
) -> list[str]:
    """Fetch every not-yet-staged symbol into local parquet shards.

    Returns the symbols whose shard failed; rerunning the script retries them.
    """
    staging.mkdir(parents=True, exist_ok=True)
    manifest = staging / MANIFEST_NAME

    already = _staged_symbols(manifest)
    todo = [symbol for symbol in symbols if symbol not in already]

    if already:
        print(f"Resuming: {len(already):,} of {len(symbols):,} tickers already staged")
    if not todo:
        print("Nothing left to stage")
        return []

    # Keep numbering past any shard an earlier run wrote.
    part = len(list(staging.glob("part-*.parquet")))
    batches = _shards(todo, shard_size)
    failed: list[str] = []
    done = 0

    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        for number, batch in enumerate(batches, start=1):
            try:
                frame = fetch_daily_prices(
                    batch,
                    api_key,
                    client=client,
                    requests_per_minute=requests_per_minute,
                    wait=lambda seconds, attempt: print(
                        f"  rate limited, retry {attempt} in {seconds:.0f}s"
                    ),
                )
            except (httpx.HTTPError, RuntimeError) as error:
                # One bad shard should not cost the other 9,300 tickers; the
                # manifest stays unwritten, so a rerun picks this batch back up.
                failed.extend(batch)
                print(f"shard {number}/{len(batches)}: FAILED ({error}) — will retry")
                continue

            _write_shard(staging / f"part-{part:05d}.parquet", frame)
            _record(manifest, part, batch, frame.height)

            part += 1
            done += len(batch)

            print(
                f"shard {number}/{len(batches)}: {len(batch)} tickers → "
                f"{frame.height:,} rows ({done:,}/{len(todo):,} staged)"
            )

    return failed


def load(library: Library, staging: Path) -> int:
    """Upsert every staged shard into `daily_prices`, a calendar year at a time.

    Year-sized chunks keep peak memory at one year of rows, and hold each
    upsert's date range to that year so ArcticDB rewrites only that slice.
    """
    shards = sorted(staging.glob("part-*.parquet"))
    if not shards:
        raise RuntimeError(f"No staged shards in {staging}")

    scan = pl.scan_parquet(shards)
    span = scan.select(
        pl.col("date").min().alias("first"), pl.col("date").max().alias("last")
    ).collect()

    first, last = span["first"].item(), span["last"].item()
    total = 0

    for year in range(first.year, last.year + 1):
        chunk = scan.filter(pl.col("date").dt.year() == year).collect()

        if chunk.is_empty():
            continue

        upsert(library, DAILY_PRICES, chunk)

        total += chunk.height
        print(f"  {year}: {chunk.height:,} rows")

    return total


def main() -> None:
    (api_key,) = require("FMP_API_KEY")
    library = connect()

    universe = read(library, TICKER_UNIVERSE, columns=["symbol"])
    symbols = universe["symbol"].to_list()

    print(f"Universe: {len(symbols):,} tickers")

    failed = stage(symbols, api_key, STAGING_DIR)

    print(f"\nLoading staged shards into '{DAILY_PRICES.symbol}'...")
    rows = load(library, STAGING_DIR)

    print(f"\nUpserted {rows:,} rows into '{DAILY_PRICES.symbol}'")

    if failed:
        print(
            f"{len(failed):,} tickers failed to stage — rerun this script to "
            f"retry them: {', '.join(failed[:10])}"
            f"{'...' if len(failed) > 10 else ''}"
        )


if __name__ == "__main__":
    main()
