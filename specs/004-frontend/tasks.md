# 004 frontend — tasks

## Approach
Build order mirrors 001–003. The **developer** scaffolds the isolated `frontend/` project and the
typed client seam (T1–T2); the **test-author** writes the black-box acceptance suites for R1–R6
(T3–T7, all **red** — the components don't exist yet); the **developer** implements in dependency
order — client → pure series → components/wiring — until they pass (T8–T10); finally the Node **CI
job is added and the frontend coverage baseline ratcheted** (T11). TDD per requirement: each R's
acceptance test is authored before the code that satisfies it.

**Boundaries (principle 4).** test-author owns `frontend/test/acceptance/` and authors its own
acceptance **mock + fixtures** implementing `NcsApiClient` (just as 001's test-author authored the
SODIR fixtures). developer owns `frontend/src/**`, the co-located `*.test.ts(x)` **unit** tests, and
the *shipping* dev-mode mock (`mockClient.ts` / `fixtures.ts`). Acceptance tests render real
components with a mock client injected and assert on **user-visible output**; the heavy view libs
(`react-leaflet`, `react-plotly.js`) are mocked to lightweight stand-ins so assertions land on
data / props / text and stay jsdom-safe (technique is the test-author's call).

**Coordinator note — architect open-qs all ACCEPTED:** oe-only chart; map-click selection **plus** a
field list so null-geometry fields stay selectable; Vitest + `@vitest/coverage-v8` + Testing-Library/
jsdom; a frontend coverage baseline tracked **separately** from Python's (~97.6%), set to what the
suite reports when it lands (recorded in the PR); OSM free tiles; CI **mock-only** (manual live-003
smoke at integration, per roadmap); `plotly.js-dist-min`.

## Tasks
| ID | Title | EARS | Tests | Owner | Depends on |
|----|-------|------|-------|-------|------------|
| 004-T1 | Scaffold `frontend/` — Vite + React + TS (`strict`), Vitest + `@vitest/coverage-v8` + Testing-Library/jsdom, `package.json` scripts (`dev`/`build`/`test`/`coverage`/`gen:api`), `tsconfig`, `.env.example`, gitignore (`node_modules`/`dist`/coverage); one green smoke test; coverage gate at 0 (ratcheted in T11) | R6 | smoke test (green) | developer | — |
| 004-T2 | Typed client seam — capture 003's `openapi.json` snapshot (dump `create_app().openapi()`), wire `gen:api` (`openapi-typescript` → `schema.gen.ts`), author `api/contracts.ts` (friendly aliases + `NcsApiClient` + `ForecastResult`/`ForecastNotAvailable` union) per `contracts.md` | R5 | (types compile; conformance asserted in T9) | developer | T1 |
| 004-T3 | Acceptance — **map (R1):** `FieldMap` renders one GeoJSON polygon per feature on free (no-token) tiles; clicking a feature selects its `field_npdid` | R1 | `test/acceptance/map.test.tsx` | test-author | T2 |
| 004-T4 | Acceptance — **chart (R2):** selecting a field shows one chart with an oe-history trace **and** a 24-point forecast trace, the two visually distinct | R2 | `test/acceptance/chart.test.tsx` | test-author | T2 |
| 004-T5 | Acceptance — **badge (R3):** a displayed forecast shows its MAPE (% ) and a **credible / low-confidence** badge matching `credible` / `backtest_mape` (002's classification) | R3 | `test/acceptance/badge.test.tsx` | test-author | T2 |
| 004-T6 | Acceptance — **no-forecast (R4):** an insufficient-history field shows its history **and** an explicit "no credible forecast" notice, draws **no** forecast trace, never blank or fabricated | R4 | `test/acceptance/no_forecast.test.tsx` | test-author | T2 |
| 004-T7 | Acceptance — **data source, mockability & coverage setup (R5, R6):** `selectClient` returns mock vs http by **config alone**; components render unchanged against an injected mock client; a guard test asserts the coverage tooling is wired (R6) | R5, R6 | `test/acceptance/client.test.tsx`, `test/acceptance/coverage_setup.test.ts` | test-author | T2 |
| 004-T8 | Implement **API client + config + dev-mode mock** — `httpClient` (fetch the un-prefixed 003 paths; map **404 `forecast_not_available` → `ForecastNotAvailable` value**, throw on `field_not_found`/other non-2xx), `selectClient`, `config`, `mockClient` + `fixtures` (≥1 credible, ≥1 low-confidence, ≥1 <60-mo no-forecast). Unit: 404→outcome mapping, `selectClient` switch | R5, R4 | passes T7 (+ unit) | developer | T7 |
| 004-T9 | Implement **pure series builders** — `productionSeries` (oe stream, JSON `null`→gap, `(year,month)` ordering), `forecastSeries` (24 points); + **type-conformance** test (`expectTypeOf` friendly aliases ⊑ `schema.gen.ts`). Unit tests | R2, R5 | (feeds T4) + conformance | developer | T8 |
| 004-T10 | Implement **components + wiring** — `FieldMap` (R1), `ProductionForecastChart` (R2), `ForecastBadge` (R3), `NoForecastNotice` (R4), `FieldDetailPanel` + `useFieldData`, `App` + `main` (`selectedNpdid` state, list fallback for null-geometry fields). Unit: `useFieldData` / panel branching | R1, R2, R3, R4 | passes T3, T4, T5, T6 (+ unit) | developer | T3, T4, T5, T6, T9 |
| 004-T11 | **Node CI job** in `.github/workflows/ci.yml` (parallel to Python: `setup-node`, `npm ci`, `npm run coverage`, `tsc --noEmit`); **ratchet** the frontend coverage gate to the landed baseline (principle 9) | R6 | full suite green under coverage | developer | T10 |

## Coverage check (principle 9)
Every EARS ID has a test-author task that writes its failing test and a developer task that makes it pass:

| EARS | Acceptance test (author) | Made to pass by |
|------|--------------------------|-----------------|
| 004-R1 | T3 `map.test.tsx` | T10 (`FieldMap`) |
| 004-R2 | T4 `chart.test.tsx` | T9 (series) + T10 (chart) |
| 004-R3 | T5 `badge.test.tsx` | T10 (`ForecastBadge`) |
| 004-R4 | T6 `no_forecast.test.tsx` | T8 (`ForecastNotAvailable`) + T10 (notice + history-only) |
| 004-R5 | T7 `client.test.tsx` | T8 (client/select) + T9 (conformance) |
| 004-R6 | T7 `coverage_setup.test.ts` | T1 (tooling) + T11 (CI gate + ratchet) |

No EARS ID is left without a test. R6 (the test apparatus itself) is verified by its setup-guard test
plus the whole suite executing under `npm run coverage` and the CI gate (T11) — its baseline is the
first frontend ratchet value (recorded in the PR), tracked separately from the Python baseline.

## Open questions
1. **jsdom vs heavy view libs.** `react-leaflet` / `react-plotly.js` touch DOM/canvas APIs jsdom lacks.
   Recommended (and assumed above): the test-author **mocks those two modules** to lightweight
   stand-ins and asserts on the props/data/text passed to them (black-box at the component contract),
   rather than rendering real Leaflet/Plotly. Flag if you'd prefer a different technique.
2. **Nothing else blocking** — the architect's defaults are accepted (see Approach). Ready for the
   test-author to start T3–T7 once T1–T2 land.
