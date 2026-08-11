"""ArcticDB storage layer.

A dataset is declared once as a ``Dataset``; ``read`` / ``write`` / ``upsert``
serve every one of them. Filters are pushed into ArcticDB instead of being
applied after a full read, and ``upsert`` rewrites only the date range it
touches rather than the whole table.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import polars as pl
from arcticdb import Arctic, OutputFormat, QueryBuilder
from arcticdb.version_store.library import Library
import os
from dotenv import load_dotenv

from src.vendors.fmp import DAILY_PRICES_SCHEMA, TICKER_UNIVERSE_SCHEMA

load_dotenv()


LIBRARY_NAME = "market_data"


# ====================================
# --> Helper funcs
# ====================================


def _conform(frame: pl.DataFrame, schema: dict[str, Any]) -> pl.DataFrame:
    """Cast every declared column to its dtype and add any that are missing.

    ArcticDB stores all temporal columns as naive nanosecond datetimes, so
    ``pl.Date`` and tz-aware columns come back widened and have to be cast
    back on the way out. This is not defensive — it is the round-trip.
    """
    casts = [
        pl.col(name).cast(dtype, strict=False)
        for name, dtype in schema.items()
        if name in frame.columns and frame.schema[name] != dtype
    ]
    if casts:
        frame = frame.with_columns(casts)

    missing = [
        pl.lit(None).cast(dtype).alias(name)
        for name, dtype in schema.items()
        if name not in frame.columns
    ]
    if missing:
        frame = frame.with_columns(missing)

    return frame


def _merge(stored: pl.DataFrame, fresh: pl.DataFrame, dataset: Dataset) -> pl.DataFrame:
    """Overlay ``fresh`` onto ``stored``, keyed by the dataset's key columns."""
    key = list(dataset.key)

    return (
        # `fresh` goes last so keep="last" lets refreshed rows win. Order matters.
        pl.concat([stored, fresh], how="vertical_relaxed")
        .unique(subset=key, keep="last", maintain_order=True)
        .sort(key)
    )


def _to_pandas(frame: pl.DataFrame, dataset: Dataset):
    """Conform, order, and hand ArcticDB a pandas frame indexed as declared.

    Pandas appears only here: ArcticDB's write path requires it, and `update`
    rejects unsorted input, so the sort is not cosmetic.
    """
    ordered = (
        _conform(frame, dataset.schema).select(dataset.columns).sort(list(dataset.key))
    )
    pandas_frame = ordered.to_pandas()

    if dataset.time_index is None:
        return pandas_frame

    return pandas_frame.set_index(dataset.time_index)


# ====================================
# --> Dataset declarations
# ====================================


@dataclass(frozen=True)
class Dataset:
    """One ArcticDB symbol: its Polars schema and the columns identifying a row."""

    symbol: str
    schema: dict[str, Any]
    #: Columns identifying a row, most significant first. Also the sort order.
    key: tuple[str, ...]

    @property
    def columns(self) -> list[str]:
        return list(self.schema)

    @property
    def time_index(self) -> str | None:
        """The column written as the pandas index, if the key leads with a date.

        Only a timestamp index earns ArcticDB anything: it is what row-segment
        pruning and ``update``'s range replacement key off. A string index buys
        nothing and costs a round-trip that mangles the column name, so
        non-temporal datasets are stored on a plain RangeIndex.
        """
        leading = self.key[0]
        return leading if self.schema[leading] in (pl.Date, pl.Datetime) else None


DAILY_PRICES = Dataset(
    symbol="daily_prices",
    schema=DAILY_PRICES_SCHEMA,
    key=("date", "symbol"),
)

TICKER_UNIVERSE = Dataset(
    symbol="ticker_universe",
    schema=TICKER_UNIVERSE_SCHEMA,
    key=("symbol",),
)


# ====================================
# --> Storage API
# ====================================


def connect() -> Library:
    """Open the `market_data` library on S3, creating it if it is missing."""
    bucket = os.environ["S3_BUCKET"]
    region = os.environ["AWS_DEFAULT_REGION"]

    uri = (
        f"s3s://s3.{region}.amazonaws.com:{bucket}"
        f"?region={region}&aws_auth=default&path_prefix=arcticdb"
    )

    arctic = Arctic(uri, output_format=OutputFormat.POLARS)

    return arctic.get_library(LIBRARY_NAME, create_if_missing=True)


def read(
    library: Library,
    dataset: Dataset,
    *,
    symbols: str | Iterable[str] | None = None,
    start: date | datetime | None = None,
    end: date | datetime | None = None,
    columns: Sequence[str] | None = None,
    where: QueryBuilder | None = None,
) -> pl.DataFrame:
    """Read a dataset, or an empty typed frame if it has never been written.

    Every filter is pushed into ArcticDB: ``symbols`` and ``where`` become
    predicates, ``start`` / ``end`` skip whole row-segments in storage, and
    columns outside ``columns`` are never fetched. Key columns always come
    back. ``where`` takes a raw ``QueryBuilder`` for anything else, and is
    combined with ``symbols`` when both are given.
    """
    if columns is None:
        selection = dataset.columns
    else:
        unknown = [name for name in columns if name not in dataset.schema]
        if unknown:
            # ArcticDB silently ignores unknown column names; a typo should not
            # quietly return fewer columns than were asked for.
            raise ValueError(f"{dataset.symbol} has no column(s): {sorted(unknown)}")
        wanted = set(columns) | set(dataset.key)
        selection = [name for name in dataset.schema if name in wanted]

    schema = {name: dataset.schema[name] for name in selection}
    empty = pl.DataFrame(schema=schema)

    if symbols is not None:
        # A bare string is one ticker; tickers are upper-cased at every entry point.
        raw = [symbols] if isinstance(symbols, str) else symbols
        tickers = [str(value).upper().strip() for value in raw if str(value).strip()]
        if not tickers:
            return empty
        where = QueryBuilder() if where is None else where
        where = where[where["symbol"].isin(tickers)]

    if not library.has_symbol(dataset.symbol):
        return empty

    kwargs: dict[str, Any] = {}
    if columns is not None:
        # ArcticDB returns the index column regardless; ask only for the rest.
        kwargs["columns"] = [n for n in selection if n != dataset.time_index]
    if start is not None or end is not None:
        if dataset.time_index is None:
            raise ValueError(
                f"{dataset.symbol} is keyed on {dataset.key[0]!r}, which is not a "
                "time index; start/end do not apply"
            )
        kwargs["date_range"] = (start, end)
    if where is not None:
        kwargs["query_builder"] = where

    frame = library.read(dataset.symbol, **kwargs).data

    return _conform(frame, schema).select(selection)


def write(library: Library, dataset: Dataset, frame: pl.DataFrame) -> None:
    """Replace a dataset's entire contents with ``frame``."""
    library.write(dataset.symbol, _to_pandas(frame, dataset))


def upsert(library: Library, dataset: Dataset, fresh: pl.DataFrame) -> None:
    """Merge ``fresh`` into a dataset on its key columns; rows in ``fresh`` win.

    On a time-indexed dataset only the date range ``fresh`` spans is read and
    rewritten, so a daily refresh costs one day rather than the whole history.
    """
    if fresh.is_empty():
        return

    fresh = _conform(fresh, dataset.schema).select(dataset.columns)
    index = dataset.time_index

    if index is None:
        write(library, dataset, _merge(read(library, dataset), fresh, dataset))
        return

    start, end = fresh[index].min(), fresh[index].max()
    stored = read(library, dataset, start=start, end=end)
    merged = _merge(stored, fresh, dataset)

    # `update` replaces exactly this range, and creates the symbol when absent.
    library.update(
        dataset.symbol,
        _to_pandas(merged, dataset),
        date_range=(start, end),
        upsert=True,
    )


if __name__ == "__main__":
    q = QueryBuilder()
    library = connect()
    universe = read(
        library,
        TICKER_UNIVERSE,
        where=q[(q["is_etf"] == True) & (q["is_fund"] == False) & (q["is_adr"] == False)],
    )
    print(universe.columns)