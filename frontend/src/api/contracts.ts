/**
 * 004 consumer seam — the TypeScript contract (004-R5).
 *
 * 004 defines NO data contract of its own: it *consumes 003's OpenAPI*. These declarations
 * are the faithful mirror of the frozen 001/002 models 003 serves, plus 003's transport
 * envelopes — the boundary the components, the API client, and the test-author's mocks all
 * build to. See specs/004-frontend/contracts.md.
 *
 * Faithfulness strategy (contracts.md §"generate, don't hand-curate"): the closed string
 * unions and the loose GeoJSON geometry are DERIVED from the generated `schema.gen.ts`
 * (regenerated from a committed snapshot of 003's /openapi.json via `npm run gen:api`), so
 * a drift in those becomes a reviewable diff. The object shapes are restated here in the
 * friendly snake_case form contracts.md mandates — `| null` required (NOT `?`-optional),
 * because a JSON `null` is a real, present value distinct from 0.0 (001-R6, 003-R3) and must
 * round-trip as `null`, not vanish. The T9 conformance test (`expectTypeOf`) asserts these
 * friendly aliases stay assignable to the generated schema types.
 *
 * Type declarations + client signatures ONLY — no fetch logic, no React components (T8+).
 */

import type { components } from "./schema.gen";

type Schemas = components["schemas"];

// ---------------------------------------------------------------------------
// Frozen 001 models (served verbatim) — 004-R1, 004-R2
// ---------------------------------------------------------------------------

/**
 * Mirrors ncs.contracts.MonthlyProduction (001). One field-month row; a null stream is a real
 * gap, never 0.0. `oil_equivalents` is the chart's history stream (004-R2).
 */
export interface MonthlyProduction {
  field_npdid: number;
  field_name: string;
  year: number;
  month: number; // 1–12
  oil: number | null; // million Sm³
  gas: number | null; // billion Sm³
  ngl: number | null; // million Sm³
  condensate: number | null; // million Sm³
  oil_equivalents: number | null; // million Sm³ — forecast target & history stream (R2)
  produced_water: number | null; // million Sm³
}

/**
 * Mirrors ncs.contracts.Field (001). Identity + descriptive attributes + WKT outline.
 * 004 reads geometry from the GeoJSON endpoint (R1), not from this WKT string.
 */
export interface Field {
  field_npdid: number;
  field_name: string;
  current_activity_status: string | null;
  hc_type: string | null;
  main_area: string | null;
  operator: string | null;
  discovery_year: number | null;
  geometry_wkt: string | null; // POLYGON|MULTIPOLYGON WKT or null (raw; map uses GeoJSON)
}

// ---------------------------------------------------------------------------
// Frozen 002 forecast models (served verbatim) — 004-R2, 004-R3, 004-R4
// ---------------------------------------------------------------------------

/** Mirrors ncs.forecast.contracts.ForecastMethod — which approach produced the forecast (R3). */
export type ForecastMethod = Schemas["ForecastMethod"];

/** Mirrors ncs.forecast.contracts.ForecastTarget — fixed to oil-equivalents this cycle (R2). */
export type ForecastTarget = Schemas["ForecastTarget"];

/** Mirrors ncs.forecast.contracts.ForecastPoint — one forecasted oe value for one month. */
export interface ForecastPoint {
  year: number;
  month: number; // 1–12
  value: number; // forecasted oil-equivalents · million Sm³ (≥ 0)
}

/**
 * Mirrors ncs.forecast.contracts.FieldForecast — the 24-month forecast + backtest credibility.
 * On success the forecast endpoint returns THIS directly (R2/R3). Insufficient history is NOT
 * an empty FieldForecast — it is the distinct ForecastNotAvailable outcome below (R4).
 */
export interface FieldForecast {
  field_npdid: number;
  target: ForecastTarget;
  points: ForecastPoint[]; // exactly 24 (the horizon) — the forecast series (R2)
  method: ForecastMethod; // selected approach (R3 badge detail)
  backtest_mape: number; // held-out MAPE as a FRACTION — 0.12 ⇒ 12% (R3; ×100 to display)
  credible: boolean; // mape < 0.15, guard-adjusted — credible/low-confidence (R3)
  history_months: number; // field's history length, ≥ 60
}

// ---------------------------------------------------------------------------
// 003 transport envelopes — 004-R1, 004-R2
// ---------------------------------------------------------------------------

/** Mirrors ncs.api.responses.FieldListResponse (003-R2). GET /fields. */
export interface FieldListResponse {
  count: number; // == fields.length
  fields: Field[];
}

/**
 * Mirrors ncs.api.responses.ProductionHistoryResponse (003-R3). GET /fields/{npdid}/production.
 * `production` is ordered (year, month); nulls preserved (R2 history stream).
 */
export interface ProductionHistoryResponse {
  field_npdid: number;
  count: number;
  production: MonthlyProduction[];
}

// ---------------------------------------------------------------------------
// GeoJSON FeatureCollection — 004-R1
// ---------------------------------------------------------------------------

/**
 * A loose RFC-7946 geometry — mirrors 003's `dict[str, Any] | None`. Handed straight to
 * Leaflet, which parses the coordinate grammar itself; we do not hand-write one.
 */
export interface GeoJsonGeometry {
  type: string; // "Polygon" | "MultiPolygon" | …
  coordinates: unknown; // nested-array coordinate payload; Leaflet parses it
}

/** Mirrors ncs.api.responses.FieldProperties (003-R5). field_npdid is the map ⇄ chart join key. */
export interface FieldProperties {
  field_npdid: number;
  field_name: string;
}

/** Mirrors ncs.api.responses.FieldFeature (003-R5). geometry null ⇒ no outline (kept, not omitted). */
export interface FieldFeature {
  type: "Feature";
  geometry: GeoJsonGeometry | null;
  properties: FieldProperties;
}

/** Mirrors ncs.api.responses.FieldFeatureCollection (003-R5). GET /fields.geojson — Leaflet source. */
export interface FieldFeatureCollection {
  type: "FeatureCollection";
  features: FieldFeature[];
}

// ---------------------------------------------------------------------------
// Typed error body — 004-R4
// ---------------------------------------------------------------------------

/** Mirrors ncs.api.responses.ErrorCode. Lets 004 branch on the reason without parsing prose. */
export type ErrorCode = Schemas["ErrorCode"];

/** Mirrors ncs.api.responses.ErrorResponse — the body of every 4xx (both 404s tell apart via `code`). */
export interface ErrorResponse {
  code: ErrorCode;
  detail: string;
}

// ---------------------------------------------------------------------------
// The R4 forecast outcome — a typed result, not a swallowed exception (004-R4)
// ---------------------------------------------------------------------------

/**
 * The two NORMAL outcomes of asking for a field's forecast (R4). A thrown error is reserved
 * for genuine faults (network down, 5xx, malformed body) — NOT for the expected
 * insufficient-history case. These client-only types are NOT in 003's OpenAPI.
 */
export const FORECAST_NOT_AVAILABLE = "forecast_not_available" as const;

export interface ForecastNotAvailable {
  kind: typeof FORECAST_NOT_AVAILABLE; // discriminant — the UI branches on this for R4
  field_npdid: number; // echoed so the UI can label which field lacks a forecast
  detail: string; // human message from ErrorResponse.detail
}

/**
 * getForecast resolves to one of these; it never resolves "blank". (FieldForecast has no
 * `kind`, so `"kind" in result` cleanly discriminates the two arms.)
 */
export type ForecastResult = FieldForecast | ForecastNotAvailable;

// ---------------------------------------------------------------------------
// The API client interface — the single seam (004-R5)
// ---------------------------------------------------------------------------

/**
 * One typed interface with TWO implementations selected by configuration only (real fetch vs
 * mock). The app/components depend on `NcsApiClient`, never on a concrete implementation, so
 * switching between the mock and live 003 is a config change, not a code change (R5).
 * Endpoint binding (verified against 003's routes) lives in contracts.md; only `getForecast`'s
 * 404 handling carries the R4 branch (forecast_not_available → ForecastNotAvailable value).
 */
export interface NcsApiClient {
  listFields(): Promise<FieldListResponse>; // GET /fields            (R1 list, R2 select)
  getField(npdid: number): Promise<Field>; // GET /fields/{npdid}    (detail)
  getProduction(npdid: number): Promise<ProductionHistoryResponse>; // GET …/production (R2)
  getForecast(npdid: number): Promise<ForecastResult>; // GET …/forecast — R4 typed outcome
  getFieldsGeoJson(): Promise<FieldFeatureCollection>; // GET /fields.geojson    (R1 map)
}
