# 003 api — plan

Design for the **read-only FastAPI** layer over the single DuckDB store: it serves the frozen 001
`Field` / `MonthlyProduction` and the 002 `FieldForecast` as JSON, plus fields as a **GeoJSON
FeatureCollection** (WKT→GeoJSON via shapely), with **OpenAPI / Swagger auto-generated** from the typed
models. Every element cites the EARS ID(s) it serves (principle 8). **Design only** — no implementation
code, no tests. The new response types (envelopes / GeoJSON / error) are in `contracts.md`; 003 defines
**no new persisted entity** (principle 3).

This layer is **purely additive**: it lives in a new `src/ncs/api/` package and reads the existing tables
read-only. It does **not** touch 001 (`ncs.*`) or 002 (`ncs.forecast.*`) — those stay frozen inputs.

---

## Component shape (the seams)

```
                 ┌──────────────────────────────────────────────────────┐
   HTTP client → │  FastAPI app (ncs.api.app)                            │
   (004 / curl)  │    routers: fields · production · forecast · geojson  │  R2 R3 R4 R5 R6 R7
                 │      │            depends on ↓ (injected, read-only)   │
                 │   get_connection()  ──►  DuckDB read-only connection   │  R1
                 │      │            calls ↓                              │
                 │   store-read layer (ncs.api.store) ── reconstructs ──► │  Field / MonthlyProduction /
                 │                                       frozen models    │  FieldForecast (R2 R3 R4)
                 │   geojson layer (ncs.api.geojson) ── shapely WKT→GeoJSON│  R5
                 └──────────────────────────────────────────────────────┘
   (populated, out-of-band, by the seed/build entrypoint — see §Store population — never by the API)
```

A small, layered package. Each layer is a seam the developer fills and the test-author targets:

| Module | Responsibility | EARS |
|--------|----------------|------|
| `src/ncs/api/__init__.py` | package marker | — |
| `src/ncs/api/responses.py` | the response models from `contracts.md` (envelopes, GeoJSON, error) | R2–R7 |
| `src/ncs/api/store.py` | **read-only** store queries → reconstruct frozen `Field` / `MonthlyProduction` / `FieldForecast` | R2 R3 R4 R6 |
| `src/ncs/api/geojson.py` | one pure fn: `Field` → `FieldFeature` via shapely (WKT→GeoJSON) | R5 |
| `src/ncs/api/deps.py` | `get_connection()` — the injected read-only DuckDB dependency | R1 |
| `src/ncs/api/settings.py` | `ApiSettings` (DB path, host, port) from env — no secrets, no hard-coding | R1 |
| `src/ncs/api/errors.py` | `FieldNotFoundError` / `ForecastNotAvailableError` + the handler → 404 + `ErrorResponse` | R6 R4 |
| `src/ncs/api/routes/*.py` | the four routers (signatures below); thin — parse path param, call `store`, shape response | R2–R6 |
| `src/ncs/api/app.py` | `create_app()` — build `FastAPI`, include routers, register the error handler | R1 R7 |
| `src/ncs/api/seed.py` | the **build/seed** entrypoint (populate `ncs-003.duckdb`); **separate** from the API | (demo data; serves R2–R5) |

> **Why an app *factory* (`create_app()`), not a module-level `app`.** The acceptance suite must spin the
> app over a **hermetically seeded** store with the connection dependency overridden (FastAPI
> `dependency_overrides`); a factory + injected `get_connection` makes that a one-liner and keeps the app
> free of global state (R1: read-only, testable). `uvicorn` serves `create_app()` in production.

### Read-only connection dependency (R1)
`get_connection()` yields a DuckDB connection opened **read-only** (`duckdb.connect(path,
read_only=True)`) against `ApiSettings.db_path`, and closes it after the request. Read-only at the
engine level is the structural guarantee for R1 — even a stray write SQL would raise. There are **no
write/mutate routes** in any router (R1). The dependency is the single seam the acceptance suite
overrides to point at its seeded fixture store (no live network, §Store population).

---

## Endpoints (R2–R7)

Route **signatures** only (bodies are the developer's). All are `GET`; the app exposes **no** POST / PUT
/ PATCH / DELETE (R1). `response_model=` is set on every route so the response is validated and **OpenAPI
documents it** (R7). `npdid` path params are typed `int` (FastAPI 422s a non-int automatically).

```python
# ncs/api/routes/fields.py  — field list + detail (R2, R6)
@router.get("/fields", response_model=FieldListResponse)                       # R2
def list_fields(con = Depends(get_connection)) -> FieldListResponse: ...

@router.get("/fields/{npdid}", response_model=Field,                            # R2 (detail)
            responses={404: {"model": ErrorResponse}})                          # R6
def get_field(npdid: int, con = Depends(get_connection)) -> Field: ...

# ncs/api/routes/production.py  — per-field monthly history (R3, R6)
@router.get("/fields/{npdid}/production", response_model=ProductionHistoryResponse,
            responses={404: {"model": ErrorResponse}})                          # R3 + R6
def get_production(npdid: int, con = Depends(get_connection)) -> ProductionHistoryResponse: ...

# ncs/api/routes/forecast.py  — per-field forecast (R4, R6)
@router.get("/fields/{npdid}/forecast", response_model=FieldForecast,
            responses={404: {"model": ErrorResponse}})                          # R4 (+ R6)
def get_forecast(npdid: int, con = Depends(get_connection)) -> FieldForecast: ...

# ncs/api/routes/geojson.py  — fields as a GeoJSON FeatureCollection (R5)
@router.get("/fields.geojson", response_model=FieldFeatureCollection)           # R5
def fields_geojson(con = Depends(get_connection)) -> FieldFeatureCollection: ...
```

| Endpoint | Behaviour (the acceptance bar) | EARS |
|----------|--------------------------------|------|
| `GET /fields` | every persisted field (npdid, name, current_activity_status, hc_type, main_area, operator, discovery_year) in a `FieldListResponse`; counts/values match what 001 persisted | **R2** |
| `GET /fields/{npdid}` | that field's frozen `Field`; **404 + `ErrorResponse(field_not_found)`** if the NPDID is absent | **R2**, **R6** |
| `GET /fields/{npdid}/production` | full `MonthlyProduction` history, **ordered `(year, month)`**, all six streams native units, **nulls preserved (null ≠ 0.0)**; 404 if the field is unknown | **R3**, R6 |
| `GET /fields/{npdid}/forecast` | the field's `FieldForecast` (24 points, method, MAPE, credible). **Insufficient history → 404 + `ErrorResponse(forecast_not_available)`** — a *distinct* outcome, never an empty/fake forecast. Unknown NPDID → 404 + `field_not_found` | **R4**, R6 |
| `GET /fields.geojson` | fields as a GeoJSON `FeatureCollection`; each feature = shapely(WKT)→GeoJSON Polygon/MultiPolygon + `{field_npdid, field_name}`; **null-outline field → `geometry: null`** | **R5** |
| `GET /openapi.json`, `GET /docs` | FastAPI's **auto-generated** schema + Swagger UI, listing every endpoint and response model | **R7** |

**R6 / R4 distinctness.** Two 404 conditions, told apart by `ErrorResponse.code`: `field_not_found`
(npdid not in `field`, R6) vs `forecast_not_available` (field exists, no row in `field_forecast` because
< 60 months, R4 / 002-R5). The store layer raises `FieldNotFoundError` / `ForecastNotAvailableError`; one
exception handler maps each to 404 with the right `code` (R4 demands the insufficient-history case be
*distinctly* indicated). R7's auto-generated schema is satisfied **purely** by `response_model=` /
`responses=` on the routes — nothing hand-written (tech-standards: OpenAPI never hand-written).

---

## Store read + reconstruct (R2, R3, R4, R6)

`ncs/api/store.py` runs the **read** side of the round-trip 001/002 already support: the data tables'
columns equal their frozen model's fields exactly, so a `SELECT` row reconstructs the model under
`extra="forbid"` (no stray columns). All queries are `SELECT`-only (R1). Read functions (signatures —
bodies are the developer's):

```python
def list_fields(con) -> list[Field]: ...                       # SELECT * FROM field ORDER BY field_npdid  (R2)
def get_field(con, npdid: int) -> Field: ...                   # one row; raise FieldNotFoundError if none (R2, R6)
def get_production(con, npdid: int) -> list[MonthlyProduction]: ...  # ORDER BY year, month; raise if field absent (R3, R6)
def get_forecast(con, npdid: int) -> FieldForecast: ...        # join parent + 24 points; raise if no forecast (R4)
```

- **Field reconstruction (R2).** `SELECT <Field columns> FROM field` → `Field(**row)`. Column order is
  taken from `Field.model_fields` (as 001's persist does), so the row maps 1:1; `geometry_wkt` rides
  along for the detail endpoint and is re-used by the geojson layer.
- **Production reconstruction (R3).** `SELECT <MonthlyProduction columns> FROM monthly_production WHERE
  field_npdid = ? ORDER BY year, month`. **Ordering is in SQL** (R3). A DuckDB `NULL` stream reads back
  as Python `None` and stays `None` through Pydantic — **null ≠ 0.0 is preserved end to end** (the crux
  of R3, mirroring 001-R6). The reconstructed rows carry the real `field_name` from the table.
- **Forecast reconstruction (R4).** `field_forecast` holds the scalar row (`target, method,
  backtest_mape, credible, history_months`); the 24 points live in `field_forecast_point`. Read the
  parent by `field_npdid`, then `SELECT year, month, value FROM field_forecast_point WHERE field_npdid =
  ? ORDER BY year, month` → build `[ForecastPoint(...)]`, assemble `FieldForecast(...)`. The frozen
  model's `model_validator` re-asserts the 24-point and `credible ⟹ mape < 0.15` invariants on
  reconstruction, so a corrupt store row fails loudly rather than serving a bad forecast.
- **The two not-found paths (R6, R4).** `get_field` / `get_production` raise `FieldNotFoundError` when no
  `field` row exists for the npdid (R6). `get_forecast` raises `ForecastNotAvailableError` when the field
  exists but `field_forecast` has no row for it (R4 insufficient-history) — and `FieldNotFoundError` if
  the field itself is unknown. **Existence is checked against the `field` table**, so "field exists but
  has no forecast" (R4) is cleanly separable from "no such field" (R6).

> **No 002 import needed for the insufficient-history decision.** The absence of a `field_forecast` row
> *is* the insufficient-history signal (002 only persists forecasts for ≥ 60-month fields; the
> `forecast_run.insufficient_history_npdids` audit array corroborates it but the store layer needn't read
> it). This keeps 003's read path a plain table read, decoupled from 002's run internals.

---

## GeoJSON conversion (R5)

`ncs/api/geojson.py` is one pure function plus the collection assembly — unit-testable in isolation
(no DB, no HTTP):

```python
def field_to_feature(field: Field) -> FieldFeature: ...                 # shapely WKT → GeoJSON geometry (R5)
def fields_to_feature_collection(fields: list[Field]) -> FieldFeatureCollection: ...   # R5
```

- **WKT → GeoJSON via shapely** (tech-standards): `shapely.wkt.loads(field.geometry_wkt)` →
  `shapely.geometry.mapping(geom)` yields the GeoJSON geometry dict (`{type, coordinates}`) placed in
  `FieldFeature.geometry`. The geometry is always Polygon or MultiPolygon — 001's `Field` validator
  already guarantees that for any non-null WKT, so 003 doesn't re-validate the geometry class.
- **`properties` carry npdid + name** (R5): `FieldProperties(field_npdid=..., field_name=...)`.
- **Null outline (R5).** When `field.geometry_wkt is None`, the feature is emitted with **`geometry:
  null`** (RFC 7946 permits it) rather than dropped — the collection then has one feature per field and
  004 can list every field, geometry or not. *(Omission is the documented alternative; see §Resolved.)*
- The route reuses `store.list_fields(con)` (the same fields as `/fields`) and maps each through
  `field_to_feature` — so the map layer and the list layer are guaranteed consistent.

---

## Store population vs read (resolves spec open-question "Store population")

**The API only ever *reads*** `ncs-003.duckdb` (read-only connection, R1). Populating it is a **separate,
out-of-band** step — never an endpoint (the spec puts ingest/forecast-trigger out of scope).

- **Build/seed entrypoint — `ncs/api/seed.py`** (a `build_store(con, settings)` function + a thin
  `__main__` so it runs as `python -m ncs.api.seed`). It calls the **frozen** batch runs in order against
  one writable connection:
  1. `ncs.pipeline.ingest(con, settings)` → loads `field` + `monthly_production` (+ `ingestion_report`);
  2. `ncs.forecast.run.run_forecasts(con)` → loads `field_forecast` (+ points, + `forecast_run`).
  Then the connection closes; the API process later opens the same file **read-only**. This is exactly
  the "run 001 ingest (and 002) into `ncs-003.duckdb`" the spec/tech-standards prescribe, so the demo
  serves real SODIR data. `ingest`'s `Settings` come from env/config (URLs in production), never
  hard-coded — same boundary 001 fixed (no secrets, principle 7).
- **Who runs it.** The seed is a deploy/demo step the coordinator or developer runs once (and on data
  refresh); CI/acceptance never hits the live SODIR network. It is intentionally **not** wired into
  `create_app()` — the running API neither ingests nor forecasts (R1).
- **Hermetic seeding for acceptance tests.** The test-author seeds a temp store by calling the same
  frozen `ingest(con, settings)` with `Settings` pointing at **local fixture files** (001 already
  supports a filesystem `Source.location`) followed by `run_forecasts(con)` — or, for forecast cases
  that need a guaranteed ≥60-month / <60-month split without heavy fixtures, by writing rows directly via
  001/002's `persist_*` helpers. Either way the store is built **without network**, then the
  `get_connection` dependency is overridden to point the app at it. This keeps R2–R5 acceptance tests
  black-box over a real (seeded) store, deterministic and offline.

> **Why reuse the frozen runs rather than re-implement a loader.** Reconstruction fidelity (R2/R3/R4) is
> *defined* by the 001/002 round-trip; seeding through the very functions that persist guarantees 003
> reads exactly what those phases write — no parallel, drift-prone loader.

---

## Read-only, port, deps (R1)

- **Read-only (R1).** Engine-level `read_only=True` connection + zero write routes; the store is
  unchanged after any call (the R1 acceptance bar). The seed (writes) is a distinct entrypoint, never the
  API.
- **Port — `8003`.** 003's distinct port, pinned **here and in local env** (`API_PORT`, per CONTRIBUTING:
  never hard-coded in shared code — `ApiSettings` reads it, defaulting to `8003`). Distinct from 004's dev
  server, so worktrees run side by side without collision (tech-standards). Host defaults to `127.0.0.1`.
- **DB path** from `ApiSettings.db_path` (env `NCS_DB_PATH`, default `ncs-003.duckdb` — gitignored,
  per-worktree). No secrets anywhere (principle 7); SODIR is open and only the **seed** needs URLs.
- **Libraries to add** (feature-specific — belong here, not the constitution):
  - **`fastapi`** — the app + auto-generated OpenAPI/Swagger (tech-standards; R7).
  - **`uvicorn`** — ASGI server to run `create_app()` (dev/demo).
  - **No new test dep:** FastAPI's `TestClient` runs on **`httpx`**, already a project dependency (001).
  - Reused, already present: **`duckdb`** (read), **`shapely`** (WKT→GeoJSON, R5), **`pydantic`** v2
    (responses). The seed reuses 001/002's existing deps transitively.
  Add `fastapi` + `uvicorn` to `pyproject.toml`; `uv.lock` is regenerated at build-out.

---

## Resolved open questions (spec §"Open questions" — one-line rationale each)

1. **Forecast coupling → the forecast endpoint lives in 003, served from 002's persisted
   `field_forecast`.** *Rationale:* the spec default; 003 reads the precomputed forecast (no live
   backtest), decoupled from 002's run internals — the table's presence/absence of a row *is* the R4
   signal. (During parallel dev a fixture store stood in; with 002 merged here, real forecasts seed.)
2. **Store population → a separate `ncs.api.seed` entrypoint runs frozen `ingest` + `run_forecasts` into
   `ncs-003.duckdb`; the API only reads.** *Rationale:* honours R1 (no ingest/forecast endpoint) and
   tech-standards (own DB file), and guarantees read-fidelity by seeding through the same functions that
   persist. Acceptance seeds hermetically (local fixtures / direct `persist_*`), no network.
3. **Port → `8003`, from `API_PORT` env (default in `ApiSettings`), never hard-coded in shared code.**
   *Rationale:* CONTRIBUTING's distinct-port rule; lets 003 + 004 run concurrently in their worktrees.
4. **Envelopes / pagination → thin `count`+items envelopes for the two list responses; detail / forecast
   return the bare frozen model; no pagination this cycle.** *Rationale:* the NCS field set is small
   (hundreds), so a single response is fine; an envelope leaves room to add paging later without breaking
   the shape. GeoJSON uses the standard `FeatureCollection` envelope (RFC 7946).
5. **Null-outline geometry → emit a feature with `geometry: null` (not omit).** *Rationale:* RFC 7946
   allows null geometry; keeping one feature per field lets 004 enumerate every field on the list even
   when it can't be drawn. (Spec allows omit *or* null — flagged below in case the coordinator prefers
   omit.)

---

## Traceability (principle 8)

| EARS | Where designed |
|------|----------------|
| R1 | §Read-only connection dependency (`read_only=True`, injected) · §Endpoints (GET-only, no mutate route) · §Store population (writes are the seed, not the API) |
| R2 | §Endpoints `GET /fields` + `GET /fields/{npdid}` · §Store read (`list_fields` / `get_field`) · `contracts.md` `FieldListResponse` + served `Field` |
| R3 | §Endpoints `GET /fields/{npdid}/production` · §Store read (`get_production`, `ORDER BY year, month`, null≠0.0 preserved) · `contracts.md` `ProductionHistoryResponse` |
| R4 | §Endpoints `GET /fields/{npdid}/forecast` · §Store read (`get_forecast`, parent+points join; `ForecastNotAvailableError` → 404 `forecast_not_available`) · `contracts.md` served `FieldForecast` + `ErrorResponse` |
| R5 | §GeoJSON conversion (`field_to_feature`, shapely WKT→GeoJSON, npdid+name, null geometry) · §Endpoints `GET /fields.geojson` · `contracts.md` `FieldFeature` / `FieldFeatureCollection` |
| R6 | §Endpoints (404 on unknown npdid) · §Store read (`FieldNotFoundError`) · `contracts.md` `ErrorResponse` (`field_not_found`) · §errors handler |
| R7 | §Endpoints (`response_model=` / `responses=` on every route; `/openapi.json` + `/docs`) · `app.py` `create_app()` — FastAPI auto-generates, never hand-written |

---

## Coordinator decisions on the open questions (resolved before tasks)

1. **API path prefix → none.** Unprefixed `/fields`, `/fields.geojson`, etc.; no versioning this cycle —
   004 uses a configurable base URL. (Single-cycle demo; keep the surface simple.)
2. **Null-outline geometry → emit `geometry: null`** (keep one feature per field), per the plan default —
   so 004 can enumerate every field on its list even when it can't be drawn.
3. **CORS → add a minimal, env-configured `CORSMiddleware`** in `create_app()` (allowed origin(s) from env,
   defaulting to the 004 dev origin) so 004 integrates cross-origin without a 003 change. No credentials;
   the surface is GET-only anyway (R1).
4. **Health endpoint → include** a trivial `GET /health` → `{"status": "ok"}` (no data, no DB hit). An
   operational/demo nicety (the run/verify flow pings it). **Non-EARS** — documented as operational, not a
   requirement; a light test is enough, no EARS trace needed.
5. **`/fields` ordering → by `field_npdid`** (stable, deterministic). 004 sorts client-side for its picker.
