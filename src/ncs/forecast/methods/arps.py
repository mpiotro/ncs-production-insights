"""Approach A — Arps hyperbolic decline-curve fit (task 002-T8; R2, plan.md §Approach A).

The classical petroleum production-decline model. Rate vs time (months ``t`` from first production):

    q(t) = q_i / (1 + b · D_i · t) ** (1 / b),   0 < b ≤ 1, q_i > 0, D_i ≥ 0

Hyperbolic with ``b`` bounded to ``(0, 1]`` **subsumes** the other Arps forms — ``b → 0`` ⇒
exponential, ``b = 1`` ⇒ harmonic — so one bounded fit lands on whichever decline shape fits the
field; we do not hard-pick exponential vs harmonic per field.

Fit by ``scipy.optimize.curve_fit`` (non-linear least squares) on the series' **non-missing** monthly
oe points only (R6 — nulls/holes are excluded, never fed as 0). A non-converging fit raises
:class:`ncs.forecast.methods.FitError` so the candidate scores as non-selectable (plan.md §Backtest).
"""

from __future__ import annotations

import warnings

import numpy as np
from scipy.optimize import OptimizeWarning, curve_fit

from ncs.forecast.methods import FitError
from ncs.forecast.series import MonthlySeries

# A small positive floor so ``b`` stays strictly > 0 (the model is undefined at b = 0; the exponential
# limit is approached, not reached) and the fit can still land near-exponential.
_B_FLOOR: float = 1e-6


def _hyperbolic(t: np.ndarray, q_i: float, d_i: float, b: float) -> np.ndarray:
    """Arps hyperbolic rate ``q(t) = q_i / (1 + b·d_i·t) ** (1/b)`` (vectorised over ``t``)."""
    return q_i / np.power(1.0 + b * d_i * t, 1.0 / b)


def _seed_parameters(offsets: np.ndarray, values: np.ndarray) -> tuple[float, float, float]:
    """Initial ``(q_i, D_i, b)`` guess from early history (plan.md §Approach A).

    ``q_i`` from the earliest observed rate, ``D_i`` from the early decline slope (clamped ≥ 0 so a
    flat/rising early patch doesn't seed a negative decline), ``b = 0.5`` (mid-range hyperbolic).
    A good seed keeps ``curve_fit`` stable on short single-field series.
    """
    q_i = float(max(values[0], 1e-9))
    if len(values) >= 2 and values[0] > 0:
        # Approximate nominal decline from the first usable step: (q0 - q1) / q0 per month.
        step = float(offsets[1] - offsets[0]) or 1.0
        d_i = max((values[0] - values[1]) / (values[0] * step), 0.0)
    else:
        d_i = 0.03
    return q_i, d_i, 0.5


def fit_and_forecast(series: MonthlySeries, horizon: int) -> list[float]:
    """Fit the hyperbolic decline on ``series``'s observed points and forecast ``horizon`` months.

    The forecast covers the ``horizon`` month offsets immediately following the **end of the input
    series span** (``len(series.values) .. len(series.values)+horizon-1``) — i.e. the months after
    the series' last calendar month. Fit uses only the non-missing observations at their true offsets
    (R6). Returns non-negative oe values; raises :class:`FitError` if the fit cannot converge or has
    too few points.
    """
    offsets = series.observed_offsets.astype(float)
    values = series.observed_values.astype(float)

    # Need more points than free parameters (3) for a meaningful non-linear fit.
    if len(values) < 4:
        raise FitError("too few observed points to fit an Arps decline (need ≥ 4)")

    q_i0, d_i0, b0 = _seed_parameters(offsets, values)
    # Bounds: q_i ≥ 0, D_i ≥ 0 (physical decline), b ∈ (0, 1] (hyperbolic family).
    bounds = ([0.0, 0.0, _B_FLOOR], [np.inf, np.inf, 1.0])

    try:
        with warnings.catch_warnings():
            # A covariance warning is not a failure — only a raised exception is (handled below).
            warnings.simplefilter("ignore", OptimizeWarning)
            popt, _ = curve_fit(
                _hyperbolic,
                offsets,
                values,
                p0=[q_i0, d_i0, b0],
                bounds=bounds,
                maxfev=10000,
            )
    except (RuntimeError, ValueError, TypeError) as exc:
        # RuntimeError: least-squares did not converge; ValueError: bad inputs/NaN in the fit.
        raise FitError(f"Arps decline did not converge: {exc}") from exc

    span = len(series.values)
    future_offsets = np.arange(span, span + horizon, dtype=float)
    predicted = _hyperbolic(future_offsets, *popt)

    if not np.all(np.isfinite(predicted)):
        raise FitError("Arps decline produced non-finite forecast values")

    # Clamp to non-negative oe (a decline never predicts negative production).
    return [float(max(v, 0.0)) for v in predicted]
