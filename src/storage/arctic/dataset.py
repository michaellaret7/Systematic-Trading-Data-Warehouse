"""Declarative ArcticDB dataset: symbol, schema, and row key."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl


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
