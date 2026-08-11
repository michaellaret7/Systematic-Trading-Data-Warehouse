from datetime import date
from io import BytesIO

import pandas as pd
import requests

BENCHMARK = "SPY"
WINDOW = 60

symbols = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "BRK-B", "JPM", "V",
    "UNH", "XOM", "JNJ", "WMT", "MA", "PG", "HD", "CVX", "MRK", "ABBV",
    "KO", "PEP", "COST", "AVGO", "LLY", "BAC", "TMO", "CSCO", "MCD", "ACN",
    "ABT", "DHR", "WFC", "CRM", "LIN", "ADBE", "DIS", "TXN", "NFLX", "NKE",
    "PM", "VZ", "CMCSA", "INTC", "AMD", "QCOM", "INTU", "AMAT", "IBM", "ORCL",
]

response = requests.get(
    "http://0.0.0.0:8000/v1/daily-prices",
    params={
        "symbols": [*symbols, BENCHMARK],
        # Extra history so the first 60 trading days aren't all NaN.
        "start": date(2024, 10, 1).isoformat(),
        "end": date(2026, 8, 1).isoformat(),
    },
)
response.raise_for_status()

df = pd.DataFrame(response.json()["data"])

df["date"] = pd.to_datetime(df["date"])
df = df.sort_values(["symbol", "date"])


def add_metrics(group: pd.DataFrame) -> pd.DataFrame:
    out = group.copy()
    out["returns"] = out["adj_close"].pct_change()
    out["cumulative_returns"] = (1 + out["returns"].fillna(0)).cumprod() - 1
    return out


df = df.groupby("symbol", group_keys=False).apply(add_metrics)

mkt = (
    df.loc[df["symbol"] == BENCHMARK, ["date", "returns"]]
    .rename(columns={"returns": "mkt_ret"})
)
df = df.merge(mkt, on="date", how="left")


def add_alpha_beta(group: pd.DataFrame) -> pd.DataFrame:
    out = group.copy()
    beta = out["returns"].rolling(WINDOW).cov(out["mkt_ret"]) / out["mkt_ret"].rolling(
        WINDOW
    ).var()
    alpha = (
        out["returns"].rolling(WINDOW).mean()
        - beta * out["mkt_ret"].rolling(WINDOW).mean()
    )
    out["beta_60"] = beta
    out["alpha_60"] = alpha
    return out


df = (
    df.groupby("symbol", group_keys=False)
    .apply(add_alpha_beta)
    .drop(columns=["mkt_ret"])
)

print(df.loc[df["symbol"] == "AAPL", [
    "date", "symbol", "adj_close", "returns", "cumulative_returns", "beta_60", "alpha_60"
]].tail(10))
