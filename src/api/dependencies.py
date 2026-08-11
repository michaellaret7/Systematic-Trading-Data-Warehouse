"""Dependencies shared by the HTTP endpoints."""

from __future__ import annotations

from functools import lru_cache

from arcticdb.version_store.library import Library

from src.storage.arctic import connect


@lru_cache(maxsize=1)
def get_library() -> Library:
    """Reuse one ArcticDB library handle for the life of the API process."""
    return connect()
