"""Generic read / write / upsert over declared datasets."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Any

import polars as pl
from arcticdb import QueryBuilder
from arcticdb.version_store.library import Library

from src.storage.arctic.dataset import Dataset
from src.storage.arctic.frames import conform, merge, to_pandas


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

    return conform(frame, schema).select(selection)


def write(library: Library, dataset: Dataset, frame: pl.DataFrame) -> None:
    """Replace a dataset's entire contents with ``frame``."""
    library.write(dataset.symbol, to_pandas(frame, dataset))


def upsert(library: Library, dataset: Dataset, fresh: pl.DataFrame) -> None:
    """Merge ``fresh`` into a dataset on its key columns; rows in ``fresh`` win.

    On a time-indexed dataset only the date range ``fresh`` spans is read and
    rewritten, so a daily refresh costs one day rather than the whole history.
    """
    if fresh.is_empty():
        return

    fresh = conform(fresh, dataset.schema).select(dataset.columns)
    index = dataset.time_index

    if index is None:
        write(library, dataset, merge(read(library, dataset), fresh, dataset))
        return

    start, end = fresh[index].min(), fresh[index].max()
    stored = read(library, dataset, start=start, end=end)
    merged = merge(stored, fresh, dataset)

    # `update` replaces exactly this range, and creates the symbol when absent.
    library.update(
        dataset.symbol,
        to_pandas(merged, dataset),
        date_range=(start, end),
        upsert=True,
    )
