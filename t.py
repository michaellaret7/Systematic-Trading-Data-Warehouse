from datetime import date
from io import BytesIO

import pandas as pd
import requests

BENCHMARK = "SPY"
WINDOW = 60

response = requests.get(
    "http://159.203.132.63:8000/v1/universe",
    params={
        "sector": "Technology",
        "industry": "Semiconductors",
    },
)
response.raise_for_status()
symbols = [row["symbol"] for row in response.json()["data"]]

import time
start_time = time.time()
response = requests.get(
    "http://159.203.132.63:8000/v1/daily-prices",
    params={
        "symbols": symbols,
        # Extra history so the first 60 trading days aren't all NaN.
        "start": date(2020, 1, 1).isoformat(),
        "end": date(2026, 8, 1).isoformat(),
    },
)
response.raise_for_status()
end_time = time.time()
print(f"Time taken: {end_time - start_time} seconds")

df = pd.DataFrame(response.json()["data"])

print(df.head())
print(df.tail())