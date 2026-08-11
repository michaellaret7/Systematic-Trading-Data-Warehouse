import argparse
import os
from datetime import date

import polars as pl
from arcticdb.version_store.library import Library

from src.storage.arctic import connect, read_daily_prices, write_daily_prices
