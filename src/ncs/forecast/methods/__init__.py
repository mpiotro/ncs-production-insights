"""Forecasting approaches behind one internal ``fit_and_forecast`` contract (task 002-T8; R2).

Each approach fits a model to a gappy monthly oil-equivalents series and predicts ``horizon`` steps
ahead, returning non-negative values (clamped at the producer). A failed fit raises :class:`FitError`
so the backtest scores that candidate as non-selectable (``+inf`` MAPE) and selection falls to the
other approach (plan.md §Two approaches, §Backtest "failed candidate handling").

Two approaches compete (plan.md §Two approaches):

* :func:`ncs.forecast.methods.arps.fit_and_forecast` — Arps hyperbolic decline-curve (mechanistic).
* :func:`ncs.forecast.methods.stats.fit_and_forecast` — Holt damped-trend smoothing (empirical).
"""

from __future__ import annotations


class FitError(Exception):
    """An approach could not fit the given series (non-convergence / estimation failure) (R2).

    Raised by an approach's ``fit_and_forecast`` when no usable forecast can be produced — the
    backtest treats the candidate as non-selectable (``+inf`` MAPE) rather than feeding a bogus
    forecast into the error average (plan.md §Backtest).
    """
