"""Databento client factory: Historical for research, Live for real-time."""

from __future__ import annotations

from typing import Literal

import databento as db

from src.config import require


Mode = Literal["historical", "live"]


def client(mode: Mode) -> db.Historical | db.Live:
    """Build a Databento Historical or Live client from DATABENTO_API_KEY."""
    (api_key,) = require("DATABENTO_API_KEY")

    if mode == "historical":
        return db.Historical(api_key)

    if mode == "live":
        return db.Live(api_key)

    raise ValueError(f"mode must be 'historical' or 'live', got {mode!r}")

