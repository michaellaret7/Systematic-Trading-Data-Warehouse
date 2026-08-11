"""Open the market_data ArcticDB library."""

from __future__ import annotations

from arcticdb import Arctic, OutputFormat
from arcticdb.version_store.library import Library

from src.config import require


LIBRARY_NAME = "market_data"


def connect() -> Library:
    """Open the `market_data` library on S3, creating it if it is missing."""
    bucket, region = require("S3_BUCKET", "AWS_DEFAULT_REGION")

    uri = (
        f"s3s://s3.{region}.amazonaws.com:{bucket}"
        f"?region={region}&aws_auth=default&path_prefix=arcticdb"
    )

    arctic = Arctic(uri, output_format=OutputFormat.POLARS)

    return arctic.get_library(LIBRARY_NAME, create_if_missing=True)
