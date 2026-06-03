"""Frozen typed forecast contract for 002 analytics (task 002-T6).

These model signatures are the 002 seam — the typed boundary **003 serves** (over the API) and
**004 displays** (history + forecast charts). They mirror ``specs/002-analytics/contracts.md``
exactly (field declarations copied verbatim from the frozen contract); the only code added here is
the body of the ``FieldForecast`` invariant validator, which the contract deliberately left to
``src/``.

This contract is **additive** to the frozen 001 contract (``ncs.contracts``): it does **not**
redefine or touch ``MonthlyProduction`` / ``Field`` — those stay read-only inputs (the forecaster
*consumes* ``MonthlyProduction``; it never re-emits it).

Conventions (mirroring ``ncs.contracts`` / ``specs/001-ingestion/contracts.md``):
- Pydantic v2, ``ConfigDict(frozen=True, extra="forbid")`` on every model — forecast records are
  immutable value objects and reject any stray field.
- Numeric constraints via ``Annotated[..., Field(...)]``; units live in field comments. Forecast
  values are **million Sm³ of oil-equivalents** — the one target this cycle.
- ``int`` NPDIDs throughout (links to the 001 ``Field`` / ``MonthlyProduction`` key).
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

# The spec-fixed forecast horizon (months) and credibility gate (a fraction). Module constants — the
# contract invariants below are stated in terms of them so the magic numbers live in exactly one
# place (plan.md §History/horizon, §Backtest "credibility").
FORECAST_HORIZON: int = 24
CREDIBLE_MAPE_GATE: float = 0.15


class ForecastMethod(str, Enum):
    """Which approach produced a forecast — the selected one is recorded on FieldForecast (R2)."""

    arps_decline = "arps_decline"  # Arps hyperbolic decline-curve fit (plan.md §Approach A)
    holt_damped = "holt_damped"  # damped-trend exponential smoothing (plan.md §Approach B)


class ForecastTarget(str, Enum):
    """The forecast quantity. Fixed to oil-equivalents this cycle (spec §Scope; R1)."""

    oil_equivalents = "oil_equivalents"  # million Sm³ — mirrors MonthlyProduction.oil_equivalents


class ForecastPoint(BaseModel):
    """One forecasted oil-equivalents value for one calendar month (R1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    year: int  # calendar year of the forecast month
    month: Annotated[int, Field(ge=1, le=12)]  # 1–12
    value: Annotated[float, Field(ge=0)]  # forecasted oil-equivalents · million Sm³ (≥ 0)


class FieldForecast(BaseModel):
    """A field's 24-month oil-equivalents forecast: selection, backtest, credibility (R1–R4, R7)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_npdid: int  # → 001 Field / MonthlyProduction key (R7)
    target: ForecastTarget = ForecastTarget.oil_equivalents  # fixed this cycle (R1)
    points: list[ForecastPoint]  # the forward forecast — exactly 24 (R1)
    method: ForecastMethod  # the selected approach (R2)
    backtest_mape: Annotated[float, Field(ge=0)]  # held-out MAPE, fraction (0.12 ⇒ 12%) (R3)
    credible: bool  # backtest_mape < 0.15, guard-adjusted (R4)
    history_months: Annotated[int, Field(ge=60)]  # field's history length, ≥ 60 (R1, R5)

    @model_validator(mode="after")
    def _check_invariants(self) -> "FieldForecast":
        """Enforce the spec's cross-field invariants (R1, R4).

        - exactly 24 forecast points (R1: a 24-month horizon);
        - ``credible`` ⟹ ``backtest_mape < 0.15`` (R4) — a credible forecast must have passed the
          gate, so a high-MAPE forecast can never be persisted/served as credible. The converse is
          intentionally **not** enforced: the producer's too-few-scorable-months guard (plan.md
          §Backtest) may set ``credible = False`` even at low MAPE, so the validator checks only that
          ``credible`` *implies* the gate, never the reverse;
        - ``target`` is oil-equivalents (the one target this cycle; redundant with the default but
          asserted so an explicit wrong target is rejected, not silently accepted).
        """
        if len(self.points) != FORECAST_HORIZON:
            raise ValueError(
                f"a FieldForecast must carry exactly {FORECAST_HORIZON} forecast points "
                f"(the {FORECAST_HORIZON}-month horizon); got {len(self.points)}"
            )
        if self.credible and not (self.backtest_mape < CREDIBLE_MAPE_GATE):
            raise ValueError(
                "a credible forecast must have backtest_mape < "
                f"{CREDIBLE_MAPE_GATE} (R4); got credible=True with "
                f"backtest_mape={self.backtest_mape}"
            )
        if self.target is not ForecastTarget.oil_equivalents:
            raise ValueError(
                f"the forecast target is fixed to oil-equivalents this cycle (R1); got {self.target}"
            )
        return self


class ForecastRun(BaseModel):
    """Typed summary of one forecasting run over the whole store (R5, R8). Returned and persisted.

    The 002 analogue of 001's ``IngestionReport`` — it makes the R5 "insufficient-history" outcome
    (and the both-approaches-fail edge case) a typed, queryable result rather than a silent omission.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    forecasts: list[FieldForecast]  # one per field with ≥ 60 months (R1, R7)
    insufficient_history_npdids: list[int]  # fields with < 60 months — no forecast (R5)
    unforecastable_npdids: list[int] = []  # ≥ 60 months but neither approach fit (plan.md edge case)
