"""Unit tests for ``ncs.api.seed`` (developer-owned, white-box) — 003-T9 / plan §Store population.

``build_store`` is the out-of-band seed: it runs the **frozen** ``ingest`` then ``run_forecasts``
against one writable connection, so the API later reads exactly what 001/002 persist. These tests
drive it **hermetically** through the local SODIR fixtures (the same files the 001 acceptance suite
uses — no network) and assert the tables actually populate and the typed runs come back. The store is
then read through ``ncs.api.store`` to prove the seed produced a store the API can serve.

The fixtures carry only short histories (< 60 months), so every field lands in
``insufficient_history_npdids`` and no ``field_forecast`` row is written — which is itself the genuine
R4 forecast-not-available seeding (a forecast read of a seeded field then raises
``ForecastNotAvailableError``). The forecast *tables* are still created (the schema exists), proving
``run_forecasts`` ran.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from ncs.api import store
from ncs.api.errors import ForecastNotAvailableError
from ncs.api.seed import _require_env, _settings_from_env, build_store
from ncs.config import Settings, Source
from ncs.contracts import IngestionReport, Transport
from ncs.forecast.contracts import ForecastRun

# The canonical local SODIR fixtures shared with the 001 acceptance suite (hermetic, no network).
_FIXTURES = Path(__file__).resolve().parents[1] / "acceptance" / "fixtures" / "sodir"
_PRODUCTION_PRIMARY = _FIXTURES / "production_primary.csv"
_FIELD_FALLBACK_CSV = _FIXTURES / "field_fallback.csv"

# Expected counts from the fixture manifest (README.md): 4 fields, 10 production rows.
_EXPECTED_FIELDS = 4
_EXPECTED_PRODUCTION_ROWS = 10


def _fixture_settings() -> Settings:
    """Ingestion ``Settings`` pointed at the local fixtures over the CSV transport (hermetic).

    Uses the CSV field fallback (a stable WKT source) so the seed reads fields without a live REST
    service — exactly the local-file ``Source.location`` 001 supports. No network is touched.
    """
    return Settings(
        production_sources=[Source(transport=Transport.csv, location=str(_PRODUCTION_PRIMARY))],
        field_sources=[Source(transport=Transport.csv, location=str(_FIELD_FALLBACK_CSV))],
    )


@pytest.fixture
def seeded_path(tmp_path: Path) -> Path:
    """Build a store via ``build_store`` over the fixtures; return its (closed) file path."""
    db_path = tmp_path / "seeded.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        build_store(con, _fixture_settings())
    finally:
        con.close()
    return db_path


def test_build_store_returns_typed_runs(tmp_path: Path) -> None:
    """``build_store`` returns the ``IngestionReport`` + ``ForecastRun`` typed summaries."""
    con = duckdb.connect(str(tmp_path / "store.duckdb"))
    try:
        report, run = build_store(con, _fixture_settings())
    finally:
        con.close()

    assert isinstance(report, IngestionReport)
    assert isinstance(run, ForecastRun)


def test_build_store_populates_field_and_production_tables(seeded_path: Path) -> None:
    """The seed lands the fields + monthly production (counts match the fixture manifest)."""
    con = duckdb.connect(str(seeded_path), read_only=True)
    try:
        (field_count,) = con.execute("SELECT count(*) FROM field").fetchone()
        (prod_count,) = con.execute("SELECT count(*) FROM monthly_production").fetchone()
    finally:
        con.close()

    assert field_count == _EXPECTED_FIELDS
    assert prod_count == _EXPECTED_PRODUCTION_ROWS


def test_build_store_creates_the_forecast_tables(seeded_path: Path) -> None:
    """``run_forecasts`` ran: the forecast tables exist (even though the short fixtures yield none)."""
    con = duckdb.connect(str(seeded_path), read_only=True)
    try:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
    finally:
        con.close()

    assert {"field_forecast", "field_forecast_point", "forecast_run"} <= tables


def test_seeded_store_is_readable_through_the_api_store(seeded_path: Path) -> None:
    """The seed produced a store the API reads: ``store.list_fields`` returns the seeded fields."""
    con = duckdb.connect(str(seeded_path), read_only=True)
    try:
        fields = store.list_fields(con)
    finally:
        con.close()

    assert len(fields) == _EXPECTED_FIELDS
    assert [f.field_npdid for f in fields] == sorted(f.field_npdid for f in fields)


def test_short_history_fields_have_no_forecast_row(seeded_path: Path) -> None:
    """Every fixture field is < 60 months, so a forecast read raises ForecastNotAvailable (R4 seed)."""
    con = duckdb.connect(str(seeded_path), read_only=True)
    try:
        first_npdid = store.list_fields(con)[0].field_npdid
        with pytest.raises(ForecastNotAvailableError):
            store.get_forecast(con, first_npdid)
    finally:
        con.close()


def test_require_env_returns_a_set_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_require_env`` returns the value when the variable is set (principle 7: config via env)."""
    monkeypatch.setenv("NCS_SEED_TEST_VAR", "hello")

    assert _require_env("NCS_SEED_TEST_VAR") == "hello"


def test_require_env_raises_systemexit_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_require_env`` raises a clear ``SystemExit`` when the variable is missing (no hard-coded URL)."""
    monkeypatch.delenv("NCS_SEED_TEST_VAR", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        _require_env("NCS_SEED_TEST_VAR")
    assert "NCS_SEED_TEST_VAR" in str(exc_info.value)


def test_settings_from_env_parses_the_ingest_settings_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_settings_from_env`` builds the ingestion ``Settings`` from the env JSON (env-sourced config)."""
    settings = _fixture_settings()
    monkeypatch.setenv("NCS_INGEST_SETTINGS_JSON", settings.model_dump_json())

    parsed = _settings_from_env()

    assert isinstance(parsed, Settings)
    assert parsed == settings


def test_settings_from_env_raises_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing ``NCS_INGEST_SETTINGS_JSON`` surfaces the ``SystemExit`` from ``_require_env``."""
    monkeypatch.delenv("NCS_INGEST_SETTINGS_JSON", raising=False)

    with pytest.raises(SystemExit):
        _settings_from_env()


def test_build_store_is_idempotent(tmp_path: Path) -> None:
    """Re-seeding the same store updates in place — counts are unchanged (001-R11 / 002-R8 via the runs)."""
    db_path = tmp_path / "store.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        build_store(con, _fixture_settings())
        build_store(con, _fixture_settings())  # second seed over the same store
        (field_count,) = con.execute("SELECT count(*) FROM field").fetchone()
        (prod_count,) = con.execute("SELECT count(*) FROM monthly_production").fetchone()
    finally:
        con.close()

    assert field_count == _EXPECTED_FIELDS
    assert prod_count == _EXPECTED_PRODUCTION_ROWS
