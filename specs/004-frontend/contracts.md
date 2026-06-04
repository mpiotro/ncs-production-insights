# 004 frontend — TypeScript contract (the consumer seam)

**This is the 004 seam.** 004 defines **no data contract of its own** (spec §Data contract): it
*consumes 003's OpenAPI*. These TypeScript declarations are the **faithful mirror** of the frozen
001/002 models 003 serves, plus 003's transport envelopes — the boundary the component code, the
API client, and the test-author's mocks all build to. **Type declarations + client function
signatures only** — no implementation bodies, no React components (those live in `plan.md`'s tree).

Conventions (mirroring `src/ncs/api/responses.py`, `src/ncs/contracts.py`, `src/ncs/forecast/contracts.py`):
- **Snake_case preserved.** JSON keys are exactly the Python field names — `field_npdid`,
  `oil_equivalents`, `backtest_mape`, `history_months`. No camelCase remapping; the wire shape *is*
  the contract.
- **`| null` where Python is `| None`.** Optional streams (`oil`, `gas`, …) and `geometry_wkt` /
  `geometry` are `number | null` / `… | null`, **never** `?`-optional — a JSON `null` is a real,
  present value distinct from `0.0` (001-R6, 003-R3) and must round-trip as `null`, not vanish.
- **Closed string unions** for the Python `str`-enums (`ForecastMethod`, `ForecastTarget`,
  `ErrorCode`) — the same members, same wire values.
- **GeoJSON `geometry` stays loose.** 003 types it `dict[str, Any] | None`; we mirror that as
  `GeoJsonGeometry | null` (an open `{ type; coordinates }` object) and hand it straight to Leaflet,
  which parses RFC-7946 itself — we do not hand-write a coordinate grammar (matches 003's rationale).

---

## Frozen 001 models (served verbatim) — 004-R1, 004-R2

```ts
// Mirrors ncs.contracts.MonthlyProduction (001). One field-month row; null stream ≠ 0.0.
// oil_equivalents is the chart's history stream (004-R2); units live in 003's OpenAPI descriptions.
export interface MonthlyProduction {
  field_npdid: number;
  field_name: string;
  year: number;
  month: number;                       // 1–12
  oil: number | null;                  // million Sm³
  gas: number | null;                  // billion Sm³
  ngl: number | null;                  // million Sm³
  condensate: number | null;           // million Sm³
  oil_equivalents: number | null;      // million Sm³ — the forecast target & history stream (R2)
  produced_water: number | null;       // million Sm³
}

// Mirrors ncs.contracts.Field (001). Identity + descriptive attributes + WKT outline.
// 004 reads geometry from the GeoJSON endpoint (R1), not from this WKT string.
export interface Field {
  field_npdid: number;
  field_name: string;
  current_activity_status: string | null;
  hc_type: string | null;
  main_area: string | null;
  operator: string | null;
  discovery_year: number | null;
  geometry_wkt: string | null;         // POLYGON|MULTIPOLYGON WKT or null (raw; map uses GeoJSON instead)
}
```

## Frozen 002 forecast models (served verbatim) — 004-R2, 004-R3, 004-R4

```ts
// Mirrors ncs.forecast.contracts.ForecastMethod — which approach produced the forecast (R3 label).
export type ForecastMethod = "arps_decline" | "holt_damped";

// Mirrors ncs.forecast.contracts.ForecastTarget — fixed to oil-equivalents this cycle (R2).
export type ForecastTarget = "oil_equivalents";

// Mirrors ncs.forecast.contracts.ForecastPoint — one forecasted oe value for one calendar month.
export interface ForecastPoint {
  year: number;
  month: number;                       // 1–12
  value: number;                       // forecasted oil-equivalents · million Sm³ (≥ 0)
}

// Mirrors ncs.forecast.contracts.FieldForecast — the 24-month forecast + backtest credibility.
// On success the forecast endpoint returns THIS directly (R2/R3). Insufficient history is NOT an
// empty FieldForecast — it is the distinct ForecastNotAvailable outcome below (R4).
export interface FieldForecast {
  field_npdid: number;
  target: ForecastTarget;
  points: ForecastPoint[];             // exactly 24 (the horizon) — drawn as the forecast series (R2)
  method: ForecastMethod;              // selected approach (R3 badge detail)
  backtest_mape: number;               // held-out MAPE as a FRACTION — 0.12 ⇒ 12% (R3; ×100 to display)
  credible: boolean;                   // mape < 0.15, guard-adjusted — drives credible/low-confidence (R3)
  history_months: number;              // field's history length, ≥ 60
}
```

## 003 transport envelopes (new in 003) — 004-R1, 004-R2

```ts
// Mirrors ncs.api.responses.FieldListResponse (003-R2). GET /fields.
export interface FieldListResponse {
  count: number;                       // == fields.length
  fields: Field[];
}

// Mirrors ncs.api.responses.ProductionHistoryResponse (003-R3). GET /fields/{npdid}/production.
// production is ordered (year, month); nulls preserved (R2 history stream).
export interface ProductionHistoryResponse {
  field_npdid: number;
  count: number;
  production: MonthlyProduction[];
}
```

## GeoJSON FeatureCollection (new in 003) — 004-R1

```ts
// A loose RFC-7946 geometry — mirrors 003's dict[str, Any] | None. Handed straight to Leaflet.
export interface GeoJsonGeometry {
  type: string;                        // "Polygon" | "MultiPolygon" | …
  coordinates: unknown;                // nested-array coordinate payload; Leaflet parses it
}

// Mirrors ncs.api.responses.FieldProperties (003-R5). field_npdid is the map ⇄ chart join key (R1→R2).
export interface FieldProperties {
  field_npdid: number;
  field_name: string;
}

// Mirrors ncs.api.responses.FieldFeature (003-R5). geometry null ⇒ field has no outline (kept, not omitted).
export interface FieldFeature {
  type: "Feature";
  geometry: GeoJsonGeometry | null;
  properties: FieldProperties;
}

// Mirrors ncs.api.responses.FieldFeatureCollection (003-R5). GET /fields.geojson — the Leaflet source (R1).
export interface FieldFeatureCollection {
  type: "FeatureCollection";
  features: FieldFeature[];
}
```

## Typed error body (new in 003) — 004-R4

```ts
// Mirrors ncs.api.responses.ErrorCode. Lets 004 branch on the reason without parsing prose.
export type ErrorCode = "field_not_found" | "forecast_not_available";

// Mirrors ncs.api.responses.ErrorResponse — the body of every 4xx (both 404s tell apart via `code`).
export interface ErrorResponse {
  code: ErrorCode;
  detail: string;
}
```

---

## The R4 forecast outcome — a typed result, not a swallowed exception

R4 hinges on telling **"field exists but has < 60 months of history"** apart from a real forecast and
from "no such field". 003 makes this a **distinct HTTP outcome**: `GET /fields/{npdid}/forecast` →
**404 + `ErrorResponse{ code: "forecast_not_available" }`** for insufficient history (vs `404 +
field_not_found` for an unknown NPDID). So the client must **not** collapse that 404 into a thrown
error — it surfaces it as a value the UI can render as the explicit "no credible forecast" state.

We model the forecast call's result as a **discriminated union** (the only client method that needs
one — every other endpoint either succeeds or is a genuine fault):

```ts
// The two NORMAL outcomes of asking for a field's forecast (R4). A thrown error is reserved for
// genuine faults (network down, 5xx, malformed body) — NOT for the expected insufficient-history case.
export const FORECAST_NOT_AVAILABLE = "forecast_not_available" as const;

export interface ForecastNotAvailable {
  kind: typeof FORECAST_NOT_AVAILABLE; // discriminant — the UI branches on this for R4
  field_npdid: number;                 // echoed so the UI can label which field lacks a forecast
  detail: string;                      // human message from ErrorResponse.detail
}

// getForecast resolves to one of these; it never resolves "blank". (FieldForecast has no `kind`,
// so `"kind" in result` cleanly discriminates the two arms.)
export type ForecastResult = FieldForecast | ForecastNotAvailable;
```

> **Why a typed result, not an exception.** R4 forbids a blank or fabricated curve; the insufficient-
> history case is a *normal, expected* answer the dashboard renders deliberately, so it must reach the
> component as data. A `404 field_not_found` (unknown NPDID) is, by contrast, a programming/selection
> fault and *is* thrown — the user only ever selects a field that exists in the list/map (R1/R2).

---

## The API client interface — the single seam (004-R5)

One typed interface with **two implementations selected by configuration only** (real fetch vs mock).
The app/components depend on `NcsApiClient`, never on a concrete implementation, so switching between
the mock and live 003 is a config change, not a code change (R5).

```ts
export interface NcsApiClient {
  listFields(): Promise<FieldListResponse>;                 // GET /fields            (R1 list, R2 select)
  getField(npdid: number): Promise<Field>;                  // GET /fields/{npdid}    (detail)
  getProduction(npdid: number): Promise<ProductionHistoryResponse>; // GET …/production (R2 history)
  getForecast(npdid: number): Promise<ForecastResult>;      // GET …/forecast — R4 typed outcome (R2/R3/R4)
  getFieldsGeoJson(): Promise<FieldFeatureCollection>;       // GET /fields.geojson    (R1 map)
}
```

**Endpoint binding (verified against `src/ncs/api/routes/*`).** Paths are **un-prefixed** and joined
to `VITE_API_BASE_URL` by the real client:

| Method | HTTP request | Success type | Error → outcome |
|--------|--------------|--------------|-----------------|
| `listFields` | `GET {base}/fields` | `FieldListResponse` | throw on non-2xx |
| `getField` | `GET {base}/fields/{npdid}` | `Field` | 404 `field_not_found` → throw |
| `getProduction` | `GET {base}/fields/{npdid}/production` | `ProductionHistoryResponse` | 404 `field_not_found` → throw |
| `getForecast` | `GET {base}/fields/{npdid}/forecast` | `FieldForecast` | **404 `forecast_not_available` → `ForecastNotAvailable` value**; 404 `field_not_found` / other → throw |
| `getFieldsGeoJson` | `GET {base}/fields.geojson` | `FieldFeatureCollection` | throw on non-2xx |

Both implementations satisfy this interface identically; only `getForecast`'s 404 handling carries
the R4 branch. The mock returns in-memory fixtures (incl. at least one field with no forecast, to make
R4 testable); the real client `fetch`es `VITE_API_BASE_URL` and parses the same JSON shapes.

---

## Faithfulness to `/openapi.json` — generate, don't hand-curate

These TS types **must stay faithful to 003's `/openapi.json`** (the constitution: OpenAPI is the real
consumable contract — `contracts.md` of 003, R7). To keep them honest without hand-maintenance drift:

- **Recommendation: generate** the model types from a **committed snapshot** of 003's OpenAPI using
  **`openapi-typescript`** (schema-only, zero runtime). The developer commits
  `frontend/src/api/openapi.json` (captured from 003's `/openapi.json`) and a script
  `npm run gen:api` that regenerates `frontend/src/api/schema.gen.ts`; the **hand-written**
  `contracts.ts` in this file's shape re-exports/aliases those generated types into the friendly names
  above (`Field`, `FieldForecast`, …) plus the **client-only** types that are *not* in OpenAPI
  (`ForecastResult`, `ForecastNotAvailable`, `NcsApiClient`).
- A small **type-level conformance test** (`expectTypeOf`, see plan §Testing) asserts the friendly
  aliases are assignable to the generated schema types, so a contract drift fails the build — this is
  the developer's task, satisfying principle 9's "stay faithful" without a running 003 in CI.

> Generated-from-snapshot (not hand-typed) is the call because 003's OpenAPI is *machine-emitted from
> the real frozen models* — regenerating from a refreshed snapshot is a diff the reviewer reads,
> whereas hand-typed models silently rot. The snapshot keeps the frontend CI hermetic (no live 003).
