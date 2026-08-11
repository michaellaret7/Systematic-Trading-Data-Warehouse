"""ArcticDB storage layer.

Tables are described declaratively (symbol, schema, index, upsert key) and
served by one generic ``read_table`` / ``write_table`` / ``upsert_table``
trio. Adding a dataset means adding a ``Table`` entry, not another pair of
hand-written functions.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import os
from dotenv import load_dotenv
import polars as pl
from arcticdb import Arctic, OutputFormat, QueryBuilder
from arcticdb.version_store.library import Library

from src.vendors.fmp import DAILY_PRICES_SCHEMA, TICKER_UNIVERSE_SCHEMA

load_dotenv()

LIBRARY_NAME = "market_data"


@dataclass(frozen=True)
class Table:
    """One ArcticDB symbol and the shape of the frame stored in it."""

    symbol: str
    schema: dict[str, Any]
    #: Columns written as the pandas index (ArcticDB indexes/filters on these).
    index: tuple[str, ...]
    #: Columns identifying a row for upserts; defaults to ``index``.
    key: tuple[str, ...] = ()
    #: Write-time sort order; defaults to ``index``.
    sort_by: tuple[str, ...] = ()
    #: Column holding the ticker, for ``symbols=`` filters.
    symbol_column: str = "symbol"

    @property
    def columns(self) -> list[str]:
        return list(self.schema)

    @property
    def key_columns(self) -> list[str]:
        return list(self.key or self.index)

    @property
    def sort_columns(self) -> list[str]:
        return list(self.sort_by or self.index)

    @property
    def is_time_indexed(self) -> bool:
        """True when index level 0 is temporal, i.e. ``date_range`` applies."""
        return self.schema[self.index[0]] in (pl.Date, pl.Datetime)

    def selection(self, columns: Sequence[str] | None) -> list[str]:
        """Index columns plus ``columns``, in schema order, validated."""
        if columns is None:
            return self.columns
        unknown = [name for name in columns if name not in self.schema]
        if unknown:
            # ArcticDB silently ignores unknown columns; a typo should not
            # quietly return fewer columns than asked for.
            raise ValueError(f"{self.symbol} has no column(s): {sorted(unknown)}")
        wanted = set(columns) | set(self.index)
        return [name for name in self.schema if name in wanted]


DAILY_PRICES = Table(
    symbol="daily_prices",
    schema=DAILY_PRICES_SCHEMA,
    index=("date", "symbol"),
    key=("symbol", "date"),
)

TICKER_UNIVERSE = Table(
    symbol="ticker_universe",
    schema=TICKER_UNIVERSE_SCHEMA,
    index=("symbol",),
)

TABLES: dict[str, Table] = {
    table.symbol: table for table in (DAILY_PRICES, TICKER_UNIVERSE)
}

DAILY_PRICES_SYMBOL = DAILY_PRICES.symbol
TICKER_UNIVERSE_SYMBOL = TICKER_UNIVERSE.symbol


def connect(bucket: str, region: str) -> Library:
    uri = (
        f"s3s://s3.{region}.amazonaws.com:{bucket}"
        f"?region={region}&aws_auth=default&path_prefix=arcticdb"
    )
    arctic = Arctic(uri, output_format=OutputFormat.POLARS)
    return arctic.get_library(LIBRARY_NAME, create_if_missing=True)


def _restore_index_columns(frame: pl.DataFrame, table: Table) -> pl.DataFrame:
    """Rename index columns back to their declared names.

    The Polars output format usually materializes the pandas index as normal
    columns, but depending on the write path an index level can surface as
    ``index``, ``level_0``, or ``<name>_0``.
    """
    renames: dict[str, str] = {}
    for position, name in enumerate(table.index):
        if name in frame.columns:
            continue
        candidates = [f"{name}_0", f"level_{position}"]
        if len(table.index) == 1:
            candidates.append("index")
        for candidate in candidates:
            if candidate in frame.columns and candidate not in renames:
                renames[candidate] = name
                break
    return frame.rename(renames) if renames else frame


def _conform_to_schema(frame: pl.DataFrame, schema: dict[str, Any]) -> pl.DataFrame:
    """Cast every declared column to its schema dtype and add missing ones."""
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


DateRange = tuple[date | datetime | None, date | datetime | None]


def _symbol_query(
    table: Table,
    symbols: Sequence[str],
    query: QueryBuilder | None,
) -> QueryBuilder:
    if table.symbol_column not in table.schema:
        raise ValueError(f"{table.symbol} has no '{table.symbol_column}' column")
    builder = QueryBuilder() if query is None else query
    return builder[builder[table.symbol_column].isin(list(symbols))]


def read_table(
    library: Library,
    table: Table,
    *,
    symbols: str | Iterable[str] | None = None,
    date_range: DateRange | None = None,
    columns: Sequence[str] | None = None,
    query: QueryBuilder | None = None,
) -> pl.DataFrame:
    """Read a table, or an empty correctly-typed frame if it does not exist.

    All filters are pushed down into ArcticDB rather than applied after a
    full read:

    ``symbols``
        Ticker(s) to keep, as an ArcticDB filter. A bare string is one ticker.
    ``date_range``
        ``(start, end)`` on the time index; either side may be None for an
        open-ended range. Whole row-segments outside the range are never
        fetched from storage.
    ``columns``
        Columns to fetch besides the index. Unlisted columns are not read.
    ``query``
        An explicit ``QueryBuilder`` for anything else; combined with
        ``symbols`` when both are given.
    """
    selection = table.selection(columns)

    if symbols is not None:
        symbols = [symbols] if isinstance(symbols, str) else list(symbols)
        symbols = [str(s).upper().strip() for s in symbols if str(s).strip()]

    empty = pl.DataFrame(schema={name: table.schema[name] for name in selection})
    if symbols is not None and not symbols:
        return empty
    if not library.has_symbol(table.symbol):
        return empty

    if symbols is not None:
        query = _symbol_query(table, symbols, query)

    read_kwargs: dict[str, Any] = {}
    if columns is not None:
        # ArcticDB returns index columns regardless; ask only for the rest.
        read_kwargs["columns"] = [c for c in selection if c not in table.index]
    if date_range is not None:
        if not table.is_time_indexed:
            raise ValueError(
                f"{table.symbol} is indexed by {table.index[0]!r}, "
                "which is not a time index; date_range does not apply"
            )
        read_kwargs["date_range"] = tuple(date_range)
    if query is not None:
        read_kwargs["query_builder"] = query

    frame = library.read(table.symbol, **read_kwargs).data
    frame = _restore_index_columns(frame, table)
    frame = _conform_to_schema(frame, {name: table.schema[name] for name in selection})
    return frame.select(selection)


def write_table(library: Library, table: Table, frame: pl.DataFrame) -> None:
    """Replace a table's contents with ``frame``."""
    pandas_frame = (
        _conform_to_schema(frame, table.schema)
        .select(table.columns)
        .sort(table.sort_columns)
        .to_pandas()
        .set_index(list(table.index))
    )
    library.write(table.symbol, pandas_frame)


def upsert_table(library: Library, table: Table, fresh: pl.DataFrame) -> pl.DataFrame:
    """Merge ``fresh`` into a table on its key columns and return the result.

    Rows in ``fresh`` win over stored rows with the same key.
    """
    existing = read_table(library, table)
    if fresh.is_empty():
        return existing

    merged = (
        # `fresh` goes last so keep="last" lets refreshed rows win.
        pl.concat(
            [existing, _conform_to_schema(fresh, table.schema).select(table.columns)],
            how="vertical_relaxed",
        )
        .unique(subset=table.key_columns, keep="last")
        .sort(table.sort_columns)
    )
    write_table(library, table, merged)
    return merged


def read_daily_prices(
    library: Library,
    *,
    symbols: str | Iterable[str] | None = None,
    start: date | datetime | None = None,
    end: date | datetime | None = None,
    columns: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Read daily OHLCV, filtering by ticker and date range in storage."""
    return read_table(
        library,
        DAILY_PRICES,
        symbols=symbols,
        date_range=(start, end) if start is not None or end is not None else None,
        columns=columns,
    )


def write_daily_prices(library: Library, prices: pl.DataFrame) -> None:
    write_table(library, DAILY_PRICES, prices)


def read_ticker_universe(
    library: Library,
    *,
    symbols: str | Iterable[str] | None = None,
    columns: Sequence[str] | None = None,
) -> pl.DataFrame:
    return read_table(library, TICKER_UNIVERSE, symbols=symbols, columns=columns)


def write_ticker_universe(library: Library, universe: pl.DataFrame) -> None:
    write_table(library, TICKER_UNIVERSE, universe)


if __name__ == "__main__":
    library = connect(os.environ.get("S3_BUCKET"), os.environ.get("AWS_DEFAULT_REGION"))
    x = read_ticker_universe(library)
    x = pl.DataFrame(x)
    x = x.filter(pl.col("is_etf") == True, pl.col("is_fund") == False, pl.col("is_adr") == False)
    print(x.head(25))
