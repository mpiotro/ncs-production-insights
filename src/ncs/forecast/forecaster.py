"""The ``Forecaster`` seam — the one interface every forecast is produced through (task 002-T10).

A single field's monthly history goes in; a typed ``FieldForecast`` comes out (plan.md §Component
shape). Behind ``forecast`` the whole pipeline runs (R1, R2, R4, R5):

1. build the calendar-spaced oe series (``series.py``; gaps = missing, R6);
2. **eligibility** — ``history_months >= 60`` or raise :class:`InsufficientHistoryError` (R5); the
   absence of a ``FieldForecast`` *is* the R5 outcome (a < 60-month ``FieldForecast`` is
   unconstructable, ``history_months >= 60``);
3. **backtest → select** the lowest-MAPE approach over the held-out final 24 months (``backtest.py``;
   R2, R3);
4. **refit on the full history** with the selected approach and project the forward 24-month forecast
   (R1) — clamped to non-negative oe;
5. **classify** ``credible = (backtest_mape < 0.15) AND scorable`` (R4) — the scorable-months guard is
   applied *before* construction, so the frozen contract's one-directional invariant holds as written;
6. **assemble** the typed ``FieldForecast`` (R7).
"""

from __future__ import annotations

from collections.abc import Sequence

from ncs.contracts import MonthlyProduction
from ncs.forecast.backtest import (
    HORIZON,
    MIN_SCORABLE,
    AllApproachesFailedError,
    select,
)
from ncs.forecast.contracts import (
    CREDIBLE_MAPE_GATE,
    FieldForecast,
    ForecastMethod,
    ForecastPoint,
    ForecastTarget,
)
from ncs.forecast.methods import FitError, arps, stats
from ncs.forecast.series import MonthlySeries, build_series

# The 60-month eligibility gate (plan.md §History/eligibility). Spec-fixed module constant.
MIN_HISTORY_MONTHS: int = 60

# Map a selected method to its fit function for the forward refit (mirrors backtest's registry).
_FORWARD_FIT = {
    ForecastMethod.arps_decline: arps.fit_and_forecast,
    ForecastMethod.holt_damped: stats.fit_and_forecast,
}


class InsufficientHistoryError(Exception):
    """A field has fewer than 60 months of observed oe history — no forecast is produced (R5).

    Raised by :meth:`Forecaster.forecast` rather than returning a non-credible stand-in: the absence
    of a ``FieldForecast`` *is* the insufficient-history outcome at this seam. ``run_forecasts``
    catches it to populate ``ForecastRun.insufficient_history_npdids``.
    """


class Forecaster:
    """Produces a field's credible, backtested 24-month oil-equivalents forecast (R1, R2, R7).

    The ≥ 2-approach evaluation (Arps decline + Holt damped-trend), the held-out backtest, MAPE,
    selection, and the credibility classification all happen behind the single :meth:`forecast`
    method (R2, R3, R4).
    """

    def forecast(self, history: Sequence[MonthlyProduction]) -> FieldForecast:
        """Forecast one field's 24-month oil-equivalents production from its monthly history (R1–R7).

        Raises :class:`InsufficientHistoryError` if the field has < 60 observed oe months (R5), and
        :class:`ncs.forecast.backtest.AllApproachesFailedError` if neither approach can fit a ≥ 60-month
        field (plan.md edge case). Otherwise returns the typed, contract-valid ``FieldForecast``.
        """
        series = build_series(history)
        npdid = history[0].field_npdid

        history_months = series.history_months
        if history_months < MIN_HISTORY_MONTHS:
            raise InsufficientHistoryError(
                f"field {npdid} has {history_months} observed oe months "
                f"(< {MIN_HISTORY_MONTHS}); no forecast produced (R5)"
            )

        # Backtest the candidates and select the lowest-MAPE approach (R2, R3). Raises
        # AllApproachesFailedError if every candidate failed — surfaced to run_forecasts.
        selection = select(series)

        # Refit the selected approach on the FULL history and project the forward 24 months (R1).
        forward_values = self._forward_forecast(selection.method, series)
        points = [
            ForecastPoint(
                year=year,
                month=month,
                value=value,
            )
            for value, (year, month) in zip(
                forward_values,
                (series.forecast_month(step) for step in range(1, HORIZON + 1)),
            )
        ]

        # Classify credibility (R4): below the gate AND credibly backtestable (enough scorable months).
        # The guard is applied *before* construction so the contract's one-directional invariant holds.
        credible = (
            selection.backtest_mape < CREDIBLE_MAPE_GATE
            and selection.scorable_months >= MIN_SCORABLE
        )

        return FieldForecast(
            field_npdid=npdid,
            target=ForecastTarget.oil_equivalents,
            points=points,
            method=selection.method,
            backtest_mape=selection.backtest_mape,
            credible=credible,
            history_months=history_months,
        )

    @staticmethod
    def _forward_forecast(method: ForecastMethod, series: MonthlySeries) -> list[float]:
        """Refit the selected approach on the full series and forecast the forward horizon (R1).

        The forward forecast is a separate refit on **all** available data (train + the held-out
        window), distinct from the backtest's train-only fit (plan.md §Backtest). The selected
        approach backtested successfully on the (smaller) train split, so a full-history refit is
        expected to succeed; a :class:`FitError` here is re-raised as
        :class:`AllApproachesFailedError` so the field is reported unforecastable rather than crashing.
        """
        try:
            return _FORWARD_FIT[method](series, HORIZON)
        except FitError as exc:
            raise AllApproachesFailedError(
                f"selected approach {method.value} backtested but failed to refit on full history: {exc}"
            ) from exc
