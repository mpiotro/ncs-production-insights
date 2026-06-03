# Roadmap (living)

Ordered phases. **Living document** — refined as we go; the coordinator loads it per phase
(it is intentionally *not* imported by `CLAUDE.md`).

## Per-phase convention
Each phase gets a folder `specs/00N-<name>/` and runs the loop:

**spec.md → plan.md → tasks.md → implement → validate**

- `spec.md` — EARS requirements, each with an ID (e.g. `002-R3`). Author: coordinator.
- `plan.md` + interfaces — design & feature-specific choices. Author: **architect**.
- acceptance tests — from the EARS criteria, in `tests/acceptance/`. Author: **test-author** (never the implementer).
- implementation + unit tests — under `src/` and `tests/unit/`. Author: **developer**.
- validation — findings vs spec + constitution. Author: **validator** (read-only).

Tasks, tests, and commits cite the EARS requirement IDs they satisfy (principle 8).

## Phases

### 001 — ingestion · *sequential; blocks everything*
Build the ingestion layer (SODIR REST client + CSV fallback + normalization) and **FREEZE the data
contract**: typed Pydantic v2 models for monthly production per field and for field geometry.
**Sources (SODIR, NLOD 2.0):** REST JSON `https://factmaps.sodir.no/api/rest/services/DataService`; CSV `https://factpages.sodir.no/downloads/csv/` (CSVs carry WKT geometry).
**Depends on:** nothing. **Unblocks:** 002, 003, 004.

### 002 — analytics · *depends on 001*
The forecasting engine behind a single `Forecaster` interface. Explore **two competing approaches** —
(a) classical **Arps decline-curve** fitting, (b) a **statistical time-series** forecast — adjudicated
by one acceptance target:

> **WHEN** forecasting a field with at least 60 months of history, the system **SHALL** produce a
> 24-month forecast whose **MAPE on a held-out final 24 months is below 15%**.

The specific statistical method and libraries are a **002 `plan.md`** decision, not fixed here.

### 003 — api · *depends on 001*
A REST API (FastAPI) over the frozen contract; OpenAPI / Swagger auto-generated.

### 004 — frontend · *depends on 001; consumes the API (003)*
Dashboard (Plotly: history + forecast) and map (Leaflet: fields as GeoJSON). Builds against the frozen
contract — mocking the API where needed — and integrates with 003 when available.

## Flow
```
001  (freeze contract)
       |
       +--> 002 analytics  -+
       +--> 003 api         +-- parallel, separate worktrees (own DB file + port)
       +--> 004 frontend   -+   004 integrates with 003's API at the end
```
Once 001's contract is frozen, **002 / 003 / 004 fan out in parallel**, each in its own worktree.
