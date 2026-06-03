"""ncs.forecast — phase 002 decline-forecasting engine.

The public seam (plan.md §Component shape):

* ``Forecaster().forecast(history) -> FieldForecast`` — the single-field interface every forecast is
  produced through: build the oe series, backtest ≥ 2 competing approaches (Arps decline + Holt
  damped-trend) on a held-out final 24 months, select the lower-MAPE approach, project a 24-month
  forward forecast, and classify it credible (R1–R7). Raises ``InsufficientHistoryError`` for a field
  with < 60 observed oe months (R5).
* ``run_forecasts(con) -> ForecastRun`` — the integration seam: read ``monthly_production`` from the
  single DuckDB store, forecast every field, persist the results (R8), and return the typed run.

The frozen forecast models live in ``ncs.forecast.contracts`` (``FieldForecast``, ``ForecastPoint``,
``ForecastMethod``, ``ForecastTarget``, ``ForecastRun``). This package is **additive** to the frozen
001 contract (``ncs.contracts``), which it consumes read-only.
"""

from __future__ import annotations

from ncs.forecast.forecaster import Forecaster, InsufficientHistoryError
from ncs.forecast.run import run_forecasts

__all__ = ["Forecaster", "run_forecasts", "InsufficientHistoryError"]
