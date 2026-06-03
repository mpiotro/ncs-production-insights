# 002 analytics — plan

Design for the forecasting engine behind a single `Forecaster` interface: it builds a per-field
oil-equivalents series from the frozen 001 `MonthlyProduction`, **backtests ≥2 competing approaches**
on a held-out final 24 months, **selects** the lower-MAPE approach, emits a 24-month forward forecast,
classifies it **credible** (MAPE < 15%), and **persists** the typed `FieldForecast` (`contracts.md`) to
the single DuckDB store. Every element cites the EARS ID(s) it serves (principle 8). **Design only** —
no implementation code, no tests; the typed seams are in `contracts.md`.

Built in the `002-analytics` worktree, off the **frozen** 001 contract (tagged `001-contract-frozen`),
which is consumed **read-only** — this plan does not redesign `MonthlyProduction` / `Field`.

## Component shape (the seams)

A small pipeline behind one public interface. Each stage is a pure-ish function the developer fills in
and the test-author targets through the `Forecaster` seam (mirroring how 001 exposed `ingest`):

```
read history (per field, from DuckDB)            build series (oe, calendar-spaced, gaps = missing)
        R8                                                R1 R6
            └────────────────────────┬─────────────────────┘
                                     ↓
   for each candidate approach:  backtest (hold out final 24, fit earlier, forecast, MAPE)
                                     R2 R3 R6
                                     ↓
              select lowest-MAPE approach   →   refit on full history → forward 24-month forecast
                            R2                                  R1
                                     ↓
            classify credible (MAPE < 0.15)  →  assemble FieldForecast  →  persist (DuckDB)
                       R4                              R7                      R8
                                     ↓
            fields with <60 months → no forecast, recorded insufficient-history (R5)
```

### The `Forecaster` interface (R1, R2, R7)

The one seam every forecast is produced through (002-R2). Public signatures only — **bodies are the
developer's**; the ≥2-approach evaluation, backtest and selection all happen behind `forecast`.

```python
from collections.abc import Sequence
from ncs.contracts import MonthlyProduction          # frozen 001 input (read-only)
from ncs.forecast.contracts import FieldForecast      # 002 output seam (contracts.md)

class Forecaster:
    """Produces a field's credible, backtested 24-month oil-equivalents forecast (R1, R2, R7).

    A single field's monthly history goes in; a typed FieldForecast comes out. The ≥2-approach
    evaluation (Arps decline + statistical), the held-out backtest, MAPE, selection, and the
    credibility classification all happen behind this one method (R2, R3, R4).
    """

    def forecast(self, history: Sequence[MonthlyProduction]) -> FieldForecast: ...
```

`forecast` is the **single-field** seam the acceptance tests drive (R1–R4, R7). It **raises**
`InsufficientHistoryError` (below) for a field with <60 usable months rather than returning a
non-credible stand-in — the absence of a `FieldForecast` *is* the R5 outcome, and the contract makes a
`<60`-month `FieldForecast` unconstructable (`history_months >= 60`).

A thin **run** wrapper drives the store end-to-end (the integration seam, like 001's `ingest`):

```python
import duckdb
from ncs.forecast.contracts import FieldForecast

def run_forecasts(con: duckdb.DuckDBPyConnection) -> ForecastRun: ...
```

```python
from pydantic import BaseModel, ConfigDict
from ncs.forecast.contracts import FieldForecast

class ForecastRun(BaseModel):
    """Typed summary of one forecasting run over the whole store (R5, R8). Returned and persisted."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    forecasts: list[FieldForecast]                 # one per field with ≥60 months (R1, R7)
    insufficient_history_npdids: list[int]         # fields with <60 months — no forecast (R5)
```

- `run_forecasts` reads every field's history from DuckDB (§Input source), calls `Forecaster.forecast`
  per field, collects the `FieldForecast`s, catches `InsufficientHistoryError` to populate
  `insufficient_history_npdids` (R5), **persists** the forecasts (§Persistence, R8), and returns the
  typed `ForecastRun`. `ForecastRun` is the 002 analogue of 001's `IngestionReport` — it makes the R5
  "insufficient-history" outcome a typed, queryable result rather than a silent omission.
- **No `Settings` model needed.** Unlike 001, 002 has no external sources/transports to configure — its
  only input is the DuckDB store, whose connection is passed in (mirroring 001's "DB lifecycle owned by
  the caller"). The 60-month threshold and the 15%/24-month constants are **spec-fixed**, so they live
  as named module constants, not runtime config (see §Resolved questions).

### Module layout (mirrors 001's `src/ncs/` seams)

A new `src/ncs/forecast/` package, additive to 001's modules — 001's files are untouched:

| module | responsibility | EARS |
|--------|----------------|------|
| `ncs/forecast/contracts.py` | the `contracts.md` models (`FieldForecast`, `ForecastPoint`, enums, `ForecastRun`) | R7 |
| `ncs/forecast/series.py` | DuckDB read → per-field calendar-spaced oe series; gaps = missing | R6, R8 |
| `ncs/forecast/backtest.py` | train/test split, per-approach fit→forecast→MAPE, selection | R2, R3, R6 |
| `ncs/forecast/methods/arps.py` | Approach A — Arps decline-curve fit (§Approach A) | R2 |
| `ncs/forecast/methods/stats.py` | Approach B — damped-trend exponential smoothing (§Approach B) | R2 |
| `ncs/forecast/forecaster.py` | the `Forecaster` interface; orchestrates backtest → select → forward → classify | R1, R2, R4 |
| `ncs/forecast/persist.py` | `field_forecast` table DDL + upsert; read history; persist run | R8 |
| `ncs/forecast/run.py` | `run_forecasts(con)` end-to-end + `ForecastRun` assembly | R5, R8 |

---

## The two competing approaches (R2) — design decision

002-R2 requires **≥2** approaches adjudicated by held-out backtest MAPE. Per the roadmap, the specific
statistical method, the Arps variant, and the libraries are **this plan's** call. Both approaches expose
the **same internal contract** so `backtest.py` treats them uniformly:

```python
# internal (NOT part of the frozen seam) — the shape every approach implements.
# fit a model to a gappy monthly oe series (index = month offsets, NaN = missing), then
# predict `horizon` steps ahead. Returns non-negative oe values (clamped at the producer).
def fit_and_forecast(series: "MonthlySeries", horizon: int) -> "list[float]": ...
```

### Approach A — Arps decline-curve (`method = arps_decline`)

The classical petroleum production-decline model. Rate vs time months `t` (from first production):

- **Hyperbolic** (the variant we fit): `q(t) = q_i / (1 + b · D_i · t) ** (1 / b)`, with
  `0 < b ≤ 1`, initial rate `q_i > 0`, initial nominal decline `D_i > 0`.
- This **subsumes** the other Arps forms as boundary cases: `b → 0` ⇒ **exponential**
  (`q_i · exp(-D_i · t)`), `b = 1` ⇒ **harmonic**. So fitting hyperbolic with `b` bounded to
  `(0, 1]` lets the optimiser land on whichever decline shape fits the field — we do **not** hard-pick
  exponential vs harmonic per field; the fit chooses.

**How it's fit (library: `scipy`).** Non-linear least squares (`scipy.optimize.curve_fit`, Levenberg–
Marquardt / trust-region) of `q(t)` to the field's **non-missing** monthly oe points (R6 — nulls are
excluded, never fed as 0). Seed `q_i` from early-history rate, `D_i` from the early decline slope,
`b = 0.5`; bound `b ∈ (0, 1]`, `q_i ≥ 0`, `D_i ≥ 0` so the result is a physically valid decline. The
forward forecast evaluates the fitted `q(t)` at the 24 future month-offsets; a non-converging fit (no
stable decline) makes the approach **score as a failed candidate** for that field (effectively +∞ MAPE,
so selection prefers the other approach — §Backtest).

- **Why hyperbolic-with-bounds:** one fit covers exponential→harmonic, matching how NCS oil fields
  actually decline (steep early, flattening tail); it is the standard, defensible decline model and
  needs only `scipy`, already implied by the numeric stack.

### Approach B — statistical time-series: damped-trend (Holt) exponential smoothing (`method = holt_damped`)

A purely empirical forecaster that doesn't assume a decline law — it extrapolates **level + a damped
trend** from the recent series, capturing fields that don't follow clean Arps decline (plateaus,
re-developments, late-life noise).

**Library: `statsmodels`** — `statsmodels.tsa.holtwinters.ExponentialSmoothing` with `trend="add"`,
`damped_trend=True`, no seasonal term (monthly oe decline is trend-dominated, not strongly seasonal;
keeping it seasonless avoids over-fitting 24-point holdouts). Smoothing parameters are estimated by the
library's MLE; the damped trend prevents the 24-month extrapolation from running away. Forecast =
`fit.forecast(24)`.

- **Why this method / library:** Holt damped-trend is the lightest credible statistical baseline that
  (a) handles trended, non-seasonal monthly data, (b) is a single well-tested `statsmodels` call, and
  (c) contrasts cleanly with Arps — one is mechanistic, one is empirical, so "select the lower backtest
  MAPE" is a meaningful choice (R2). It needs a **gap-filled, evenly-spaced** monthly series (it has no
  native missing-data handling), which §Null handling provides.
- **Why not ARIMA/Prophet:** `statsmodels` `ExponentialSmoothing` is already in scope for Holt; full
  ARIMA order-search adds fitting cost and instability on short single-field series, and Prophet pulls a
  heavy dependency for little gain over a damped trend here. Lean per tech-standards — flagged as an open
  question if the coordinator wants a different/additional statistical method.

### Libraries to add (developer runs `uv add` in this worktree)

| library | used for | justification |
|---------|----------|---------------|
| **`numpy`** | series math, MAPE vectorised, model evaluation | foundational; already implied by the numeric stack |
| **`scipy`** | Arps non-linear least-squares fit (`optimize.curve_fit`) | standard curve-fitting; no heavier dep needed for Approach A |
| **`statsmodels`** | Holt damped-trend exponential smoothing (Approach B) | single well-tested call for the statistical baseline; lighter/steadier than ARIMA/Prophet on short series |

`polars` (already in the 001 stack) **may** be used for the light reshaping of the DuckDB read into the
per-field series; the heavy lifting is numpy/scipy/statsmodels. No pandas added solely for this (the
`statsmodels` call accepts a numpy/array-like input). DuckDB and Pydantic v2 are already present.

---

## Building the per-field series (R1, R6)

`series.py` turns one field's `Sequence[MonthlyProduction]` into the modelling series both approaches
consume:

- **Target = `oil_equivalents` only** (spec; locked). Other streams are ignored this cycle.
- **Calendar-spaced, monotonic in time.** Order rows by `(year, month)`; place each observation at its
  integer **month offset** from the field's **first observed month** (`t = 0` at first month). This makes
  `t` the Arps time axis and gives a regular monthly index for Holt.
- **Gaps are explicit missing, never 0 (R6).** Two kinds of "no value" both become **missing** (NaN),
  not 0.0:
  1. a `MonthlyProduction` row whose `oil_equivalents is None` (SODIR published the row but no oe), and
  2. a calendar month with **no row at all** between the first and last observed months (a hole in the
     series).
  A literal `0.0` oe (a real zero-production month) **stays 0.0** — it is an observation, not missing.
  This is the crux of R6 and mirrors 001's absent→null discipline exactly.
- **The series spans first→last observed month inclusive**; trailing/leading absent months outside that
  span are simply not part of the series (the forecast starts after the **last observed** month).

`MonthlySeries` is an **internal** structure (not the frozen seam): the ordered month offsets, the oe
values with NaN for missing, and the anchor `(first_year, first_month, last_year, last_month)` needed to
stamp the forward `ForecastPoint` calendar (R1). Its exact form is the developer's.

---

## History length, eligibility, and the forward horizon (R1, R5)

- **"History length" / `history_months`** = the count of **observed monthly oe data points** for the
  field — i.e. `MonthlyProduction` rows for the field whose `oil_equivalents is not None`. Pure calendar
  holes and null-oe months do **not** count toward the 60 (they are missing, R6). This is the number
  recorded as `FieldForecast.history_months` and tested against the threshold.
- **Eligibility (R1, R5):** a field is forecastable iff `history_months >= 60`. `< 60` ⇒ **no forecast**,
  recorded as insufficient-history (R5) — `forecast` raises `InsufficientHistoryError`; `run_forecasts`
  collects the NPDID into `ForecastRun.insufficient_history_npdids`.
- **Forward horizon = 24 months** following the field's **last observed month** (R1). `ForecastPoint`
  calendar is computed by advancing `(last_year, last_month)` by 1..24 months (month wraps 12→1, year
  increments) — exactly 24 points, enforced by the `FieldForecast` validator.

---

## Backtest, selection & MAPE precision (R2, R3, R4; principle 6)

`backtest.py` is where principle 6 lives — **every** credibility claim is a held-out backtest.

### Train/test split (R3)

- **Hold out the final 24 months; fit on the earlier history; forecast those 24; score MAPE** (002-R3).
- The split is on the field's **observed-month series** (§series): the **last 24 observed-month points**
  are the test window; everything before is train.
- **≥60-month eligibility makes the split valid:** with ≥60 observed months, train = first
  `history_months − 24` ≥ **36** months, test = final 24. So the 60-month gate is exactly "enough to hold
  out 24 and still fit on ≥36" — the eligibility rule and the backtest split are the same arithmetic
  (R1/R5 ⇔ R3).
- Each candidate approach is fit on **train only**, forecasts 24 steps, and is scored against the held-out
  24 actual oe values. The **forward** forecast that ships in `FieldForecast` is a **separate refit on the
  full history** (train+test) — the backtest measures the method's error; the shipped forecast uses all
  available data (R1). Both use the **selected** approach (R2).

### MAPE formula (R3) and the zero/near-zero resolution (spec open question)

MAPE over the held-out window, computed only on months with a **positive** actual oe:

```
let P = { i in held-out 24 : actual_i is not missing AND actual_i > 0 }
MAPE = (1 / |P|) * Σ_{i in P} | actual_i − forecast_i | / actual_i        # a fraction (0.12 ⇒ 12%)
```

- **Resolves the spec's open question "MAPE on zero / near-zero actuals."** MAPE is undefined when an
  actual is 0 (division by zero), so a held-out month whose actual oe is `0.0` or **missing** is
  **excluded** from the error average — never forced into the denominator, never treated as a 0→count.
  This is the spec's stated default, adopted.
- **Too-few-positive guard (credibility, not silent pass):** if `|P|` is below a **minimum scorable
  count** (default **`MIN_SCORABLE = 12`** of the 24 held-out months positive), the field is
  **not credibly backtestable** → its forecast is forced **low-confidence** (`credible = False`),
  regardless of the numeric MAPE, so a forecast scored on a handful of points is never badged credible
  (R4). The numeric `backtest_mape` is still recorded (over whatever positive months exist) for
  transparency; the credibility flag is the safeguard. `MIN_SCORABLE` is a named constant flagged for the
  coordinator (§Open questions).
- **`backtest_mape` is stored as a fraction** (matching `contracts.md`): `0.12` = 12%, gate `< 0.15`.
- **Failed candidate handling:** an approach that fails to fit on train (Arps non-convergence, Holt
  estimation error) yields **no usable backtest forecast** → it is scored as **non-selectable** (treated
  as `+inf` MAPE) so selection falls to the other approach. If **both** approaches fail to fit, the field
  is reported insufficient-history-like (no `FieldForecast`); flagged as an edge case for the coordinator.

### Selection (R2) and credibility (R4)

- **Select** the approach with the **lowest held-out MAPE** over `P` (002-R2); record it as
  `FieldForecast.method` and its MAPE as `backtest_mape`. Ties (exceedingly unlikely on floats) break
  toward `arps_decline` (the mechanistic, more interpretable model) — a deterministic, documented rule.
- **Classify (R4):** `credible = backtest_mape < 0.15` **AND** `|P| >= MIN_SCORABLE`. A field whose
  selected MAPE ≥ 15%, or which is not credibly backtestable, is **`credible = False`** — flagged
  low-confidence, **never hidden** (the `FieldForecast` is still produced, persisted and served; 004
  badges it). The `FieldForecast` validator asserts `credible == (backtest_mape < 0.15)` **for the
  scorable case**; the too-few-positive override is applied **before** construction (the value passed in
  already reflects the guard), so the invariant holds as written in `contracts.md`. *(Note for the
  coordinator: the override means `credible` can be `False` even when the bare `backtest_mape < 0.15`; the
  validator must compare against the **guard-adjusted** credibility, not the raw fraction — called out in
  §Open questions so the contract invariant and the guard stay consistent.)*

---

## Null handling (R6) — absent oe is missing, never 0

Single rule, applied everywhere a value is read:

- In **series building**, **fitting**, and **MAPE**, an **absent** monthly oe — whether
  `oil_equivalents is None` on a present row, or a calendar month with no row — is a **missing
  observation** (NaN / excluded), **never 0.0** (002-R6, honouring 001-R6's nullability discipline).
- A **real `0.0`** oe month is a genuine observation: it is kept in the series (Holt sees it; Arps fits
  it), but it is **excluded from the MAPE denominator** (you cannot compute a percentage error against a
  zero actual — §MAPE). So `0.0` is "present and zero" for fitting, "unscorable" for MAPE; `None` is
  "absent" for both. These two are deliberately distinct, exactly as the frozen contract demands.
- This is unit-tested by the developer and acceptance-tested by the test-author (a series with embedded
  `None`s and a `0.0` month must fit/score identically to one where the missing months are simply not
  present — the `None`s must not pull the fit toward zero).

---

## Input source — reading `MonthlyProduction` (R8, resolves the open question)

002 reads its input from the **single DuckDB store**, the same store 001 writes (resolving "how the run
sources `MonthlyProduction`"):

- **Per-worktree DB file.** This worktree uses its own DuckDB file **`ncs-002.duckdb`** (tech-standards:
  each worktree gets its own DB file + distinct API port, so 002/003/004 don't collide). The connection
  is passed into `run_forecasts(con)` by the caller (mirroring 001's "DB lifecycle owned outside").
- **Populate before forecasting.** The worktree carries the frozen 001 ingestion code (`ncs.ingest`), so
  a run **first ingests into `ncs-002.duckdb`** (`ingest(con, settings)` → fills `monthly_production` /
  `field`), **then** forecasts over it. In hermetic acceptance tests this is the local-fixture ingest the
  001 suite already uses (no live network), so 002's acceptance suite seeds the store from fixtures and
  runs `run_forecasts` against it.
- **Read shape.** `series.py` reads `monthly_production` grouped by `field_npdid`, selecting
  `(year, month, oil_equivalents)` ordered by `(year, month)` — straight from the 001 table, no schema
  change to 001. Reconstructing full `MonthlyProduction` models is optional for the math, but the
  `Forecaster.forecast` **seam takes `Sequence[MonthlyProduction]`** (so it is unit-testable in isolation
  from DuckDB); `run.py` is the only place that touches the store and hands per-field sequences to
  `forecast`.

---

## Persistence (R8) — the `field_forecast` table

002 **persists** each `FieldForecast` to the single DuckDB store, queryable by `field_npdid` (002-R8;
resolves the "persistence ownership" open question — **002 persists**, mirroring 001's persist-and-return,
so 003 serves from the store rather than recomputing live). `persist.py` owns the DDL + upsert:

**Schema (the 24 points denormalised to a child table, keyed by field):**

```sql
CREATE TABLE IF NOT EXISTS field_forecast (
    field_npdid     BIGINT  PRIMARY KEY,           -- R8 key — one current forecast per field (R7)
    target          VARCHAR NOT NULL,              -- ForecastTarget value ('oil_equivalents')
    method          VARCHAR NOT NULL,              -- ForecastMethod value ('arps_decline'|'holt_damped')
    backtest_mape   DOUBLE  NOT NULL,              -- fraction (0.12 ⇒ 12%) (R3)
    credible        BOOLEAN NOT NULL,              -- backtest_mape < 0.15, guard-adjusted (R4)
    history_months  INTEGER NOT NULL               -- ≥ 60 (R1, R5)
);

CREATE TABLE IF NOT EXISTS field_forecast_point (
    field_npdid     BIGINT  NOT NULL,              -- → field_forecast.field_npdid (R7, R8)
    year            INTEGER NOT NULL,
    month           INTEGER NOT NULL,              -- 1–12
    value           DOUBLE  NOT NULL,              -- forecasted oe · million Sm³ (≥ 0)
    PRIMARY KEY (field_npdid, year, month)         -- one point per field-month ⇒ idempotent re-run (R8)
);
```

- **Why two tables:** the 24 `ForecastPoint`s are a clean child collection; a `(field_npdid, year, month)`
  PK on the points table makes a re-run **idempotent** (upsert in place, no duplicate points) and lets 003
  query a field's series with a simple ordered `SELECT`. The parent `field_forecast` carries the scalar
  selection/credibility row, PK `field_npdid` (R8: queryable by NPDID).
- **Upsert / idempotency.** Mirror 001's pattern: `INSERT ... ON CONFLICT (<pk>) DO UPDATE` on each PK,
  the whole persist for a field's forecast (parent row + its 24 points) in **one transaction** — re-running
  the forecaster over the same store **updates in place**, never duplicating. Because a re-forecast could
  in principle return fewer/renumbered points, the developer **deletes the field's existing points then
  inserts the new 24** within that transaction (clean replace), keeping the points table consistent with
  the parent (flagged as an implementation note, not a contract change).
- **`run_forecasts` also persists `ForecastRun`** (optional, parallel to 001's `ingestion_report`): a
  `forecast_run` row per run recording `run_at`, forecast count, and `insufficient_history_npdids` as a
  native `BIGINT[]` — so the R5 "insufficient-history" set is auditable from the store. Kept lightweight;
  flagged as a nice-to-have the coordinator can drop if out of scope.
- **Read-back round-trips the contract.** As in 001, the `field_forecast` columns equal the scalar
  `FieldForecast` fields (minus `points`, which live in the child table) so a persisted forecast
  reconstructs into the frozen model — the acceptance suite does that round-trip (R7/R8).

---

## Resolved questions (spec §"Open questions" + this plan — one-line rationale each)

1. **Persistence ownership → 002 persists `FieldForecast` to DuckDB.** *Rationale:* mirrors 001's
   persist-and-return; 003 serves a precomputed forecast from the single store instead of recomputing the
   backtest live on every request. (Spec default, adopted.)
2. **MAPE on zero / near-zero actuals → average over held-out months with a positive actual oe; too few
   positive ⇒ low-confidence.** *Rationale:* MAPE is undefined at actual 0; excluding zero/missing months
   keeps the metric well-defined, and the `MIN_SCORABLE` guard stops a forecast scored on a handful of
   points being badged credible (R4). (Spec default, adopted, with the guard made explicit.)
3. **Statistical method → Holt damped-trend exponential smoothing (`statsmodels`).** *Rationale:* lightest
   credible non-seasonal trended baseline, one tested call, a clean empirical contrast to mechanistic Arps;
   lighter/steadier than ARIMA/Prophet on short single-field series.
4. **Arps variant → hyperbolic with `b ∈ (0, 1]`, fit by `scipy` non-linear least squares.** *Rationale:*
   hyperbolic subsumes exponential (`b→0`) and harmonic (`b=1`), so one bounded fit picks the field's
   decline shape; standard, defensible, no heavy dependency.
5. **Prediction intervals → out this cycle.** *Rationale:* spec §Out; point forecast only. The
   `FieldForecast` seam can add an optional interval field additively later without breaking 003/004.
6. **Input source → ingest 001 into `ncs-002.duckdb` first, then forecast over the store.** *Rationale:*
   002 depends on 001; the worktree carries the frozen ingestion code, so the run populates its own
   per-worktree DB (hermetic fixtures in tests) and forecasts from the single store — no schema change to
   001, no live network in tests.
7. **No `Settings` model for 002.** *Rationale:* 002 has no external sources/transports to configure; its
   only input is the passed-in DuckDB connection, and the 60/24/0.15 constants are spec-fixed module
   constants, not runtime config.

---

## Traceability (principle 8)

| EARS | Where designed |
|------|----------------|
| 002-R1 | `contracts.md` `FieldForecast.points` (len 24) + `ForecastPoint`; §series, §History/horizon, `Forecaster.forecast` |
| 002-R2 | `contracts.md` `ForecastMethod`; §Two approaches (Arps + Holt), §Backtest "Selection" (lowest MAPE); `Forecaster` |
| 002-R3 | §Backtest — final-24 holdout, fit-on-earlier, MAPE formula; `backtest.py`; principle 6 |
| 002-R4 | `contracts.md` `FieldForecast.credible` + validator; §Backtest "credibility" (gate `< 0.15`, low-confidence flagged not hidden) |
| 002-R5 | §History/eligibility — `<60` ⇒ no forecast; `InsufficientHistoryError`; `ForecastRun.insufficient_history_npdids` |
| 002-R6 | §series (gaps = missing), §Null handling (absent ≠ 0; `0.0` kept but unscorable); `series.py` |
| 002-R7 | `contracts.md` `FieldForecast` (npdid, 24 points, method, mape, credible, history_months); `forecaster.py` assembly |
| 002-R8 | §Persistence — `field_forecast` (+ points) DDL, upsert, queryable by NPDID; §Input source — single DuckDB store |

---

## New open questions for the coordinator (decide before authoring tasks)

1. **`MIN_SCORABLE` threshold (zero-actuals guard).** Plan sets **12** of 24 held-out months must have a
   positive actual oe for a field to be *credibly* backtestable; below that ⇒ forced low-confidence.
   Confirm 12, or pick another minimum. (Affects R4 credibility on late-life/intermittent fields.)
2. **`credible` validator vs the guard (contract consistency).** The too-few-positive guard can make
   `credible = False` even when `backtest_mape < 0.15`. Either (a) the producer passes the
   **guard-adjusted** credibility (plan's assumption — validator stays `credible == (mape < 0.15)` only
   for the scorable case), or (b) `contracts.md` relaxes the validator to not over-constrain. Confirm (a)
   so the contract invariant and the guard agree.
3. **Both-approaches-fail edge case.** If *neither* Arps nor Holt fits a ≥60-month field (degenerate
   series), the plan yields **no `FieldForecast`** and reports it like insufficient-history. Confirm that
   bucket (vs. inventing a third fallback method this cycle).
4. **`ForecastRun` / `forecast_run` persistence scope.** Plan persists a per-run audit row (forecast count
   + `insufficient_history_npdids`) like 001's `ingestion_report`. Confirm it's in scope for 002, or drop
   it and surface insufficient-history only via the returned `ForecastRun`.
5. **Library footprint (`statsmodels`).** Approach B adds **`statsmodels`** (plus `scipy` for Arps). Confirm
   that's an acceptable dependency, or name an alternative statistical method to keep the footprint leaner.
6. **`field_name` on the forecast contract.** `FieldForecast` keys on `field_npdid` only (003 can join to
   `Field`/`monthly_production` for the name). Confirm we keep the artifact minimal rather than denormalising
   `field_name` onto it for 004's convenience.
