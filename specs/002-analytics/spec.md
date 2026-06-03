# 002 analytics — spec

## Purpose
A forecasting engine that produces **credible, backtested** 24-month forecasts of per-field
**oil-equivalents** production, behind a single `Forecaster` interface. Consumes the frozen 001
contract (the `MonthlyProduction` oil-equivalents series); emits a typed forecast artifact for 003
(API) and 004 (charts). Depends on 001; built in a parallel worktree off the frozen contract.

## Scope
- **In:** per-field **24-month forward forecast of oil-equivalents** (million Sm³); a held-out
  **backtest** (final 24 months) with **MAPE**; per-field selection of the best of **≥2 competing
  approaches** (Arps decline-curve + a statistical time-series method) by backtest MAPE; a per-field
  **credibility** classification (MAPE < 15%); a typed forecast contract, persisted to the DuckDB store.
- **Coverage:** every field with **≥60 months** of production history (read from the frozen 001 store).
- **Out:** forecasting any stream other than oil-equivalents (oil / gas / NGL / condensate / water — not
  this cycle); economics, reserves, volumetrics; prediction intervals / bands; the HTTP API (003) and
  any charting or mapping (004); fields with <60 months (no credible forecast — reported
  insufficient-history); real-time / streaming.

## Requirements (EARS)
- **002-R1** — WHEN forecasting a field with at least 60 months of monthly production history, the
  system SHALL produce a 24-month forward forecast of its oil-equivalents production, one value per
  month following the field's last observed month.
- **002-R2** — The system SHALL produce every forecast through a single `Forecaster` interface, and for
  each field SHALL evaluate at least two competing approaches — an **Arps decline-curve** fit and a
  **statistical time-series** method — and select the approach with the **lowest held-out backtest MAPE**.
- **002-R3** — WHEN forecasting a field, the system SHALL backtest each candidate approach by holding out
  the field's **final 24 months**, fitting on the earlier history, forecasting those 24 months, and
  computing the **MAPE** against the held-out actuals (principle 6).
- **002-R4** — The system SHALL classify a field's forecast as **credible** WHEN its selected backtest
  MAPE is below 15%, and as **low-confidence** otherwise; a low-confidence forecast is flagged, never
  silently presented as credible.
- **002-R5** — IF a field has fewer than 60 months of production history, THEN the system SHALL NOT
  produce a credible forecast for it and SHALL record it as **insufficient-history**.
- **002-R6** — WHEN fitting a series or computing MAPE, the system SHALL treat an **absent (null)**
  monthly oil-equivalents value as a missing observation, never as zero production (per the 001
  contract's nullability discipline, 001-R6).
- **002-R7** — WHEN a forecast is produced, the system SHALL emit a typed `FieldForecast` recording the
  field NPDID, the 24 monthly forecast points, the selected approach, the backtest MAPE, and the
  credibility classification.
- **002-R8** — WHEN a forecasting run completes, the system SHALL persist each `FieldForecast` to the
  single DuckDB store, queryable by field NPDID.

## Data / interface contract (boundary consumed by 003 / 004)

### `Forecaster` (interface)
`forecast(history: Sequence[MonthlyProduction]) -> FieldForecast` — given one field's monthly history,
returns its typed forecast; the ≥2-approach evaluation, backtest and selection happen behind the
interface. (Signature illustrative — the **architect** formalises it in `plan.md`.)

### `FieldForecast` — one per forecastable field · key `field_npdid`
| field | type | unit | nullable | meaning |
|-------|------|------|----------|---------|
| `field_npdid` | int | — | no | links to 001 `Field` / `MonthlyProduction` |
| `target` | enum `oil_equivalents` | — | no | the forecast quantity (fixed this cycle) |
| `points` | list[`ForecastPoint`] (len 24) | — | no | the forward 24-month forecast |
| `method` | enum {`arps`, `<statistical>`} | — | no | the selected approach |
| `backtest_mape` | float ≥ 0 | fraction | no | held-out MAPE (`0.12` = 12%) |
| `credible` | bool | — | no | `backtest_mape < 0.15` |
| `history_months` | int ≥ 60 | — | no | the field's history length |

### `ForecastPoint` — one per forecast month
| `year` int (no) · `month` int 1–12 (no) · `value` float ≥ 0, **million Sm³** (no) — forecasted oil-equivalents |

Fields with <60 months produce **no** `FieldForecast` (reported insufficient-history, R5).

## Acceptance criteria
- **R1 / R2** — a field with ≥60 months yields a 24-point monthly oe forecast; the result names which of
  the ≥2 approaches was selected, and selection minimises backtest MAPE.
- **R3** — the reported MAPE equals the selected approach's error on the held-out final 24 months,
  recomputable from the field's history.
- **R4** — a representative NCS field backtests **< 15% MAPE** and is marked **credible**; a field whose
  selected MAPE ≥ 15% is marked **low-confidence** (flagged, not hidden).
- **R5** — a field with <60 months yields no forecast and appears as insufficient-history.
- **R6** — null monthly oe values are excluded as missing (not counted as 0) in both fit and MAPE.
- **R7 / R8** — each forecast validates against `FieldForecast` and is queryable from the DuckDB store by
  `field_npdid`.

## Open questions (defaults chosen; flag to change)
- **Persistence ownership** — 002 persists `FieldForecast` to DuckDB (mirrors 001's persist-and-return),
  so 003 serves from the store rather than recomputing live. *Default: 002 persists.* Confirm at plan.
- **MAPE on zero / near-zero actuals** — MAPE is undefined when an actual is 0. *Default:* compute MAPE
  over held-out months with a **positive** actual oe; a field whose held-out window has too few positive
  months to score is treated as not-credibly-backtestable → low-confidence. Confirm at plan.
- **Statistical method · Arps variant · libraries** — a **002 `plan.md`** decision (per roadmap): which
  time-series method, which Arps model (exponential / hyperbolic / harmonic), and the fitting libraries.
- **Prediction intervals** — out this cycle (point forecast only); a later plan may add bands for 004.
