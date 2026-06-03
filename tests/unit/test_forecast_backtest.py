"""Unit tests for ``ncs.forecast.backtest`` (developer-owned, white-box) — 002-T9 / R2, R3.

White-box checks of the held-out backtest machinery:

* the **MAPE** formula — averaged only over held-out months with a **positive** actual; zero and
  missing actuals are excluded (never division-by-zero), and ``|P|`` is reported alongside;
* the **scorable count** the ``MIN_SCORABLE`` guard reads (so a forecast scored on too few positive
  months can be forced low-confidence upstream);
* **selection** — the lowest-MAPE approach wins, ties break toward ``arps_decline``, and an all-fail
  series raises ``AllApproachesFailedError``;
* the **train/test split** holds out the final 24 observed offsets.

The selection tests monkeypatch the approach registry with deterministic stand-ins so the *selection
logic* is tested independently of scipy/statsmodels numerics (those are covered in
``test_forecast_methods``).
"""

from __future__ import annotations

import numpy as np
import pytest

from ncs.forecast import backtest as bt
from ncs.forecast.backtest import (
    HORIZON,
    AllApproachesFailedError,
    CandidateScore,
    mape,
    score_candidates,
    select,
)
from ncs.forecast.contracts import ForecastMethod
from ncs.forecast.series import MonthlySeries


def _series(n: int) -> MonthlySeries:
    """A simple positive series of length ``n`` (values irrelevant when approaches are patched)."""
    values = np.linspace(10.0, 1.0, n)
    return MonthlySeries(values=values, first_year=2014, first_month=1, last_year=2020, last_month=1)


# --- MAPE ------------------------------------------------------------------------------------------


def test_mape_is_zero_for_a_perfect_forecast() -> None:
    actual = np.array([4.0, 2.0, 1.0])
    value, count = mape(actual, actual.copy())
    assert value == pytest.approx(0.0)
    assert count == 3


def test_mape_averages_absolute_percentage_error_over_positive_actuals() -> None:
    actual = np.array([10.0, 20.0])
    forecast = np.array([11.0, 18.0])  # 10% and 10% error
    value, count = mape(actual, forecast)
    assert value == pytest.approx(0.10)
    assert count == 2


def test_mape_excludes_zero_actuals_from_the_denominator() -> None:
    """A held-out month whose actual is 0.0 is excluded (MAPE undefined at 0), not a div-by-zero."""
    actual = np.array([10.0, 0.0, 10.0])
    forecast = np.array([11.0, 5.0, 9.0])  # the 0.0 month would be infinite error if counted
    value, count = mape(actual, forecast)
    assert count == 2, "only the two positive-actual months are scorable"
    assert value == pytest.approx(0.10)


def test_mape_excludes_missing_actuals() -> None:
    """NaN actuals (absent oe) are excluded from the error average (R6)."""
    actual = np.array([10.0, np.nan, 10.0])
    forecast = np.array([9.0, 100.0, 11.0])
    value, count = mape(actual, forecast)
    assert count == 2
    assert value == pytest.approx(0.10)


def test_mape_with_no_positive_actuals_is_inf() -> None:
    """No positive scorable month ⇒ undefined ⇒ ``+inf`` (non-selectable candidate)."""
    actual = np.array([0.0, 0.0])
    value, count = mape(actual, np.array([1.0, 1.0]))
    assert count == 0
    assert np.isinf(value)


# --- selection (approaches patched for determinism) -----------------------------------------------


def _patch_approaches(monkeypatch, approaches) -> None:
    monkeypatch.setattr(bt, "_APPROACHES", tuple(approaches))


def _constant_method(value: float):
    """An approach stand-in that always forecasts the constant ``value`` for every horizon step."""

    def _fit(series: MonthlySeries, horizon: int) -> list[float]:
        return [value] * horizon

    return _fit


def test_select_picks_the_lower_mape_approach(monkeypatch) -> None:
    """Selection returns the approach whose held-out MAPE is lower (R2)."""
    series = _series(60)
    # Actual final-24 values are the series tail; an approach forecasting near them scores low.
    tail_mean = float(np.mean(series.values[-HORIZON:]))
    _patch_approaches(
        monkeypatch,
        [
            (ForecastMethod.arps_decline, _constant_method(tail_mean * 100)),  # wildly off → high MAPE
            (ForecastMethod.holt_damped, _constant_method(tail_mean)),  # near the actuals → low MAPE
        ],
    )

    selection = select(series)

    assert selection.method is ForecastMethod.holt_damped
    assert np.isfinite(selection.backtest_mape)


def test_select_breaks_ties_toward_arps(monkeypatch) -> None:
    """Two approaches with identical MAPE ⇒ ``arps_decline`` wins (deterministic tie rule, R2)."""
    series = _series(60)
    same = _constant_method(float(np.mean(series.values[-HORIZON:])))
    _patch_approaches(
        monkeypatch,
        [
            (ForecastMethod.arps_decline, same),
            (ForecastMethod.holt_damped, same),  # identical forecast ⇒ identical MAPE
        ],
    )

    selection = select(series)

    assert selection.method is ForecastMethod.arps_decline


def test_select_raises_when_all_approaches_fail(monkeypatch) -> None:
    """Every candidate non-selectable (``+inf``) ⇒ ``AllApproachesFailedError`` (plan edge case)."""
    from ncs.forecast.methods import FitError

    def _always_fail(series: MonthlySeries, horizon: int) -> list[float]:
        raise FitError("boom")

    _patch_approaches(
        monkeypatch,
        [
            (ForecastMethod.arps_decline, _always_fail),
            (ForecastMethod.holt_damped, _always_fail),
        ],
    )

    with pytest.raises(AllApproachesFailedError):
        select(_series(60))


def test_failed_candidate_scores_inf_and_other_is_selected(monkeypatch) -> None:
    """A ``FitError`` candidate scores ``+inf``; selection falls to the surviving approach."""
    from ncs.forecast.methods import FitError

    series = _series(60)

    def _fail(series: MonthlySeries, horizon: int) -> list[float]:
        raise FitError("nope")

    _patch_approaches(
        monkeypatch,
        [
            (ForecastMethod.arps_decline, _fail),
            (ForecastMethod.holt_damped, _constant_method(float(np.mean(series.values[-HORIZON:])))),
        ],
    )

    scores = score_candidates(series)
    by_method = {s.method: s for s in scores}
    assert np.isinf(by_method[ForecastMethod.arps_decline].mape)
    assert np.isfinite(by_method[ForecastMethod.holt_damped].mape)

    assert select(series).method is ForecastMethod.holt_damped


# --- split & scorable count -----------------------------------------------------------------------


def test_score_candidates_reports_scorable_month_count(monkeypatch) -> None:
    """The scorable-month count is the number of positive held-out actuals the MAPE used."""
    series = _series(60)  # all 60 values positive ⇒ the final 24 are all scorable
    _patch_approaches(
        monkeypatch,
        [(ForecastMethod.arps_decline, _constant_method(float(np.mean(series.values[-HORIZON:]))))],
    )

    (score,) = score_candidates(series)

    assert isinstance(score, CandidateScore)
    assert score.scorable_months == HORIZON  # all 24 held-out months are positive


def test_scorable_count_drops_when_held_out_actuals_are_zero(monkeypatch) -> None:
    """Zero actuals in the held-out window reduce the scorable count (the MIN_SCORABLE guard input)."""
    series = _series(60)
    # Zero out half of the held-out final-24 window → only 12 positive scorable months remain.
    series.values[-HORIZON:][:12] = 0.0
    _patch_approaches(
        monkeypatch,
        [(ForecastMethod.arps_decline, _constant_method(5.0))],
    )

    (score,) = score_candidates(series)

    assert score.scorable_months == 12, "only the 12 positive held-out months are scorable"
