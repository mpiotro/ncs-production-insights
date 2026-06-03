"""Unit tests for the defensive edge branches of the forecast pipeline (developer-owned) — 002.

These pin the deliberately-defensive paths the main suites don't naturally reach, so each is a tested
behaviour rather than dead code: the contract's explicit wrong-target rejection (R7), the backtest's
out-of-range alignment guard, both approaches' library-exception → :class:`FitError` translation (R2),
and the persistence rollback on a mid-transaction failure (R8). Small, surgical, and behaviour-pinning.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from ncs.forecast import backtest as bt
from ncs.forecast.backtest import HORIZON, mape, score_candidates
from ncs.forecast.contracts import (
    FieldForecast,
    ForecastMethod,
    ForecastPoint,
    ForecastTarget,
)
from ncs.forecast.methods import FitError, arps, stats
from ncs.forecast.series import MonthlySeries


# --- contract: explicit wrong-target rejection (R7) -----------------------------------------------


def test_explicit_wrong_target_is_rejected() -> None:
    """The validator rejects a wrong ``target`` even though the field defaults to oil-equivalents.

    There is only one ``ForecastTarget`` member this cycle, so to reach the wrong-target branch we
    pass an out-of-vocabulary string — it fails enum coercion *or* the invariant; either way the
    explicit wrong target is rejected, never silently accepted.
    """
    points = [ForecastPoint(year=2020, month=(i % 12) + 1, value=1.0) for i in range(24)]
    with pytest.raises(ValidationError):
        FieldForecast(
            field_npdid=1,
            target="gas",  # not the fixed oil-equivalents target
            points=points,
            method=ForecastMethod.arps_decline,
            backtest_mape=0.05,
            credible=True,
            history_months=72,
        )


def test_target_enum_is_single_member() -> None:
    """Guard: the cycle's target vocabulary is exactly oil-equivalents (the invariant's premise)."""
    assert set(ForecastTarget) == {ForecastTarget.oil_equivalents}


# --- backtest: out-of-range alignment guard -------------------------------------------------------


def test_backtest_out_of_range_alignment_scores_inf(monkeypatch) -> None:
    """If a held-out offset doesn't map into ``[0, HORIZON)`` the candidate is scored non-selectable.

    Constructed by putting a gap **inside** the final-24-observed band so the held-out window spans
    more than 24 calendar months: the last 24 *observed* offsets then stretch from 47 to 71 (offset 60
    missing), and the largest alignment step (71 − 47 = 24) lands at/over ``HORIZON`` — the guard must
    score ``+inf`` rather than index past the forecast array.
    """
    values = np.linspace(10.0, 1.0, 72)  # offsets 0..71
    values[60] = np.nan  # a single interior hole inside the trailing window
    series = MonthlySeries(
        values=values, first_year=2014, first_month=1, last_year=2019, last_month=12
    )

    # A trivial approach so scoring depends only on the alignment guard, not on a real fit.
    monkeypatch.setattr(
        bt,
        "_APPROACHES",
        ((ForecastMethod.arps_decline, lambda s, h: [1.0] * h),),
    )

    (score,) = score_candidates(series)
    assert np.isinf(score.mape), "a non-contiguous holdout must score +inf via the range guard"


# --- approaches: library-exception → FitError (R2) ------------------------------------------------


def test_arps_non_finite_inputs_raise_fit_error() -> None:
    """Non-finite observed values make ``curve_fit`` raise ⇒ translated to ``FitError``."""
    values = np.array([5.0, 4.0, np.inf, 3.0, 2.0, 1.0], dtype=float)  # inf is observed (not NaN)
    series = MonthlySeries(
        values=values, first_year=2014, first_month=1, last_year=2014, last_month=6
    )

    with pytest.raises(FitError):
        arps.fit_and_forecast(series, 24)


def test_arps_seed_handles_flat_early_history() -> None:
    """The seed's ``else`` branch (flat/zero early point) is exercised without crashing.

    A series whose first observed value is 0.0 takes the seed fallback (``d_i`` default), then either
    fits or raises ``FitError`` — never an uncaught exception.
    """
    values = np.array([0.0, 4.0, 3.0, 2.5, 2.0, 1.8, 1.5, 1.3], dtype=float)
    series = MonthlySeries(
        values=values, first_year=2014, first_month=1, last_year=2014, last_month=8
    )
    try:
        forecast = arps.fit_and_forecast(series, 24)
    except FitError:
        return
    assert len(forecast) == 24


def test_holt_non_finite_inputs_raise_fit_error() -> None:
    """A degenerate dense series that breaks the estimator is translated to ``FitError``."""
    # A constant series with an inf observation: interpolation yields inf, estimation fails.
    values = np.full(20, 5.0)
    values[5] = np.inf
    series = MonthlySeries(
        values=values, first_year=2014, first_month=1, last_year=2015, last_month=8
    )

    with pytest.raises(FitError):
        stats.fit_and_forecast(series, 24)


# --- mape edge: empty input -----------------------------------------------------------------------


def test_mape_on_empty_arrays_is_inf() -> None:
    value, count = mape(np.array([]), np.array([]))
    assert count == 0
    assert np.isinf(value)


# --- persistence: rollback on a mid-transaction failure (R8) --------------------------------------


def test_persist_rolls_back_without_schema(tmp_path: Path) -> None:
    """Persisting before the schema exists raises (the table is missing) and rolls back cleanly (R8).

    Exercises the ``except → ROLLBACK → raise`` path: the insert fails because ``field_forecast`` does
    not exist, the transaction is rolled back, and the error propagates rather than leaving an open
    transaction. A subsequent statement on the connection still works (no dangling transaction).
    """
    import duckdb

    from ncs.forecast.persist import persist_forecast

    con = duckdb.connect(str(tmp_path / "rollback.duckdb"))
    try:
        points = [ForecastPoint(year=2020, month=(i % 12) + 1, value=1.0) for i in range(24)]
        forecast = FieldForecast(
            field_npdid=1,
            points=points,
            method=ForecastMethod.arps_decline,
            backtest_mape=0.05,
            credible=True,
            history_months=72,
        )
        with pytest.raises(duckdb.Error):
            persist_forecast(con, forecast)  # no create_forecast_schema first → table missing

        # The connection is usable afterward (the failed transaction was rolled back, not left open).
        (one,) = con.execute("SELECT 1").fetchone()
        assert one == 1
    finally:
        con.close()
