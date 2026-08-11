"""The single place credentials are read: `.env` in, values out, fail fast."""

from __future__ import annotations

import os

from dotenv import load_dotenv


load_dotenv()


def require(*names: str) -> list[str]:
    """Return the named environment variables, raising if any is unset."""
    values = [os.environ.get(name, "") for name in names]

    missing = [name for name, value in zip(names, values) if not value]
    if missing:
        raise RuntimeError(f"Set {', '.join(missing)} in .env")

    return values
