"""Unit tests for ``ncs.forecast.persist`` (developer-owned, white-box) — 002-T11 / R8.

White-box checks of the DuckDB forecast persistence layer, against a real tmp DuckDB file so the
actual SQL runs:

* the parent columns equal the scalar ``FieldForecast`` fields and a persisted forecast **round-trips**
  back into the frozen model (the read 003 performs);
* the upsert is **idempotent** — re-persisting the same forecast adds no rows and updates in place;
* points are **replaced cleanly** — a re-forecast with renumbered points leaves no stragglers;
* the persist **commits** (durable across a reopen of the same file);
* the ``forecast_run`` audit row is appended with native ``BIGINT[]`` outcome columns;
* the grouped ``monthly_production`` read returns per-field ``(year, month, oe)`` ordered, preserving
  ``None`` oe (R6).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pytest

from ncs.contracts import MonthlyProduction
from ncs.forecast.contracts import (
    FieldForecast,
    ForecastMethod,
    ForecastPoint,
    ForecastRun,
    ForecastTarget,
)
from ncs.forecast.persist import (
    create_forecast_schema,
    persist_forecast,
    persist_forecast_run,
    persist_forecasts,
    read_production_by_field,
)
from ncs.persist import create_schema, persist_data


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    """A file-backed DuckDB connection (a real file so durability across a reopen is testable)."""
    connection = duckdb.connect(str(tmp_path / "forecast_unit.duckdb"))
    try:
        yield connection
    finally:
        connection.close()


def _forecast(npdid: int, *, start=(2020, 1), value: float = 1.0, **overrides) -> FieldForecast:
    points = []
    y, m = start
    for _ in range(24):
        points.append(ForecastPoint(year=y, month=m, value=value))
        m += 1
        if m > 12:
            m = 1
            y += 1
    base = dict(
        field_npdid=npdid,
        points=points,
        method=ForecastMethod.arps_decline,
        backtest_mape=0.05,
        credible=True,
        history_months=72,
    )
    base.update(overrides)
    return FieldForecast(**base)


def _load(con: duckdb.DuckDBPyConnection, npdid: int) -> FieldForecast:
    """Reconstruct a persisted ``FieldForecast`` from the store (the 003 round-trip)."""
    parent = con.execute(
        "SELECT target, method, backtest_mape, credible, history_months "
        "FROM field_forecast WHERE field_npdid = ?",
        [npdid],
    ).fetchone()
    target, method, mape, credible, history_months = parent
    point_rows = con.execute(
        "SELECT year, month, value FROM field_forecast_point WHERE field_npdid = ? ORDER BY year, month",
        [npdid],
    ).fetchall()
    return FieldForecast(
        field_npdid=npdid,
        target=target,
        points=[ForecastPoint(year=y, month=m, value=v) for (y, m, v) in point_rows],
        method=method,
        backtest_mape=mape,
        credible=credible,
        history_months=history_months,
    )


def test_persisted_forecast_round_trips(con: duckdb.DuckDBPyConnection) -> None:
    """A persisted forecast reconstructs into the identical frozen ``FieldForecast`` (R8)."""
    create_forecast_schema(con)
    fc = _forecast(100)

    persist_forecast(con, fc)

    assert _load(con, 100) == fc


def test_persist_is_idempotent_no_extra_rows(con: duckdb.DuckDBPyConnection) -> None:
    """Re-persisting the same forecast adds no rows (upsert by key) (R8)."""
    create_forecast_schema(con)
    fc = _forecast(101)

    persist_forecast(con, fc)
    persist_forecast(con, fc)

    (parent,) = con.execute("SELECT count(*) FROM field_forecast").fetchone()
    (points,) = con.execute("SELECT count(*) FROM field_forecast_point").fetchone()
    assert parent == 1
    assert points == 24


def test_upsert_updates_parent_in_place(con: duckdb.DuckDBPyConnection) -> None:
    """A second persist with changed scalars updates the existing parent row, not a duplicate (R8)."""
    create_forecast_schema(con)
    persist_forecast(con, _forecast(102, credible=True, backtest_mape=0.05))

    persist_forecast(con, _forecast(102, credible=False, backtest_mape=0.30))

    (count,) = con.execute(
        "SELECT count(*) FROM field_forecast WHERE field_npdid = 102"
    ).fetchone()
    assert count == 1
    reloaded = _load(con, 102)
    assert reloaded.credible is False
    assert reloaded.backtest_mape == 0.30


def test_points_are_replaced_cleanly_on_reforecast(con: duckdb.DuckDBPyConnection) -> None:
    """A re-forecast whose points fall on different months leaves no stale points (clean replace, R8).

    The delete-then-insert replace means the points table always reflects exactly the latest 24 — a
    re-forecast that shifts the calendar can't leave the previous run's points behind.
    """
    create_forecast_schema(con)
    persist_forecast(con, _forecast(103, start=(2020, 1)))  # 2020-01 .. 2021-12

    persist_forecast(con, _forecast(103, start=(2021, 1)))  # 2021-01 .. 2022-12 (different months)

    (count,) = con.execute(
        "SELECT count(*) FROM field_forecast_point WHERE field_npdid = 103"
    ).fetchone()
    assert count == 24, "stale points from the first forecast must be deleted (no accumulation)"
    months = con.execute(
        "SELECT min(year), max(year) FROM field_forecast_point WHERE field_npdid = 103"
    ).fetchone()
    assert months == (2021, 2022), "only the latest forecast's months remain"


def test_persist_commits_durable_across_reopen(tmp_path: Path) -> None:
    """The persist commits — a reopened connection on the same file sees the rows (R8)."""
    db = str(tmp_path / "durable.duckdb")
    con1 = duckdb.connect(db)
    create_forecast_schema(con1)
    persist_forecast(con1, _forecast(104))
    con1.close()

    con2 = duckdb.connect(db)
    try:
        (count,) = con2.execute(
            "SELECT count(*) FROM field_forecast WHERE field_npdid = 104"
        ).fetchone()
        assert count == 1
    finally:
        con2.close()


def test_persist_forecasts_writes_all(con: duckdb.DuckDBPyConnection) -> None:
    """``persist_forecasts`` writes every forecast in the sequence (R8)."""
    create_forecast_schema(con)

    persist_forecasts(con, [_forecast(105), _forecast(106)])

    npdids = {row[0] for row in con.execute("SELECT field_npdid FROM field_forecast").fetchall()}
    assert npdids == {105, 106}


def test_forecast_run_audit_row_is_appended(con: duckdb.DuckDBPyConnection) -> None:
    """The audit row records the forecast count and the outcome NPDID sets as native arrays (R5, R8)."""
    create_forecast_schema(con)
    run = ForecastRun(
        forecasts=[_forecast(107)],
        insufficient_history_npdids=[201, 202],
        unforecastable_npdids=[203],
    )

    persist_forecast_run(con, run, datetime.now(timezone.utc))

    row = con.execute(
        "SELECT forecast_count, insufficient_history_npdids, unforecastable_npdids FROM forecast_run"
    ).fetchone()
    forecast_count, insufficient, unforecastable = row
    assert forecast_count == 1
    assert list(insufficient) == [201, 202]
    assert list(unforecastable) == [203]


def test_read_production_groups_by_field_preserving_nulls(con: duckdb.DuckDBPyConnection) -> None:
    """The grouped read returns per-field ordered ``(year, month, oe)`` and preserves ``None`` (R6)."""
    create_schema(con)
    rows = [
        MonthlyProduction(field_npdid=300, field_name="A", year=2014, month=2, oil_equivalents=4.0),
        MonthlyProduction(field_npdid=300, field_name="A", year=2014, month=1, oil_equivalents=5.0),
        MonthlyProduction(field_npdid=300, field_name="A", year=2014, month=3, oil_equivalents=None),
        MonthlyProduction(field_npdid=301, field_name="B", year=2015, month=1, oil_equivalents=9.0),
    ]
    persist_data(con, rows, [])

    grouped = read_production_by_field(con)

    assert set(grouped) == {300, 301}
    # Ordered by (year, month); the None oe is preserved (not coerced to 0).
    assert grouped[300] == [(2014, 1, 5.0), (2014, 2, 4.0), (2014, 3, None)]
    assert grouped[301] == [(2015, 1, 9.0)]
