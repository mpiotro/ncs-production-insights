# 002 analytics — tasks

## Approach
Build order mirrors 001: **scaffold → failing acceptance suites → implementation**, TDD throughout. The
developer scaffolds the `ncs.forecast` subpackage + deps (T1); the **test-author** writes one failing
acceptance suite per concern off the frozen `contracts.md`, driving the
`Forecaster.forecast(history)` seam with **synthetic `MonthlyProduction` histories** (T2–T5, hermetic —
DuckDB only in the persistence suite); the **developer** then implements the contract models and the
`series → backtest/select → forecast → classify → persist` pipeline (T6–T12), each task turning its suite
green and shipping unit tests (principle 5). Integration + the coverage ratchet land at T12. The 002
worktree runs the **full** suite (001 + 002), so 001 stays green throughout.

## Tasks
| ID | Title | EARS | Tests | Owner | Depends on |
|----|-------|------|-------|-------|------------|
| 002-T1 | scaffold `ncs.forecast` subpackage + deps (numpy, scipy, statsmodels) | — *(enabling)* | import smoke | developer | — |
| 002-T2 | acceptance suite + shared synthetic histories: forecast produced & contract-valid | R1, R7 | tests/acceptance/test_forecast.py | test-author | T1 |
| 002-T3 | acceptance suite: backtest, approach selection & credibility gate | R2, R3, R4 | tests/acceptance/test_backtest.py | test-author | T1, T2 |
| 002-T4 | acceptance suite: ≥60-month eligibility & absent→missing (≠ 0) | R5, R6 | tests/acceptance/test_eligibility.py | test-author | T1, T2 |
| 002-T5 | acceptance suite: persistence & idempotent re-run | R8 | tests/acceptance/test_forecast_persistence.py | test-author | T1, T2 |
| 002-T6 | implement frozen forecast contract models + validators | R7 | T2 (+ unit) | developer | T1 |
| 002-T7 | implement per-field oe series build (gaps = missing, real 0.0 kept) | R6 | T4 (+ unit) | developer | T1, T6 |
| 002-T8 | implement the two approaches (Arps hyperbolic · Holt damped-trend) | R2 | T3 (+ unit) | developer | T6, T7 |
| 002-T9 | implement backtest + MAPE (positive actuals, MIN_SCORABLE) + selection | R2, R3 | T3 (+ unit) | developer | T7, T8 |
| 002-T10 | implement `Forecaster`: backtest→select→forward refit→classify; <60 raises | R1, R2, R4, R5 | T2, T3, T4 (+ unit) | developer | T6, T8, T9 |
| 002-T11 | implement DuckDB persistence (`field_forecast` + points) + upsert | R8 | T5 (+ unit) | developer | T6, T10 |
| 002-T12 | implement `run_forecasts` end-to-end (read store → `ForecastRun` → persist) + coverage baseline | R5, R8 *(+ integration R1–R8)* | T5 + all acceptance (+ unit) | developer | T2–T5, T10, T11 |

## Coverage check (principle 9)
| EARS | Test written by | Made to pass by |
|------|-----------------|-----------------|
| R1 | T2 | T10 (+ T12 integration) |
| R2 | T3 | T8 (approaches) + T9 (selection) |
| R3 | T3 | T9 |
| R4 | T3 | T10 |
| R5 | T4 | T10 (raise `InsufficientHistoryError`) + T12 (run collects) |
| R6 | T4 | T7 |
| R7 | T2 | T6 |
| R8 | T5 | T11 + T12 |

T1 (scaffold) and the T12 integration are enabling/integrative — no EARS is uniquely theirs. The worktree
runs the **full** suite (001 + 002), so 001 stays green and the `--cov=ncs` ratchet (**≥92**, inherited
from 001) holds over the combined code; T12 confirms no regression and ratchets up if higher.

## Resolved (from plan.md / coordinator)
- **Acceptance seams.** Forecasting / backtest / eligibility / null suites drive
  **`Forecaster.forecast(Sequence[MonthlyProduction]) -> FieldForecast`** (DuckDB-free, fast, controlled
  synthetic series). The persistence suite drives **`run_forecasts(con)`** — seed the store (insert
  `MonthlyProduction` rows, or run the frozen 001 `ingest` on local fixtures into `ncs-002.duckdb`), then
  forecast. Hermetic, no live network.
- **Synthetic fixtures (T2, shared by T3–T5).** The test-author builds histories programmatically as
  `MonthlyProduction` sequences: a clean-decline **≥60-month** field (backtests credible, <15%), a
  **<60-month** field (insufficient-history, R5), and a field carrying a **`None`** month and a real
  **`0.0`** month (R6). No SODIR CSVs — forecasting wants controlled series with known properties.
- **Libraries (T1).** `uv add numpy scipy statsmodels` in the worktree (coordinator-approved; statsmodels
  for Holt damped-trend). `MIN_SCORABLE=12`, the 60/24-month thresholds, and the 0.15 gate are spec-fixed
  **module constants**, not config.
- **`credible` invariant** is one-directional (`credible ⟹ backtest_mape < 0.15`); the producer applies
  the scorable-months guard **before** constructing `FieldForecast` (contracts.md).

## Open questions
- None blocking — the plan's open questions were resolved by the coordinator (validator direction,
  MIN_SCORABLE=12, statsmodels, `forecast_run` audit in scope at T12, `field_name` off the forecast,
  `ncs.forecast.*` layout). Flag if `forecast_run` audit persistence should be deferred out of 002.
