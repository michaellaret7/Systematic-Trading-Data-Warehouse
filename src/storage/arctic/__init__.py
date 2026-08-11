"""ArcticDB storage layer.

A dataset is declared once as a ``Dataset``; ``read`` / ``write`` / ``upsert``
serve every one of them. Filters are pushed into ArcticDB instead of being
applied after a full read, and ``upsert`` rewrites only the date range it
touches rather than the whole table.
"""

from src.storage.arctic.connection import LIBRARY_NAME, connect
from src.storage.arctic.dataset import Dataset
from src.storage.arctic.ops import read, upsert, write
from src.storage.arctic.registry import (
    BALANCE_SHEET_ANNUAL,
    BALANCE_SHEET_QUARTERLY,
    CASH_FLOW_ANNUAL,
    CASH_FLOW_QUARTERLY,
    DAILY_PRICES,
    INCOME_STATEMENT_ANNUAL,
    INCOME_STATEMENT_QUARTERLY,
    RATIOS_ANNUAL,
    RATIOS_QUARTERLY,
    TICKER_UNIVERSE,
)

__all__ = [
    "LIBRARY_NAME",
    "Dataset",
    "DAILY_PRICES",
    "TICKER_UNIVERSE",
    "INCOME_STATEMENT_ANNUAL",
    "INCOME_STATEMENT_QUARTERLY",
    "BALANCE_SHEET_ANNUAL",
    "BALANCE_SHEET_QUARTERLY",
    "CASH_FLOW_ANNUAL",
    "CASH_FLOW_QUARTERLY",
    "RATIOS_ANNUAL",
    "RATIOS_QUARTERLY",
    "connect",
    "read",
    "write",
    "upsert",
]
