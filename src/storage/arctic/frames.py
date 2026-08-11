"""Polars ↔ ArcticDB frame boundary.

ArcticDB widens every temporal column to naive ``datetime[ns]`` and requires
pandas on the write path. These helpers are the round-trip, not defensive
coding: ``conform`` restores declared dtypes on read, and ``to_pandas``
sorts by key because ``Library.update`` rejects unsorted input. Never write a
MultiIndex — only a single named timestamp index round-trips cleanly.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from src.storage.arctic.dataset import Dataset


# ====================================
# --> Helper funcs
# ====================================


def conform(frame: pl.DataFrame, schema: dict[str, Any]) -> pl.DataFrame:
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


def merge(stored: pl.DataFrame, fresh: pl.DataFrame, dataset: Dataset) -> pl.DataFrame:
    """Overlay ``fresh`` onto ``stored``, keyed by the dataset's key columns."""
    key = list(dataset.key)

    return (
        # `fresh` goes last so keep="last" lets refreshed rows win. Order matters.
        pl.concat([stored, fresh], how="vertical_relaxed")
        .unique(subset=key, keep="last", maintain_order=True)
        .sort(key)
    )


def to_pandas(frame: pl.DataFrame, dataset: Dataset):
    """Conform, order, and hand ArcticDB a pandas frame indexed as declared.

    Pandas appears only here: ArcticDB's write path requires it, and `update`
    rejects unsorted input, so the sort is not cosmetic.
    """
    ordered = (
        conform(frame, dataset.schema).select(dataset.columns).sort(list(dataset.key))
    )
    pandas_frame = ordered.to_pandas()

    if dataset.time_index is None:
        return pandas_frame

    return pandas_frame.set_index(dataset.time_index)
