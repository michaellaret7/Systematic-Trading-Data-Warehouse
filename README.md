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
uv run python -m scripts.update_daily_prices AAPL MSFT
```

The table contains `symbol`, `date`, `open`, `high`, `low`, `close`, and `volume`.
Rerunning the command updates rows by `(symbol, date)` and keeps every ticker in
the same logical ArcticDB table. ArcticDB manages its own versioned objects in S3;
it does not create a Parquet file.
