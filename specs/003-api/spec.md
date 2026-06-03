# 003 api — spec

## Purpose
A read-only **FastAPI** REST API serving the frozen 001 data (fields, monthly production, and field
geometry as **GeoJSON**) and the 002 forecasts, with **OpenAPI / Swagger auto-generated** from the typed
models. The single data source the 004 dashboard consumes. Depends on 001 (frozen contract) and serves
002's `FieldForecast`; built in a parallel worktree (own DuckDB file + distinct port).

## Scope
- **In:** read-only HTTP endpoints over the single DuckDB store — list & detail **fields**, per-field
  **monthly production** history, per-field **forecast**, and fields as a **GeoJSON** FeatureCollection
  (WKT→GeoJSON via shapely); **auto-generated OpenAPI/Swagger**; typed responses (the existing Pydantic
  models — contract-first).
- **Out:** any write / ingest / forecast-trigger endpoint (the store is populated by the 001 & 002 batch
  runs); authentication, accounts, rate-limiting (mission out-of-scope); the frontend (004);
  streaming / websockets.

## Requirements (EARS)
- **003-R1** — The system SHALL expose a **read-only** HTTP API over the single DuckDB store, serving the
  typed 001 / 002 models, and SHALL NOT mutate the store.
- **003-R2** — WHEN a client requests the field list, the system SHALL return every persisted field with
  its identity and descriptive attributes (npdid, name, current activity status, hc_type, main_area,
  operator, discovery_year).
- **003-R3** — WHEN a client requests a field's monthly production, the system SHALL return that field's
  full `MonthlyProduction` history (all streams, native units, **nulls preserved**) ordered by
  (year, month).
- **003-R4** — WHEN a client requests a field's forecast, the system SHALL return that field's
  `FieldForecast` (24-month oil-equivalents forecast, selected method, backtest MAPE, credibility); IF the
  field has no forecast (insufficient history), THEN the system SHALL indicate that distinctly (not an
  empty or fabricated forecast).
- **003-R5** — WHEN a client requests field geometry, the system SHALL return the fields as a **GeoJSON
  FeatureCollection** — polygons / multipolygons converted from the contract WKT via shapely, each feature
  carrying the field NPDID and name; a field with no outline carries null geometry (or is omitted).
- **003-R6** — IF a client requests a field NPDID not present in the store, THEN the system SHALL respond
  **HTTP 404** with a typed error body.
- **003-R7** — The system SHALL **auto-generate** its OpenAPI schema and interactive Swagger docs from the
  typed models (never hand-written), reflecting every endpoint and response model.

## Data / interface contract
003 **serves existing typed models** — 001 `Field` & `MonthlyProduction`, 002 `FieldForecast` — as JSON,
plus a **GeoJSON FeatureCollection** for geometry. It defines **no new persisted entity**; its consumable
contract is the **auto-generated OpenAPI document** (consumed by 004). Response envelopes (list wrapper,
GeoJSON Feature `properties`) are an **003 `plan.md`** detail.

## Acceptance criteria
- **R1** — the API answers reads and exposes no write/mutate route; the store is unchanged after any call.
- **R2 / R3** — the field list and a field's production history match what 001 persisted (counts, values,
  null-vs-zero preserved, ordered).
- **R4** — a forecastable field returns its `FieldForecast` (MAPE + credibility); an insufficient-history
  field is distinctly indicated.
- **R5** — geometry returns as valid GeoJSON polygons / multipolygons matching the source WKT.
- **R6** — an unknown NPDID yields 404 + typed error.
- **R7** — `/openapi.json` and Swagger UI exist and list every endpoint and typed response model.

## Open questions (defaults; flag to change)
- **Forecast coupling** — 003 serves 002's `FieldForecast`, so it builds against that contract and
  integrates with 002's persisted forecasts; during parallel dev it may read a fixture/mock until 002
  lands. *Default: forecast endpoint lives in 003.* Confirm.
- **Store population** — per tech-standards each worktree has its own DuckDB file + port; 003 reads a
  store populated by running 001 ingest (and 002) into `ncs-003.duckdb`. The population mechanics are a
  **plan.md** concern.
- **Port** — a distinct port pinned in `plan.md` / local env (CONTRIBUTING), never hard-coded in shared code.
- **Envelopes / pagination** — list-wrapper shape and whether any pagination is needed: **plan.md**.
