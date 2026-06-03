"""End-to-end forecasting run over the store — ``run_forecasts(con)`` (task 002-T12; R5, R8).

The integration seam (the 002 analogue of 001's ``ingest``): it reads ``monthly_production`` from the
single DuckDB store, forecasts every field through the one ``Forecaster.forecast`` seam, collects the
typed ``ForecastRun``, **persists** the forecasts (and an audit row), and returns the run summary
(plan.md §Component shape, §Input source, §Persistence).

Outcomes surfaced in the typed ``ForecastRun`` (never a silent omission):

* ``forecasts`` — one ``FieldForecast`` per field with ≥ 60 observed oe months (R1, R7);
* ``insufficient_history_npdids`` — fields with < 60 months, caught from
  :class:`InsufficientHistoryError` (R5);
* ``unforecastable_npdids`` — ≥ 60-month fields where neither approach could fit
  (:class:`AllApproachesFailedError`; plan.md edge case).

Persistence is **eager and committed** (``persist.py``): a follow-up query on the same connection — and
the idempotent second run the acceptance suite drives — sees the rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

import duckdb

from ncs.contracts import MonthlyProduction
from ncs.forecast.backtest import AllApproachesFailedError
from ncs.forecast.contracts import FieldForecast, ForecastRun
from ncs.forecast.forecaster import Forecaster, InsufficientHistoryError
from ncs.forecast.persist import (
    create_forecast_schema,
    persist_forecast_run,
    persist_forecasts,
    read_production_by_field,
)

# A stand-in field name for the reconstructed rows. The forecaster keys on field_npdid only and never
# reads field_name (plan.md §Input source — field_name is off the forecast contract), but the frozen
# MonthlyProduction model requires the (non-null) name, so we supply a constant placeholder.
_RECONSTRUCTED_NAME = "SODIR"


def _rows_for_field(
    field_npdid: int, observations: Sequence[tuple[int, int, float | None]]
) -> list[MonthlyProduction]:
    """Rebuild ``MonthlyProduction`` rows for one field from its ``(year, month, oe)`` store tuples.

    Only the oe series and the NPDID matter to the forecaster (R6/R8); ``field_name`` is a required
    contract field supplied as a placeholder. ``None`` oe stays ``None`` (absent, never 0 — R6).
    """
    return [
        MonthlyProduction(
            field_npdid=field_npdid,
            field_name=_RECONSTRUCTED_NAME,
            year=year,
            month=month,
            oil_equivalents=oil_equivalents,
        )
        for (year, month, oil_equivalents) in observations
    ]


def run_forecasts(con: duckdb.DuckDBPyConnection) -> ForecastRun:
    """Forecast every field in the store, persist the results, and return the typed run (R5, R8).

    Reads ``monthly_production`` grouped by ``field_npdid`` (§Input source), forecasts each field
    through ``Forecaster.forecast``, sorting outcomes into forecasts / insufficient-history /
    unforecastable, then **persists** (commits) the forecasts and an audit row before returning the
    ``ForecastRun``. Idempotent: a second call over the same store upserts in place (R8).
    """
    run_at = datetime.now(timezone.utc)

    grouped = read_production_by_field(con)
    forecaster = Forecaster()

    forecasts: list[FieldForecast] = []
    insufficient_history_npdids: list[int] = []
    unforecastable_npdids: list[int] = []

    # Deterministic order (by NPDID) so the run and any audit row are reproducible.
    for field_npdid in sorted(grouped):
        history = _rows_for_field(field_npdid, grouped[field_npdid])
        try:
            forecasts.append(forecaster.forecast(history))
        except InsufficientHistoryError:
            insufficient_history_npdids.append(field_npdid)
        except AllApproachesFailedError:
            unforecastable_npdids.append(field_npdid)

    run = ForecastRun(
        forecasts=forecasts,
        insufficient_history_npdids=insufficient_history_npdids,
        unforecastable_npdids=unforecastable_npdids,
    )

    # Persist eagerly (committed): the forecasts (queryable by NPDID, R8) + a run audit row.
    create_forecast_schema(con)
    persist_forecasts(con, forecasts)
    persist_forecast_run(con, run, run_at)

    return run
