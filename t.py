from datetime import date
from io import BytesIO

import pandas as pd
import requests

BENCHMARK = "SPY"
WINDOW = 60

response = requests.get(
    "http://174.138.72.10:8000/v1/universe",
    params={
        "security_type": ["etf"],
    },
)
response.raise_for_status()
symbols = [row["symbol"] for row in response.json()["data"]]


import time

# GET /v1/daily-prices repeats `symbols=` in the query string. uvicorn rejects
# the request line once it grows past ~20KB (~1500 tickers) with a 400.
CHUNK = 800
start_time = time.time()
frames = []
for i in range(0, len(symbols), CHUNK):
    response = requests.get(
        "http://174.138.72.10:8000/v1/daily-prices",
        params={
            "symbols": symbols[i : i + CHUNK],
            "start": date(2026, 1, 1).isoformat(),
            "end": date(2026, 8, 1).isoformat(),
        },
    )
    response.raise_for_status()
    frames.append(pd.DataFrame(response.json()["data"]))

end_time = time.time()
print(f"Time taken: {end_time - start_time} seconds")

df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
print(df.head())
print(df.tail())
