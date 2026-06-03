"""DuckDB persistence for forecasts — ``field_forecast`` (+ points) + upsert (task 002-T11; R8).

002 **persists** each ``FieldForecast`` to the single DuckDB store, queryable by ``field_npdid`` (R8;
plan.md §Persistence), so 003 serves a precomputed forecast from the store rather than recomputing the
backtest live. The 24 forecast points are denormalised to a child table keyed by field-month.

Schema (plan.md §Persistence — column names are load-bearing; the acceptance round-trip queries them):

- ``field_forecast``        — one scalar row per field; PK ``field_npdid``.
- ``field_forecast_point``  — the 24 forward points; PK ``(field_npdid, year, month)``.
- ``forecast_run``          — one audit row appended per run (``run_at`` PK), recording the forecast
  count and the insufficient-history / unforecastable NPDID sets (plan.md §Persistence; T12 scope).

Idempotency (R8, mirroring 001-R11): a field's forecast is upserted in **one committed transaction** —
the parent row via ``INSERT … ON CONFLICT (field_npdid) DO UPDATE``, and the child points by deleting
the field's existing points then inserting the new 24 (a clean replace, so a re-forecast that returned
renumbered points can't leave stragglers). Re-running over the same store updates in place — neither
table gains rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import duckdb

from ncs.forecast.contracts import FieldForecast, ForecastRun

_CREATE_FIELD_FORECAST = """
CREATE TABLE IF NOT EXISTS field_forecast (
    field_npdid     BIGINT  PRIMARY KEY,
    target          VARCHAR NOT NULL,
    method          VARCHAR NOT NULL,
    backtest_mape   DOUBLE  NOT NULL,
    credible        BOOLEAN NOT NULL,
    history_months  INTEGER NOT NULL
)
"""

_CREATE_FIELD_FORECAST_POINT = """
CREATE TABLE IF NOT EXISTS field_forecast_point (
    field_npdid     BIGINT  NOT NULL,
    year            INTEGER NOT NULL,
    month           INTEGER NOT NULL,
    value           DOUBLE  NOT NULL,
    PRIMARY KEY (field_npdid, year, month)
)
"""

_CREATE_FORECAST_RUN = """
CREATE TABLE IF NOT EXISTS forecast_run (
    run_at                      TIMESTAMPTZ PRIMARY KEY,
    forecast_count              BIGINT   NOT NULL,
    insufficient_history_npdids BIGINT[] NOT NULL,
    unforecastable_npdids       BIGINT[] NOT NULL
)
"""

_UPSERT_FIELD_FORECAST = """
INSERT INTO field_forecast (
    field_npdid, target, method, backtest_mape, credible, history_months
) VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT (field_npdid) DO UPDATE SET
    target = excluded.target,
    method = excluded.method,
    backtest_mape = excluded.backtest_mape,
    credible = excluded.credible,
    history_months = excluded.history_months
"""

_DELETE_POINTS = "DELETE FROM field_forecast_point WHERE field_npdid = ?"

_INSERT_POINT = """
INSERT INTO field_forecast_point (field_npdid, year, month, value)
VALUES (?, ?, ?, ?)
"""

_INSERT_FORECAST_RUN = """
INSERT INTO forecast_run (
    run_at, forecast_count, insufficient_history_npdids, unforecastable_npdids
) VALUES (?, ?, ?, ?)
"""


def create_forecast_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the forecast tables if they do not already exist (idempotent DDL — DDL only)."""
    con.execute(_CREATE_FIELD_FORECAST)
    con.execute(_CREATE_FIELD_FORECAST_POINT)
    con.execute(_CREATE_FORECAST_RUN)


def persist_forecast(con: duckdb.DuckDBPyConnection, forecast: FieldForecast) -> None:
    """Upsert one ``FieldForecast`` (parent row + its 24 points) in one committed transaction (R8).

    The parent row upserts on ``field_npdid``; the points are replaced cleanly (delete-then-insert)
    so a re-forecast updates in place without duplicating or stranding points. Committed so a
    follow-up query on the same connection sees the rows. Assumes the schema exists
    (:func:`create_forecast_schema`).
    """
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(
            _UPSERT_FIELD_FORECAST,
            [
                forecast.field_npdid,
                forecast.target.value,
                forecast.method.value,
                forecast.backtest_mape,
                forecast.credible,
                forecast.history_months,
            ],
        )
        con.execute(_DELETE_POINTS, [forecast.field_npdid])
        con.executemany(
            _INSERT_POINT,
            [
                [forecast.field_npdid, point.year, point.month, point.value]
                for point in forecast.points
            ],
        )
    except Exception:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


def persist_forecasts(
    con: duckdb.DuckDBPyConnection, forecasts: Sequence[FieldForecast]
) -> None:
    """Persist every forecast in the run (each in its own committed transaction) (R8)."""
    for forecast in forecasts:
        persist_forecast(con, forecast)


def persist_forecast_run(
    con: duckdb.DuckDBPyConnection, run: ForecastRun, run_at: datetime
) -> None:
    """Append one ``forecast_run`` audit row recording the run's outcome sets (R5, R8).

    Appended (not upserted) — run-history keyed by ``run_at`` (the 002 analogue of 001's
    ``ingestion_report``). The insufficient-history and unforecastable NPDID sets land in native
    DuckDB ``BIGINT[]`` columns (they read back as Python lists), so the R5 outcome is auditable from
    the store. Committed so a reopened connection sees it.
    """
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(
            _INSERT_FORECAST_RUN,
            [
                run_at,
                len(run.forecasts),
                list(run.insufficient_history_npdids),
                list(run.unforecastable_npdids),
            ],
        )
    except Exception:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


def read_production_by_field(
    con: duckdb.DuckDBPyConnection,
) -> dict[int, list[tuple[int, int, float | None]]]:
    """Read ``monthly_production`` grouped by ``field_npdid`` for forecasting (R8; §Input source).

    Returns ``{field_npdid: [(year, month, oil_equivalents), …]}`` ordered by ``(year, month)`` — the
    straight 001 table read, no schema change. ``run.py`` reconstructs ``MonthlyProduction`` rows from
    these tuples and hands per-field sequences to ``Forecaster.forecast`` (the seam that takes
    ``Sequence[MonthlyProduction]`` so it is unit-testable in isolation from DuckDB).
    """
    rows = con.execute(
        """
        SELECT field_npdid, year, month, oil_equivalents
        FROM monthly_production
        ORDER BY field_npdid, year, month
        """
    ).fetchall()

    grouped: dict[int, list[tuple[int, int, float | None]]] = {}
    for field_npdid, year, month, oil_equivalents in rows:
        grouped.setdefault(field_npdid, []).append((year, month, oil_equivalents))
    return grouped
