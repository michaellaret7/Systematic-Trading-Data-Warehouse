# Systematic Trading Data Warehouse

The first feature downloads FMP daily equity prices into one ArcticDB symbol backed by S3:

```text
library: market_data
symbol:  daily_prices
storage: s3://<S3_BUCKET>/arcticdb
```

Install and run:

```bash
uv sync
set -a; source .env; set +a
uv run python -m src.jobs.update_equities AAPL MSFT
```

One call covers every ticker you pass; pass a single symbol to update just that
one. Seed the ticker universe (FMP profile-bulk) separately:

```bash
uv run python -m scripts.seed_universe
```

The table contains `symbol`, `date`, `open`, `high`, `low`, `close`, and `volume`.
Rerunning the command updates rows by `(symbol, date)` and keeps every ticker in
the same logical ArcticDB table. ArcticDB manages its own versioned objects in S3;
it does not create a Parquet file.
