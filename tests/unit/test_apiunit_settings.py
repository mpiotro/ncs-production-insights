"""Unit tests for ``ncs.api.settings`` (developer-owned, white-box) — 003-T7 / R1.

White-box checks of the env-sourced ``ApiSettings``: the defaults (port 8003, host 127.0.0.1, the
gitignored DB path, the 004 dev CORS origin), each env override applied from an injected mapping (no
real ``os.environ`` mutation), blank values falling back to defaults, and the comma-split CORS list.
``from_env`` takes an injectable mapping precisely so these run hermetically.
"""

from __future__ import annotations

from ncs.api.settings import (
    DEFAULT_CORS_ORIGINS,
    DEFAULT_DB_PATH,
    DEFAULT_HOST,
    DEFAULT_PORT,
    ApiSettings,
)


def test_defaults_when_env_empty() -> None:
    """With no env vars set, the settings carry the pinned defaults (port 8003 etc.) (R1)."""
    settings = ApiSettings.from_env({})

    assert settings.db_path == DEFAULT_DB_PATH
    assert settings.host == DEFAULT_HOST
    assert settings.port == DEFAULT_PORT
    assert settings.port == 8003
    assert settings.cors_origins == list(DEFAULT_CORS_ORIGINS)


def test_env_overrides_are_applied() -> None:
    """Each env var overrides its field; the port is coerced to int (R1)."""
    settings = ApiSettings.from_env(
        {
            "NCS_DB_PATH": "/tmp/custom.duckdb",
            "API_HOST": "0.0.0.0",
            "API_PORT": "9100",
        }
    )

    assert settings.db_path == "/tmp/custom.duckdb"
    assert settings.host == "0.0.0.0"
    assert settings.port == 9100


def test_blank_env_values_fall_back_to_defaults() -> None:
    """Blank (empty-string) env values are ignored, keeping the defaults (R1)."""
    settings = ApiSettings.from_env({"NCS_DB_PATH": "", "API_PORT": ""})

    assert settings.db_path == DEFAULT_DB_PATH
    assert settings.port == DEFAULT_PORT


def test_cors_origins_split_on_commas() -> None:
    """``API_CORS_ORIGINS`` is split on commas into the allowed-origin list, blanks dropped (R1)."""
    settings = ApiSettings.from_env(
        {"API_CORS_ORIGINS": "http://a.test, http://b.test ,, http://c.test"}
    )

    assert settings.cors_origins == ["http://a.test", "http://b.test", "http://c.test"]


def test_cors_origins_all_blank_falls_back_to_default() -> None:
    """A CORS value of only commas/whitespace yields no origins, so the default stands (R1)."""
    settings = ApiSettings.from_env({"API_CORS_ORIGINS": " , , "})

    assert settings.cors_origins == list(DEFAULT_CORS_ORIGINS)


def test_settings_are_frozen() -> None:
    """``ApiSettings`` is immutable (frozen) — config is read once, not mutated at runtime."""
    import pytest
    from pydantic import ValidationError

    settings = ApiSettings.from_env({})
    with pytest.raises(ValidationError):
        settings.port = 1234  # type: ignore[misc]
