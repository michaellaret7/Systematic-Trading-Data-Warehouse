import polars as pl
from arcticdb import Arctic, OutputFormat
from arcticdb.version_store.library import Library


LIBRARY_NAME = "market_data"
DAILY_PRICES_SYMBOL = "daily_prices"

SCHEMA = {
    "symbol": pl.String,
    "date": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Int64,
}


def connect(bucket: str, region: str) -> Library:
    uri = (
        f"s3s://s3.{region}.amazonaws.com:{bucket}"
        f"?region={region}&aws_auth=default&path_prefix=arcticdb"
    )
    arctic = Arctic(uri, output_format=OutputFormat.POLARS)
    return arctic.get_library(LIBRARY_NAME, create_if_missing=True)


def read_daily_prices(library: Library) -> pl.DataFrame:
    if not library.has_symbol(DAILY_PRICES_SYMBOL):
        return pl.DataFrame(schema=SCHEMA)

    return (
        library.read(DAILY_PRICES_SYMBOL)
        .data.with_columns(pl.col("date").cast(pl.Date))
        .select(list(SCHEMA))
    )


def write_daily_prices(library: Library, prices: pl.DataFrame) -> None:
    frame = prices.sort(["date", "symbol"]).to_pandas()
    library.write(DAILY_PRICES_SYMBOL, frame.set_index(["date", "symbol"]))
