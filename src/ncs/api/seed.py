"""Build/seed entrypoint — populate the API's DuckDB store (task 003-T9; plan.md §Store population).

**The API only ever *reads*** the store (read-only connection, R1). Populating it is this **separate,
out-of-band** step — never an endpoint (the spec puts ingest / forecast-trigger out of scope).
``build_store`` calls the **frozen** 001/002 batch runs in order against one *writable* connection:

1. ``ncs.pipeline.ingest(con, settings)`` -> loads ``field`` + ``monthly_production`` (+ the
   ``ingestion_report`` audit row);
2. ``ncs.forecast.run.run_forecasts(con)`` -> loads ``field_forecast`` (+ points, + ``forecast_run``)
   for the ≥ 60-month fields.

The connection then closes; the API process later opens the same file **read-only**. Reusing the very
functions that persist guarantees 003 reads exactly what 001/002 write — no parallel, drift-prone
loader (plan.md §"Why reuse the frozen runs"). ``ingest``'s ``Settings`` come from the environment in
production (SODIR URLs), never hard-coded here (principle 7: configuration via environment, no secrets).

Run it as ``python -m ncs.api.seed`` (a deploy/demo step the coordinator or developer runs once and on
data refresh). It is intentionally **not** wired into ``create_app()`` — the running API neither
ingests nor forecasts (R1).
"""

from __future__ import annotations

import sys

import duckdb

from ncs.api.settings import ApiSettings
from ncs.config import Settings
from ncs.contracts import IngestionReport
from ncs.forecast.contracts import ForecastRun
from ncs.forecast.run import run_forecasts
from ncs.pipeline import ingest


def build_store(
    con: duckdb.DuckDBPyConnection, settings: Settings
) -> tuple[IngestionReport, ForecastRun]:
    """Populate one writable store via the frozen runs: ``ingest`` then ``run_forecasts`` (plan §Store population).

    Returns the two typed run summaries (the ``IngestionReport`` and the ``ForecastRun``) so a caller —
    or the ``__main__`` entrypoint — can log what landed. The connection must be **writable** (this is
    the seed, the one place that writes); the API later reopens the file read-only. Idempotent: both
    frozen runs upsert, so re-seeding the same store updates in place (001-R11 / 002-R8).
    """
    report = ingest(con, settings)
    run = run_forecasts(con)
    return report, run


def _settings_from_env() -> Settings:
    """Build the ingestion ``Settings`` from the environment.

    Production seeding reads the SODIR source URLs from configuration (no secrets in code, principle
    7). The concrete env wiring is a deploy concern; this entrypoint surfaces a clear error if the
    sources are not configured rather than guessing a hard-coded URL.
    """
    return Settings.model_validate_json(_require_env("NCS_INGEST_SETTINGS_JSON"))


def _require_env(name: str) -> str:
    import os

    value = os.environ.get(name)
    if not value:
        raise SystemExit(
            f"{name} is not set. The seed step needs the SODIR source configuration "
            "(provided via the environment, never hard-coded) — see plan.md §Store population."
        )
    return value


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI wrapper
    """``python -m ncs.api.seed`` entrypoint: open the configured store writable and build it.

    Opens ``ApiSettings.from_env().db_path`` **writable** (the seed writes), runs ``build_store`` with
    env-sourced ingestion settings, prints a one-line summary, and closes. Thin glue over
    ``build_store`` (which the unit tests cover directly with a hermetic, fixture-backed store).
    """
    api_settings = ApiSettings.from_env()
    settings = _settings_from_env()

    con = duckdb.connect(api_settings.db_path)
    try:
        report, run = build_store(con, settings)
    finally:
        con.close()

    print(
        f"Seeded {api_settings.db_path}: "
        f"{report.counts.fields} fields, {report.counts.production_records} production rows, "
        f"{len(run.forecasts)} forecasts "
        f"({len(run.insufficient_history_npdids)} insufficient-history)."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - module CLI entrypoint
    sys.exit(main())
