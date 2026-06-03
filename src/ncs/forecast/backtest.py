"""Held-out backtest, MAPE, the scorable-months guard, and approach selection (task 002-T9; R2, R3).

This is where principle 6 lives — **every** credibility claim is a held-out backtest (plan.md
§Backtest):

* **Split (R3).** Hold out the field's **final 24 observed-month points**; everything earlier is the
  train window. With ≥ 60 observed months, train ≥ 36 and test = 24 — the 60-month eligibility and the
  24-month holdout are the same arithmetic.
* **Fit & score (R2, R3).** Each candidate approach is fit on **train only**, forecasts 24 steps, and
  is scored by MAPE against the held-out actual oe. The forward forecast shipped in ``FieldForecast``
  is a *separate* refit on the full history (done in ``forecaster.py``); the backtest measures error.
* **MAPE (R3).** Mean absolute percentage error over held-out months with a **positive** actual oe.
  Months whose actual is ``0.0`` or missing are excluded (MAPE is undefined at 0) — never forced into
  the denominator (plan.md resolves the spec's "MAPE on zero / near-zero actuals" open question).
* **Scorable guard.** If fewer than ``MIN_SCORABLE`` (= 12) of the 24 held-out months have a positive
  actual, the field is **not credibly backtestable** → forced low-confidence regardless of the numeric
  MAPE (the metric is still recorded for transparency).
* **Failed candidate.** An approach that raises :class:`FitError` (or scores no positive months)
  yields ``+inf`` MAPE, so selection falls to the other approach.
* **Selection (R2).** The lowest-MAPE approach wins; ties break toward ``arps_decline`` (mechanistic,
  more interpretable) — a deterministic, documented rule.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from ncs.forecast.contracts import ForecastMethod
from ncs.forecast.methods import FitError, arps, stats
from ncs.forecast.series import MonthlySeries

# Spec-fixed constants (plan.md §History/horizon, §Backtest). Named here so the magic numbers live in
# one place; they are not runtime config.
HORIZON: int = 24  # held-out window length AND forward horizon (months)
MIN_SCORABLE: int = 12  # ≥ this many positive held-out actuals to be *credibly* backtestable

# The candidate approaches, in selection-tie order (arps first ⇒ ties break toward arps_decline).
FitAndForecast = Callable[[MonthlySeries, int], list[float]]
_APPROACHES: tuple[tuple[ForecastMethod, FitAndForecast], ...] = (
    (ForecastMethod.arps_decline, arps.fit_and_forecast),
    (ForecastMethod.holt_damped, stats.fit_and_forecast),
)


@dataclass(frozen=True)
class CandidateScore:
    """One approach's held-out backtest result (internal)."""

    method: ForecastMethod
    mape: float  # fraction (0.12 ⇒ 12%); np.inf if the approach failed to fit / score
    scorable_months: int  # positive held-out actuals the MAPE averaged over


@dataclass(frozen=True)
class Selection:
    """The selected approach and the inputs the credibility classification needs (internal)."""

    method: ForecastMethod
    backtest_mape: float  # the selected approach's held-out MAPE (fraction)
    scorable_months: int  # positive held-out actuals the selected MAPE used


def _train_series(series: MonthlySeries) -> tuple[MonthlySeries, np.ndarray]:
    """Split ``series`` into the train sub-series and the held-out test offsets (R3).

    The test window is the **last ``HORIZON`` observed offsets**; the train sub-series spans offset 0
    up to (but excluding) the first test offset. Returns the train ``MonthlySeries`` and the absolute
    offsets (in the original series) of the held-out observations.
    """
    observed = series.observed_offsets
    test_offsets = observed[-HORIZON:]
    first_test_offset = int(test_offsets[0])

    train_values = series.values[:first_test_offset]
    last_train_offset = int(series.observed_offsets[series.observed_offsets < first_test_offset][-1])
    last_year, last_month = _offset_to_month(series, last_train_offset)

    train = MonthlySeries(
        values=train_values,
        first_year=series.first_year,
        first_month=series.first_month,
        last_year=last_year,
        last_month=last_month,
    )
    return train, test_offsets


def _offset_to_month(series: MonthlySeries, offset: int) -> tuple[int, int]:
    """The ``(year, month)`` at month ``offset`` from the series' first observed month."""
    absolute = series.first_year * 12 + (series.first_month - 1) + offset
    return absolute // 12, (absolute % 12) + 1


def mape(actual: np.ndarray, forecast: np.ndarray) -> tuple[float, int]:
    """MAPE over months with a **positive, non-missing** actual oe (R3); returns ``(mape, |P|)``.

    ``P = { i : actual_i is not NaN and actual_i > 0 }``. MAPE is the mean of
    ``|actual_i − forecast_i| / actual_i`` over ``P`` — a fraction. If ``P`` is empty the error is
    undefined, returned as ``(np.inf, 0)`` so the candidate is non-selectable (plan.md §Backtest).
    """
    actual = np.asarray(actual, dtype=float)
    forecast = np.asarray(forecast, dtype=float)
    positive = (~np.isnan(actual)) & (actual > 0)
    count = int(np.count_nonzero(positive))
    if count == 0:
        return np.inf, 0
    errors = np.abs(actual[positive] - forecast[positive]) / actual[positive]
    return float(np.mean(errors)), count


def _score_candidate(
    method: ForecastMethod,
    fit_and_forecast: FitAndForecast,
    train: MonthlySeries,
    series: MonthlySeries,
    test_offsets: np.ndarray,
) -> CandidateScore:
    """Fit one approach on train, forecast the held-out window, and score its MAPE (R2, R3).

    A :class:`FitError` ⇒ the candidate is non-selectable (``+inf`` MAPE, 0 scorable). Otherwise the
    forecast at each held-out offset is aligned to the actual and scored over the positive actuals.
    """
    train_span = len(train.values)
    try:
        forecast = fit_and_forecast(train, HORIZON)
    except FitError:
        return CandidateScore(method=method, mape=np.inf, scorable_months=0)

    forecast_arr = np.asarray(forecast, dtype=float)
    # Align each held-out actual to its forecast step (offset measured from the train series end).
    actual = series.values[test_offsets]
    steps = test_offsets - train_span
    # All steps fall inside [0, HORIZON) for a contiguous final-24 holdout (the only case the gates
    # allow); guard defensively so a degenerate alignment can't index out of range.
    if np.any(steps < 0) or np.any(steps >= HORIZON):
        return CandidateScore(method=method, mape=np.inf, scorable_months=0)

    aligned_forecast = forecast_arr[steps]
    value, scorable = mape(actual, aligned_forecast)
    return CandidateScore(method=method, mape=value, scorable_months=scorable)


def score_candidates(series: MonthlySeries) -> list[CandidateScore]:
    """Backtest every candidate approach on ``series`` and return their scores (R2, R3).

    Each approach is fit on the train split and scored on the held-out final 24 observed months.
    Exposed (not just used by :func:`select`) so the developer's unit tests can inspect per-approach
    behaviour directly.
    """
    train, test_offsets = _train_series(series)
    return [
        _score_candidate(method, fn, train, series, test_offsets)
        for method, fn in _APPROACHES
    ]


def select(series: MonthlySeries) -> Selection:
    """Backtest the approaches and select the lowest-MAPE one (R2); ties → ``arps_decline``.

    ``_APPROACHES`` is ordered with ``arps_decline`` first, and Python's ``min`` keeps the **first**
    minimum on ties — so an exact tie deterministically selects ``arps_decline`` (the mechanistic,
    more interpretable model), exactly as plan.md fixes. Raises :class:`AllApproachesFailedError` if
    *every* candidate failed to produce a usable backtest (both ``+inf``).
    """
    scores = score_candidates(series)
    best = min(scores, key=lambda s: s.mape)
    if not np.isfinite(best.mape):
        raise AllApproachesFailedError(
            "no candidate approach produced a usable backtest forecast for this field"
        )
    return Selection(
        method=best.method,
        backtest_mape=best.mape,
        scorable_months=best.scorable_months,
    )


class AllApproachesFailedError(Exception):
    """Neither Arps nor Holt produced a usable backtest for a ≥ 60-month field (plan.md edge case).

    A degenerate series both approaches fail to fit yields no ``FieldForecast``; ``run_forecasts``
    records the NPDID in ``ForecastRun.unforecastable_npdids`` rather than emitting a bogus forecast.
    """
