# 002 analytics — forecast contract (Pydantic v2)

**This is the 002 seam.** The model signatures below are the typed boundary **003 serves** (over the
API) and **004 displays** (history + forecast charts). They mirror the spec's contract tables exactly
(spec §"Data / interface contract") and are formalised here by the architect; the `Forecaster`
interface that produces them is designed in `plan.md` §Component shape. Signatures and field
declarations only — **no method bodies, no fitting/backtest logic** (that is the developer's job,
built to these types).

This contract is **additive** to the frozen 001 contract (`ncs.contracts`). It does **not** redefine
or touch `MonthlyProduction` / `Field` — those stay read-only inputs (the forecaster *consumes*
`MonthlyProduction`; it never re-emits it).

Conventions (mirroring `specs/001-ingestion/contracts.md`):
- Pydantic v2, `model_config = ConfigDict(frozen=True, extra="forbid")` on every model — forecast
  records are immutable value objects and reject any stray field.
- Numeric constraints via `Annotated[..., Field(...)]`; **units live in field comments** (and the
  tables below). Forecast values are **million Sm³ of oil-equivalents** — the one target this cycle.
- `int` NPDIDs throughout (links to the 001 `Field` / `MonthlyProduction` key).
- A `model_validator` enforces the cross-field invariants the spec fixes (24 points; `credible`
  agrees with the 15% gate; `target` is the single allowed value) — so an inconsistent forecast can't
  be constructed and reach the store or the API.

---

## `ForecastMethod` (enum) — the candidate approaches (R2)

The selectable approaches the `Forecaster` adjudicates between (002-R2). The selected member is
recorded on every `FieldForecast.method`. Exactly these two compete this cycle; the enum is the
closed vocabulary 003/004 can switch on.

```python
from enum import Enum

class ForecastMethod(str, Enum):
    """Which approach produced a forecast — the selected one is recorded on FieldForecast (R2)."""
    arps_decline = "arps_decline"          # Arps hyperbolic decline-curve fit (plan.md §Approach A)
    holt_damped  = "holt_damped"           # damped-trend exponential smoothing (plan.md §Approach B)
```

> `str, Enum` so the value serialises to a plain string in JSON (003) / DuckDB. The two members are
> the two competing approaches `plan.md` justifies; selection picks the lower backtest MAPE (R2).

---

## `ForecastTarget` (enum) — the forecast quantity (R1, R7)

A single-member enum, deliberately. The forecast target is **fixed to oil-equivalents** this cycle
(spec §Scope; locked decision). Modelling it as an enum — rather than hard-coding the string — keeps
the contract self-describing for 003/004 and leaves an explicit, typed extension point if a later
phase forecasts another stream (it would add a member, never change the field type).

```python
from enum import Enum

class ForecastTarget(str, Enum):
    """The forecast quantity. Fixed to oil-equivalents this cycle (spec §Scope; R1)."""
    oil_equivalents = "oil_equivalents"    # million Sm³ — mirrors MonthlyProduction.oil_equivalents
```

---

## `ForecastPoint` — one forecast month (R1)

One point per forecast month: a calendar `(year, month)` and the forecasted oil-equivalents `value`.
A `FieldForecast` carries exactly 24 of these, the 24 months immediately following the field's last
observed month (R1). Values are **non-negative** — a decline forecast never predicts negative
production; a model that would is clamped at the producer (plan.md §Forecast generation), so the
contract value is `ge=0`.

```python
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field

class ForecastPoint(BaseModel):
    """One forecasted oil-equivalents value for one calendar month (R1)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    year:  int                                   # calendar year of the forecast month
    month: Annotated[int, Field(ge=1, le=12)]    # 1–12
    value: Annotated[float, Field(ge=0)]         # forecasted oil-equivalents · million Sm³ (≥ 0)
```

| field | type | unit | nullable | meaning |
|-------|------|------|----------|---------|
| `year` | int | — | no | calendar year of the forecast month |
| `month` | int (1–12) | — | no | calendar month |
| `value` | float ≥ 0 | million Sm³ | no | forecasted oil-equivalents for that month |

---

## `FieldForecast` — one per forecastable field · key `field_npdid` (R7)

The typed forecast artifact emitted per field with ≥60 months of history (R1, R7), persisted to
DuckDB (R8) and served by 003 / displayed by 004. It records the field key, the fixed target, the 24
forward points, the **selected** approach and its **held-out backtest MAPE**, the **credibility**
flag, and the field's **history length**.

Fields with **<60 months produce no `FieldForecast`** (reported insufficient-history, R5) — that
"insufficient-history" outcome is **not** a `FieldForecast` value; it is a run-level outcome the
`Forecaster` reports separately (plan.md §Component shape & §Insufficient history). So every
constructed `FieldForecast` necessarily has `history_months >= 60`.

```python
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator

class FieldForecast(BaseModel):
    """A field's 24-month oil-equivalents forecast: selection, backtest, credibility (R1–R4, R7)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    field_npdid:    int                                       # → 001 Field / MonthlyProduction key (R7)
    target:         ForecastTarget = ForecastTarget.oil_equivalents   # fixed this cycle (R1)
    points:         list[ForecastPoint]                       # the forward forecast — exactly 24 (R1)
    method:         ForecastMethod                            # the selected approach (R2)
    backtest_mape:  Annotated[float, Field(ge=0)]             # held-out MAPE, fraction (0.12 ⇒ 12%) (R3)
    credible:       bool                                      # backtest_mape < 0.15 (R4)
    history_months: Annotated[int, Field(ge=60)]              # field's history length, ≥ 60 (R1, R5)

    @model_validator(mode="after")
    def _check_invariants(self) -> "FieldForecast":
        """Enforce the spec's cross-field invariants (R1, R4). Body in src/ (developer).

        - exactly 24 forecast points (R1: a 24-month horizon);
        - ``credible`` ⟹ ``backtest_mape < 0.15`` (R4) — a credible forecast must have passed the gate,
          so a high-MAPE forecast can never be persisted/served as credible. The converse is
          intentionally **not** enforced: the producer's too-few-scorable-months guard (plan.md
          §Backtest) may set ``credible = False`` even at low MAPE, so the validator checks only that
          ``credible`` *implies* the gate, never the reverse;
        - ``target`` is oil-equivalents (the one target this cycle; redundant with the default but
          asserted so an explicit wrong target is rejected, not silently accepted).
        """
        ...
```

| field | type | unit | nullable | meaning |
|-------|------|------|----------|---------|
| `field_npdid` | int | — | no | links to 001 `Field` / `MonthlyProduction` (R7) |
| `target` | enum `oil_equivalents` | — | no | the forecast quantity, fixed this cycle (R1) |
| `points` | list[`ForecastPoint`] (len **24**) | million Sm³ | no | the forward 24-month forecast (R1) |
| `method` | enum {`arps_decline`, `holt_damped`} | — | no | the selected approach (R2) |
| `backtest_mape` | float ≥ 0 | fraction | no | held-out MAPE on the final 24 months (`0.12` = 12%) (R3) |
| `credible` | bool | — | no | `backtest_mape < 0.15` (R4) |
| `history_months` | int ≥ 60 | — | no | the field's history length (R1, R5) |

> **`backtest_mape` is a fraction, not a percentage** (`0.12` means 12%) — the field name says MAPE,
> the comment fixes the scale; the credibility gate is therefore `< 0.15`. 004 formats it as a
> percentage for display; the stored/served value stays a fraction so the gate comparison is exact.

---

## Why these (and only these) types are the seam

- **`FieldForecast` is the unit 003 serves and 004 charts.** It is self-contained: the 24 points plot
  directly after the field's history; `method` / `backtest_mape` / `credible` annotate the chart and
  let 004 badge a low-confidence forecast (R4) without recomputing anything.
- **No prediction intervals / bands.** Point forecast only this cycle (spec §Out; open question
  "Prediction intervals" → out). A later phase can add an optional `interval` field additively without
  breaking this seam.
- **Insufficient-history is not in this contract.** A field with <60 months yields *no* `FieldForecast`
  (R5); surfacing those NPDIDs is a run-report concern, designed in `plan.md` (the `Forecaster` returns
  them alongside the forecasts), kept out of the per-field artifact so the served object stays clean.
- **The input side is the frozen 001 contract, untouched.** `Forecaster.forecast` consumes
  `Sequence[MonthlyProduction]`; this file adds only the *output* models. 001's seam is read-only.
