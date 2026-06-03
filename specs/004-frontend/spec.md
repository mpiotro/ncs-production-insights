# 004 frontend — spec

## Purpose
A **React + Vite + TypeScript** dashboard: pick an NCS field and see its **monthly oil-equivalents
history with the 24-month forecast** (Plotly) and the field **located on a map** (Leaflet / GeoJSON),
with the forecast's backtest credibility shown. Builds against the 003 API (mocking it where needed).
Depends on 001 (frozen contract); consumes 003. The demo's visible surface.

## Scope
- **In:** a single-page dashboard that (1) renders NCS fields on a **Leaflet** map as GeoJSON polygons;
  (2) on selecting a field, shows a **Plotly** time-series of its **oil-equivalents history + 24-month
  forecast**; (3) surfaces the forecast's **backtest MAPE** and a **credible / low-confidence** badge;
  (4) gets all data from the **003 API**, with a typed **mock** during parallel build. Frontend test +
  coverage tooling is established in this phase.
- **Out:** authentication / accounts; editing or writing data; multi-field comparison views; any
  forecasting or data logic (that lives in 001 / 002 — the frontend only displays); paid map tiles or API
  tokens; SSR / native-mobile.

## Requirements (EARS)
- **004-R1** — The dashboard SHALL render the NCS fields on a **Leaflet** map as **GeoJSON** polygons
  (from the 003 geometry endpoint), using free tiles with no API token.
- **004-R2** — WHEN a user selects a field (on the map or a field list), the system SHALL display that
  field's monthly **oil-equivalents history and its 24-month forecast** on a single **Plotly** chart,
  visually distinguishing history from forecast.
- **004-R3** — WHILE a field's forecast is displayed, the system SHALL show its **backtest MAPE** and a
  **credible / low-confidence** indicator matching 002's classification.
- **004-R4** — IF a selected field has no forecast (insufficient history), THEN the system SHALL show its
  history and clearly indicate **no credible forecast is available** — never a blank or fabricated curve.
- **004-R5** — The dashboard SHALL obtain all data from the **003 API** (typed to its OpenAPI contract),
  and SHALL be developable against a **mock** of that contract when 003 is unavailable.
- **004-R6** — The frontend SHALL have a **test setup with coverage measurement** established in this
  phase (tech-standards: frontend coverage tooling is fixed in 004).

## Data / interface contract
004 defines **no** data contract of its own — it consumes **003's OpenAPI** (fields, production,
`FieldForecast`, GeoJSON). Its TypeScript models are generated from / matched to that OpenAPI document.
Component structure, state management, and chart / map configuration are an **004 `plan.md`** decision.

## Acceptance criteria
- **R1** — the map renders field polygons from GeoJSON on free tiles; fields are selectable.
- **R2** — selecting a field shows one chart with its oe history and the 24-month forecast, history vs
  forecast visually distinct.
- **R3** — the displayed forecast carries its MAPE and a credible / low-confidence badge matching 002.
- **R4** — an insufficient-history field shows history plus an explicit "no credible forecast" state.
- **R5** — the app runs against the mock and against the real 003 API with no change beyond configuration.
- **R6** — the frontend test command runs with coverage reported.

## Open questions (defaults; flag to change)
- **History streams shown** — the chart shows **oil-equivalents** history (matching the forecast target);
  a toggle to show the other five streams is a *plan.md* option. *Default: oe only.*
- **Selection UX & layout** — map-driven selection (click a polygon) with an optional list / search; the
  map + chart layout is a *plan.md* detail.
- **Mock & integration / coverage tooling** — built against a typed mock of 003's OpenAPI, integrated with
  live 003 at the end (roadmap); the test runner + coverage tool (e.g. vitest) is a *plan.md* call.
