# 003 api — tasks

## Approach
Build order mirrors 001/002: **scaffold → failing acceptance suites → implementation**, TDD. The
developer scaffolds `ncs.api` + deps (T1); the **test-author** writes one failing acceptance suite per
concern, driving the app through FastAPI's **`TestClient`** over a **hermetically seeded** store (the
`get_connection` dependency overridden to a temp DuckDB built via the frozen 001 `ingest` + 002
`run_forecasts`, or direct `persist_*` — no network) (T2–T6); the **developer** then implements the
response / store / geojson layers and the FastAPI app (T7–T9), each task turning suites green and shipping
unit tests. The worktree runs the **full** suite (001 + 002 + 003), so all stay green and the `--cov=ncs`
ratchet (**≥94**) holds; T9 confirms + ratchets.

## Tasks
| ID | Title | EARS | Tests | Owner | Depends on |
|----|-------|------|-------|-------|------------|
| 003-T1 | scaffold `ncs.api` package + deps (fastapi, uvicorn) | — *(enabling)* | import smoke | developer | — |
| 003-T2 | acceptance suite + shared seeded-store / TestClient fixtures: field list & detail, unknown→404 | R2, R6 | tests/acceptance/test_api_fields.py | test-author | T1 |
| 003-T3 | acceptance suite: per-field production history (ordered, nulls preserved ≠ 0) | R3 | tests/acceptance/test_api_production.py | test-author | T1, T2 |
| 003-T4 | acceptance suite: per-field forecast; insufficient-history → **distinct** 404 | R4 | tests/acceptance/test_api_forecast.py | test-author | T1, T2 |
| 003-T5 | acceptance suite: fields as GeoJSON FeatureCollection (incl. null geometry) | R5 | tests/acceptance/test_api_geojson.py | test-author | T1, T2 |
| 003-T6 | acceptance suite: read-only (no mutate routes) & auto-generated OpenAPI/Swagger | R1, R7 | tests/acceptance/test_api_meta.py | test-author | T1, T2 |
| 003-T7 | implement response/error models + store-read layer + geojson conversion | R2, R3, R4, R5, R6 | T2–T5 (+ unit) | developer | T1 |
| 003-T8 | implement FastAPI app: routes, deps (read-only conn), settings, CORS, `/health` | R1, R2–R7 | T2–T6 (+ unit) | developer | T7 |
| 003-T9 | implement seed entrypoint (frozen `ingest` + `run_forecasts`) + record coverage baseline | — *(demo data; integration R1–R7)* | all acceptance (+ unit) | developer | T7, T8 |

## Coverage check (principle 9)
| EARS | Test written by | Made to pass by |
|------|-----------------|-----------------|
| R1 | T6 | T8 (read-only conn + GET-only routes) |
| R2 | T2 | T7 (store) + T8 (routes) |
| R3 | T3 | T7 + T8 |
| R4 | T4 | T7 (forecast read + not-available) + T8 |
| R5 | T5 | T7 (geojson) + T8 (route) |
| R6 | T2 | T7 (not-found) + T8 (404 handler) |
| R7 | T6 | T8 (`response_model=` on every route ⇒ auto OpenAPI) |

T1 (scaffold) + T9 (seed / integration) are enabling/integrative — no EARS uniquely theirs. The worktree
runs the **full** suite (001+002+003); the `--cov=ncs` gate (**≥94**) holds over the combined code, T9
confirms no regression (ratchets up only if comfortably higher).

## Resolved (from plan.md / coordinator)
- **Acceptance seam = the FastAPI app via `TestClient`**, with the `get_connection` dependency overridden
  to a **hermetically seeded** temp DuckDB. Seed by calling the frozen `ingest(con, settings)` (local
  fixture `Settings`) + `run_forecasts(con)`, or by writing rows directly via 001/002 `persist_*` for a
  controlled **≥60 / <60-month** split (forecast vs insufficient-history). No live network.
- **The two 404s are distinct** via `ErrorResponse.code` (`field_not_found` R6 vs `forecast_not_available`
  R4): T4 asserts forecast-not-available (field exists, <60 months), T2 asserts unknown-field.
- **R5 null geometry → `geometry: null` feature** (kept, not omitted): T5 asserts a real
  polygon/multipolygon feature **and** a null-geometry feature, each with `{field_npdid, field_name}`.
- **Coordinator decisions:** no path prefix; env-configured **CORS** in `create_app()`; `GET /health`
  (non-EARS, operational — a light test, not an EARS trace); `/fields` ordered by `field_npdid`. Deps
  `fastapi` + `uvicorn`; port **8003** (`API_PORT` env).

## Open questions
- None blocking — the plan's open questions were resolved by the coordinator. `/health` is non-EARS
  (operational). The `seed` entrypoint (T9) is demo-data tooling exercised by a **developer unit test**
  (acceptance seeds hermetically), not an acceptance suite.
