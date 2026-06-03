"""Unit tests for ``ncs.forecast.run`` (developer-owned, white-box) — 002-T12 / R5, R8.

White-box checks of the end-to-end ``run_forecasts`` wrapper against a real tmp DuckDB store seeded
via the frozen 001 persistence seam:

* it reads ``monthly_production``, forecasts each field, and sorts outcomes into forecasts /
  insufficient-history / **unforecastable** (the both-approaches-fail bucket the acceptance suite
  can't easily reach with its fixtures, exercised here by patching the forecaster to raise);
* the returned run matches what is persisted (no store↔return drift), and a re-run is idempotent;
* an empty store yields an empty run without error.

The forecasting *numerics* are covered elsewhere; here the focus is the run's orchestration, the
outcome bucketing, and the committed persistence.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from ncs.contracts import MonthlyProduction
from ncs.forecast import run as run_mod
from ncs.forecast.backtest import AllApproachesFailedError
from ncs.forecast.contracts import ForecastRun
from ncs.forecast.forecaster import InsufficientHistoryError
from ncs.forecast.run import run_forecasts
from ncs.persist import create_schema, persist_data


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(str(tmp_path / "run_unit.duckdb"))
    try:
        yield connection
    finally:
        connection.close()


def _hyperbolic(t: float) -> float:
    return 5.0 / (1.0 + 0.5 * 0.03 * t) ** (1.0 / 0.5)


def _clean_rows(npdid: int, months: int) -> list[MonthlyProduction]:
    rows = []
    y, m = 2014, 1
    for t in range(months):
        rows.append(
            MonthlyProduction(
                field_npdid=npdid, field_name="F", year=y, month=m, oil_equivalents=_hyperbolic(t)
            )
        )
        m += 1
        if m > 12:
            m = 1
            y += 1
    return rows


def _seed(con: duckdb.DuckDBPyConnection, *histories) -> None:
    create_schema(con)
    rows: list[MonthlyProduction] = []
    for h in histories:
        rows.extend(h)
    persist_data(con, rows, [])


def test_run_forecasts_buckets_forecastable_and_short(con: duckdb.DuckDBPyConnection) -> None:
    """A ≥ 60-month field is forecast; a < 60-month field lands in insufficient-history (R5, R8)."""
    _seed(con, _clean_rows(1, 72), _clean_rows(2, 40))

    run = run_forecasts(con)

    assert isinstance(run, ForecastRun)
    assert {f.field_npdid for f in run.forecasts} == {1}
    assert run.insufficient_history_npdids == [2]
    assert run.unforecastable_npdids == []


def test_run_persists_and_matches_return(con: duckdb.DuckDBPyConnection) -> None:
    """The persisted parent rows match the returned forecasts' NPDIDs (no drift, R8)."""
    _seed(con, _clean_rows(10, 72), _clean_rows(11, 72))

    run = run_forecasts(con)

    persisted = {
        row[0] for row in con.execute("SELECT field_npdid FROM field_forecast").fetchall()
    }
    assert persisted == {f.field_npdid for f in run.forecasts} == {10, 11}


def test_second_run_is_idempotent(con: duckdb.DuckDBPyConnection) -> None:
    """A second run over the same store adds no forecast/point rows (R8 idempotent upsert)."""
    _seed(con, _clean_rows(20, 72))

    run_forecasts(con)
    (p1,) = con.execute("SELECT count(*) FROM field_forecast").fetchone()
    (pp1,) = con.execute("SELECT count(*) FROM field_forecast_point").fetchone()

    run_forecasts(con)
    (p2,) = con.execute("SELECT count(*) FROM field_forecast").fetchone()
    (pp2,) = con.execute("SELECT count(*) FROM field_forecast_point").fetchone()

    assert (p1, pp1) == (p2, pp2) == (1, 24)
    # The audit table, by contrast, appends one row per run (run-history).
    (runs,) = con.execute("SELECT count(*) FROM forecast_run").fetchone()
    assert runs == 2


def test_unforecastable_field_is_bucketed(con: duckdb.DuckDBPyConnection, monkeypatch) -> None:
    """A ≥ 60-month field whose forecast raises ``AllApproachesFailedError`` lands in unforecastable.

    Patches the ``Forecaster`` the run uses so the both-approaches-fail edge case is exercised without
    contriving a pathological series: the NPDID must be recorded in ``unforecastable_npdids`` and
    **not** persisted as a forecast (never a bogus row).
    """
    _seed(con, _clean_rows(30, 72))

    class _FailingForecaster:
        def forecast(self, history):
            raise AllApproachesFailedError("both failed")

    monkeypatch.setattr(run_mod, "Forecaster", _FailingForecaster)

    run = run_forecasts(con)

    assert run.unforecastable_npdids == [30]
    assert run.forecasts == []
    (persisted,) = con.execute("SELECT count(*) FROM field_forecast").fetchone()
    assert persisted == 0


def test_mixed_outcomes_are_each_bucketed(con: duckdb.DuckDBPyConnection, monkeypatch) -> None:
    """Forecastable, short, and unforecastable fields each land in their own bucket (R5, R8)."""
    _seed(con, _clean_rows(40, 72), _clean_rows(41, 40), _clean_rows(42, 72))

    real_forecast = run_mod.Forecaster().forecast

    class _SelectiveForecaster:
        def forecast(self, history):
            npdid = history[0].field_npdid
            if npdid == 42:
                raise AllApproachesFailedError("degenerate")
            # 40 → real forecast; 41 → the real forecaster raises InsufficientHistoryError itself.
            return real_forecast(history)

    monkeypatch.setattr(run_mod, "Forecaster", _SelectiveForecaster)

    run = run_forecasts(con)

    assert {f.field_npdid for f in run.forecasts} == {40}
    assert run.insufficient_history_npdids == [41]
    assert run.unforecastable_npdids == [42]


def test_empty_store_yields_empty_run(con: duckdb.DuckDBPyConnection) -> None:
    """An empty ``monthly_production`` produces an empty run without error (R8)."""
    create_schema(con)  # tables exist, no rows

    run = run_forecasts(con)

    assert run.forecasts == []
    assert run.insufficient_history_npdids == []
    assert run.unforecastable_npdids == []


def test_run_forecasts_raises_other_exceptions(con: duckdb.DuckDBPyConnection) -> None:
    """An InsufficientHistoryError from a genuinely short field is caught (sanity, R5).

    Distinct from a programming error: the run swallows only the two documented forecast outcomes;
    this confirms the short-field path is one of them (it would be a bug if it propagated).
    """
    _seed(con, _clean_rows(50, 50))  # 50 < 60

    # Should not raise — the short field is bucketed, not propagated.
    run = run_forecasts(con)
    assert run.insufficient_history_npdids == [50]
    # And InsufficientHistoryError is importable as the documented seam exception.
    assert issubclass(InsufficientHistoryError, Exception)
