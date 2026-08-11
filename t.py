from datetime import date
import os
import databento as db
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from src.config import require
from src.storage.arctic import DAILY_PRICES, connect, read

bucket, region = require('S3_BUCKET', 'AWS_DEFAULT_REGION')
library = connect(bucket, region)
df = read(library, DAILY_PRICES, symbols='AAPL', start=date(2025, 1, 1), end=date(2026, 1, 31))
print(df.head(10))
print(df.tail(5))
