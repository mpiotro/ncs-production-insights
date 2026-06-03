"""Approach B — Holt damped-trend exponential smoothing (task 002-T8; R2, plan.md §Approach B).

A purely empirical forecaster that doesn't assume a decline law: it extrapolates **level + a damped
trend** from the recent series, capturing fields that don't follow clean Arps decline (plateaus,
re-developments, late-life noise).

Library: ``statsmodels.tsa.holtwinters.ExponentialSmoothing`` with ``trend="add"``,
``damped_trend=True``, no seasonal term (monthly oe decline is trend-dominated, not strongly
seasonal; seasonless avoids over-fitting the 24-point holdout). Smoothing parameters are estimated by
the library's MLE; the damped trend keeps the 24-month extrapolation from running away. Forecast =
``fit.forecast(horizon)``.

Holt has **no native missing-data handling**, so it needs a gap-filled, evenly-spaced monthly series.
The interior NaN gaps (R6: absent oe, never 0) are linearly interpolated from neighbouring
observations before fitting — so the absent months are reconstructed from real data, **never read as
zeros**, and the gap-filled series is identical whether a gap was expressed as a ``None`` row or an
absent calendar month (both produce the same NaN at the same offset upstream). A failed estimation
raises :class:`ncs.forecast.methods.FitError`.
"""

from __future__ import annotations

import warnings

import numpy as np
from statsmodels.tools.sm_exceptions import ConvergenceWarning
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from ncs.forecast.methods import FitError
from ncs.forecast.series import MonthlySeries


def _interpolate_gaps(values: np.ndarray) -> np.ndarray:
    """Fill interior NaN gaps by linear interpolation between observed points (R6: gaps ≠ 0).

    The endpoints of a ``MonthlySeries`` are always observed (the series spans first→last *observed*
    month), so only interior gaps exist; ``np.interp`` reconstructs them from the surrounding real
    observations — the absent months are inferred from data, never substituted with 0. Returns a
    fully-dense float array Holt can fit.
    """
    indices = np.arange(len(values), dtype=float)
    observed = ~np.isnan(values)
    if not np.any(observed):
        raise FitError("series has no observed points to interpolate")
    return np.interp(indices, indices[observed], values[observed])


def fit_and_forecast(series: MonthlySeries, horizon: int) -> list[float]:
    """Fit Holt damped-trend smoothing on the gap-filled series and forecast ``horizon`` months.

    The series is densified (interior gaps interpolated — R6, never zero-filled), fit with an additive
    damped trend, and extrapolated ``horizon`` steps past the series' last month. Returns non-negative
    oe values; raises :class:`FitError` on a degenerate series or an estimation failure.
    """
    dense = _interpolate_gaps(series.values)

    # Need enough points to estimate a level + damped trend; statsmodels itself wants ≥ ~10 for a
    # stable damped fit. The 60-month eligibility guarantees far more on the forward path; on the
    # backtest train window (≥ 36) it is comfortably satisfied.
    if len(dense) < 10:
        raise FitError("too few points to fit a damped-trend model (need ≥ 10)")

    try:
        with warnings.catch_warnings():
            # Convergence/optimization warnings are not failures; only a raised exception is.
            warnings.simplefilter("ignore", ConvergenceWarning)
            warnings.simplefilter("ignore", RuntimeWarning)
            model = ExponentialSmoothing(
                dense,
                trend="add",
                damped_trend=True,
                seasonal=None,
                initialization_method="estimated",
            )
            fit = model.fit()
            predicted = np.asarray(fit.forecast(horizon), dtype=float)
    except (ValueError, np.linalg.LinAlgError, RuntimeError, TypeError) as exc:
        raise FitError(f"Holt damped-trend estimation failed: {exc}") from exc

    if predicted.shape[0] != horizon or not np.all(np.isfinite(predicted)):
        raise FitError("Holt damped-trend produced an invalid forecast")

    # Clamp to non-negative oe (production is never negative).
    return [float(max(v, 0.0)) for v in predicted]
