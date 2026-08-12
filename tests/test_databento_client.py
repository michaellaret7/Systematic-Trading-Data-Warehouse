from unittest.mock import MagicMock, patch

import pytest

from src.vendors.databento.client import client


def test_client_builds_historical(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABENTO_API_KEY", "test-key")
    historical = MagicMock()

    with patch("src.vendors.databento.client.db.Historical", return_value=historical) as ctor:
        result = client("historical")

    ctor.assert_called_once_with("test-key")
    assert result is historical


def test_client_builds_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABENTO_API_KEY", "test-key")
    live = MagicMock()

    with patch("src.vendors.databento.client.db.Live", return_value=live) as ctor:
        result = client("live")

    ctor.assert_called_once_with("test-key")
    assert result is live


def test_client_rejects_unknown_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABENTO_API_KEY", "test-key")

    with pytest.raises(ValueError, match="historical"):
        client("replay")  # type: ignore[arg-type]
