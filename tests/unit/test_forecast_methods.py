"""Unit tests for the two forecasting approaches (developer-owned, white-box) — 002-T8 / R2.

White-box checks of ``ncs.forecast.methods.arps`` (Arps hyperbolic decline) and
``ncs.forecast.methods.stats`` (Holt damped-trend), both behind the same ``fit_and_forecast(series,
horizon)`` contract:

* each fits a clean decline and forecasts the right number of **non-negative** values continuing the
  trend (no jump up, no collapse to zero);
* a failed/degenerate fit raises :class:`FitError` (so the backtest scores it non-selectable);
* the missing-data discipline (R6): a series carrying interior NaN gaps fits without those gaps being
  read as zeros — Arps fits the observed points only, Holt interpolates the gaps from real data.
"""

from __future__ import annotations

import numpy as np
import pytest

from ncs.forecast.methods import FitError, arps, stats
from ncs.forecast.series import MonthlySeries


def _hyperbolic(t: float, q_i: float = 5.0, d_i: float = 0.03, b: float = 0.5) -> float:
    return q_i / (1.0 + b * d_i * t) ** (1.0 / b)


def _decline_series(n: int = 48, *, gaps: tuple[int, ...] = ()) -> MonthlySeries:
    """A clean hyperbolic decline of ``n`` months, with optional interior NaN gaps at ``gaps``."""
    values = np.array([_hyperbolic(t) for t in range(n)], dtype=float)
    for g in gaps:
        values[g] = np.nan
    return MonthlySeries(values=values, first_year=2014, first_month=1, last_year=2017, last_month=12)


@pytest.mark.parametrize("module", [arps, stats], ids=["arps", "holt"])
def test_fit_and_forecast_returns_horizon_non_negative_values(module) -> None:
    """Both approaches return exactly ``horizon`` non-negative forecast values for a clean decline."""
    series = _decline_series(48)

    forecast = module.fit_and_forecast(series, 24)

    assert len(forecast) == 24
    assert all(v >= 0 for v in forecast)


def test_arps_fits_a_clean_decline_close_to_the_truth() -> None:
    """Arps recovers the hyperbolic decline: its forecast continues the curve, not a flat/up line."""
    n = 48
    series = _decline_series(n)

    forecast = arps.fit_and_forecast(series, 24)

    # Compare to the true hyperbolic continuation at offsets n..n+23 (tight — the data is noiseless).
    truth = [_hyperbolic(t) for t in range(n, n + 24)]
    assert np.allclose(forecast, truth, rtol=0.05), "Arps must recover a clean hyperbolic decline"
    # And the decline keeps decreasing (monotone tail), never jumping above the last observed value.
    assert forecast[0] < series.observed_values[-1]


def test_holt_extrapolates_a_decline_downward_not_to_zero() -> None:
    """Holt damped-trend continues a clean decline downward without collapsing to zero."""
    series = _decline_series(48)

    forecast = stats.fit_and_forecast(series, 24)

    last_observed = float(series.observed_values[-1])
    assert forecast[0] <= last_observed + 1e-6, "the trend should not jump up from the last point"
    assert max(forecast) > 0.1, "a clean decline must not collapse to ~0"


@pytest.mark.parametrize("module", [arps, stats], ids=["arps", "holt"])
def test_gappy_series_fits_without_reading_gaps_as_zero(module) -> None:
    """Interior NaN gaps don't drag the fit toward zero — gappy ≈ ungapped forecast (R6)."""
    full = _decline_series(48)
    gappy = _decline_series(48, gaps=(20, 33))  # same series, two interior months missing

    forecast_full = module.fit_and_forecast(full, 24)
    forecast_gappy = module.fit_and_forecast(gappy, 24)

    # The two forecasts must be close: if the gaps had been read as 0.0 the gappy fit would be pulled
    # sharply down, breaking this. A loose tolerance keeps it about "not poisoned", not exact equality.
    assert np.allclose(forecast_full, forecast_gappy, rtol=0.15)


def test_arps_too_few_points_raises_fit_error() -> None:
    """Fewer observed points than free parameters ⇒ Arps raises ``FitError`` (non-selectable)."""
    series = _decline_series(3)  # 3 points < 4

    with pytest.raises(FitError):
        arps.fit_and_forecast(series, 24)


def test_holt_too_few_points_raises_fit_error() -> None:
    """Too short a series for a damped-trend estimate ⇒ Holt raises ``FitError``."""
    series = _decline_series(6)  # < 10

    with pytest.raises(FitError):
        stats.fit_and_forecast(series, 24)


def test_arps_constant_series_does_not_crash() -> None:
    """A flat (constant) series is degenerate for a decline fit but must not crash the process.

    Arps either fits a near-zero decline or raises ``FitError`` — both are acceptable (the backtest
    handles a ``FitError`` as non-selectable). The contract is "no uncaught exception other than
    ``FitError``".
    """
    series = MonthlySeries(
        values=np.full(40, 4.0), first_year=2014, first_month=1, last_year=2017, last_month=4
    )
    try:
        forecast = arps.fit_and_forecast(series, 24)
    except FitError:
        return
    assert len(forecast) == 24
    assert all(v >= 0 for v in forecast)


def test_holt_all_nan_series_raises_fit_error() -> None:
    """A series with no observed points can't be interpolated ⇒ Holt raises ``FitError``."""
    series = MonthlySeries(
        values=np.full(40, np.nan), first_year=2014, first_month=1, last_year=2017, last_month=4
    )

    with pytest.raises(FitError):
        stats.fit_and_forecast(series, 24)
