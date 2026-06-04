/**
 * Acceptance fixtures (test-author–owned, principle 4) — the in-memory data the mock
 * NcsApiClient serves. Authored against the frozen contracts in src/api/contracts.ts, mirroring
 * how 001's test-author authored the SODIR fixtures. The *shipping* dev-mode mock
 * (src/api/mockClient.ts / fixtures.ts) is the developer's; these are separate and only feed the
 * black-box R1–R6 suites.
 *
 * Field → requirement coverage (one representative per outcome):
 *  - SNORRE   (npdid 1001) — CREDIBLE forecast: 24 points, backtest_mape 0.08 (< 0.15),
 *                            credible:true. Has geometry. Production carries a `null` oe month
 *                            (a gap ≠ 0.0) and is intentionally returned OUT OF ORDER so an
 *                            ordering assertion is meaningful. Exercises R2 (history+forecast,
 *                            null gap), R3 (Credible).
 *  - TROLL    (npdid 1002) — LOW-CONFIDENCE forecast: 24 points, backtest_mape 0.22 (≥ 0.15),
 *                            credible:false. Has geometry. Exercises R3 (Low confidence).
 *  - YME      (npdid 1003) — INSUFFICIENT HISTORY: getForecast resolves to a typed
 *                            ForecastNotAvailable value (NOT a thrown error, NOT an empty
 *                            forecast). Has geometry + a short history. Exercises R4.
 *  - NULLGEOM (npdid 1004) — NULL geometry (no map polygon) but a credible forecast, so it is
 *                            reachable only via the field-list fallback. Exercises R1's
 *                            list-selectability-of-a-null-geometry-field.
 */
import type {
  Field,
  FieldFeatureCollection,
  FieldForecast,
  FieldListResponse,
  ForecastNotAvailable,
  ForecastPoint,
  MonthlyProduction,
  ProductionHistoryResponse,
} from "../../../src/api/contracts";
import { FORECAST_NOT_AVAILABLE } from "../../../src/api/contracts";

export const NPDID_CREDIBLE = 1001;
export const NPDID_LOW_CONFIDENCE = 1002;
export const NPDID_NO_FORECAST = 1003;
export const NPDID_NULL_GEOMETRY = 1004;

const A_POLYGON = {
  type: "Polygon",
  coordinates: [
    [
      [2.0, 61.0],
      [2.1, 61.0],
      [2.1, 61.1],
      [2.0, 61.1],
      [2.0, 61.0],
    ],
  ],
};

const B_POLYGON = {
  type: "Polygon",
  coordinates: [
    [
      [3.6, 60.6],
      [3.7, 60.6],
      [3.7, 60.7],
      [3.6, 60.7],
      [3.6, 60.6],
    ],
  ],
};

const C_POLYGON = {
  type: "Polygon",
  coordinates: [
    [
      [4.0, 57.8],
      [4.1, 57.8],
      [4.1, 57.9],
      [4.0, 57.9],
      [4.0, 57.8],
    ],
  ],
};

export const FIELDS: Field[] = [
  {
    field_npdid: NPDID_CREDIBLE,
    field_name: "SNORRE",
    current_activity_status: "Producing",
    hc_type: "OIL",
    main_area: "North sea",
    operator: "Equinor Energy AS",
    discovery_year: 1979,
    geometry_wkt: "POLYGON ((2.0 61.0, 2.1 61.0, 2.1 61.1, 2.0 61.1, 2.0 61.0))",
  },
  {
    field_npdid: NPDID_LOW_CONFIDENCE,
    field_name: "TROLL",
    current_activity_status: "Producing",
    hc_type: "OIL/GAS",
    main_area: "North sea",
    operator: "Equinor Energy AS",
    discovery_year: 1979,
    geometry_wkt: "POLYGON ((3.6 60.6, 3.7 60.6, 3.7 60.7, 3.6 60.7, 3.6 60.6))",
  },
  {
    field_npdid: NPDID_NO_FORECAST,
    field_name: "YME",
    current_activity_status: "Producing",
    hc_type: "OIL",
    main_area: "North sea",
    operator: "Repsol Norge AS",
    discovery_year: 1987,
    geometry_wkt: "POLYGON ((4.0 57.8, 4.1 57.8, 4.1 57.9, 4.0 57.9, 4.0 57.8))",
  },
  {
    field_npdid: NPDID_NULL_GEOMETRY,
    field_name: "NULLGEOM",
    current_activity_status: "Producing",
    hc_type: "GAS",
    main_area: "Norwegian sea",
    operator: "Aker BP ASA",
    discovery_year: 1995,
    geometry_wkt: null,
  },
];

export const FIELD_LIST: FieldListResponse = {
  count: FIELDS.length,
  fields: FIELDS,
};

/**
 * GeoJSON FeatureCollection (the Leaflet source, R1). Every field is a feature — the
 * null-geometry field is KEPT with `geometry: null` (contracts: "kept, not omitted"), so it has
 * no polygon to click and must be reachable via the list fallback instead.
 */
export const FIELDS_GEOJSON: FieldFeatureCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      geometry: A_POLYGON,
      properties: { field_npdid: NPDID_CREDIBLE, field_name: "SNORRE" },
    },
    {
      type: "Feature",
      geometry: B_POLYGON,
      properties: { field_npdid: NPDID_LOW_CONFIDENCE, field_name: "TROLL" },
    },
    {
      type: "Feature",
      geometry: C_POLYGON,
      properties: { field_npdid: NPDID_NO_FORECAST, field_name: "YME" },
    },
    {
      type: "Feature",
      geometry: null,
      properties: { field_npdid: NPDID_NULL_GEOMETRY, field_name: "NULLGEOM" },
    },
  ],
};

/** How many features carry a real (non-null) geometry — the count that can be clicked on a map. */
export const FEATURES_WITH_GEOMETRY = FIELDS_GEOJSON.features.filter(
  (f) => f.geometry !== null,
).length;

function productionRow(
  npdid: number,
  name: string,
  year: number,
  month: number,
  oe: number | null,
): MonthlyProduction {
  return {
    field_npdid: npdid,
    field_name: name,
    year,
    month,
    oil: oe,
    gas: oe === null ? null : oe * 0.5,
    ngl: 0.0,
    condensate: 0.0,
    oil_equivalents: oe,
    produced_water: oe === null ? null : oe * 2,
  };
}

/**
 * SNORRE history — deliberately UNORDERED and containing a `null` oil_equivalents month
 * (2021-03). The null is a real GAP, never 0.0 (001-R6 / 003-R3); a chart-data assertion checks
 * the gap survives as a plotted slot rather than collapsing to zero.
 */
export const PRODUCTION_CREDIBLE: ProductionHistoryResponse = {
  field_npdid: NPDID_CREDIBLE,
  count: 6,
  production: [
    productionRow(NPDID_CREDIBLE, "SNORRE", 2021, 2, 9.4),
    productionRow(NPDID_CREDIBLE, "SNORRE", 2020, 12, 10.1),
    productionRow(NPDID_CREDIBLE, "SNORRE", 2021, 4, 9.0),
    productionRow(NPDID_CREDIBLE, "SNORRE", 2021, 1, 9.8),
    // The gap: a present row whose oil_equivalents is null (must NOT become 0.0).
    productionRow(NPDID_CREDIBLE, "SNORRE", 2021, 3, null),
    productionRow(NPDID_CREDIBLE, "SNORRE", 2020, 11, 10.4),
  ],
};

export const PRODUCTION_LOW_CONFIDENCE: ProductionHistoryResponse = {
  field_npdid: NPDID_LOW_CONFIDENCE,
  count: 4,
  production: [
    productionRow(NPDID_LOW_CONFIDENCE, "TROLL", 2021, 1, 41.0),
    productionRow(NPDID_LOW_CONFIDENCE, "TROLL", 2021, 2, 40.2),
    productionRow(NPDID_LOW_CONFIDENCE, "TROLL", 2021, 3, 39.8),
    productionRow(NPDID_LOW_CONFIDENCE, "TROLL", 2021, 4, 39.1),
  ],
};

/** YME still HAS a production history (R4: history is shown even with no forecast). */
export const PRODUCTION_NO_FORECAST: ProductionHistoryResponse = {
  field_npdid: NPDID_NO_FORECAST,
  count: 3,
  production: [
    productionRow(NPDID_NO_FORECAST, "YME", 2022, 10, 1.2),
    productionRow(NPDID_NO_FORECAST, "YME", 2022, 11, 1.1),
    productionRow(NPDID_NO_FORECAST, "YME", 2022, 12, 1.0),
  ],
};

export const PRODUCTION_NULL_GEOMETRY: ProductionHistoryResponse = {
  field_npdid: NPDID_NULL_GEOMETRY,
  count: 3,
  production: [
    productionRow(NPDID_NULL_GEOMETRY, "NULLGEOM", 2021, 1, 5.5),
    productionRow(NPDID_NULL_GEOMETRY, "NULLGEOM", 2021, 2, 5.4),
    productionRow(NPDID_NULL_GEOMETRY, "NULLGEOM", 2021, 3, 5.3),
  ],
};

/** Build the canonical 24 forecast points (the horizon) starting the month after the history. */
function buildForecastPoints(startYear: number, startMonth: number, base: number): ForecastPoint[] {
  const points: ForecastPoint[] = [];
  let year = startYear;
  let month = startMonth;
  for (let i = 0; i < 24; i += 1) {
    points.push({ year, month, value: Math.max(0, base - i * 0.1) });
    month += 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
  }
  return points;
}

/** SNORRE — credible: mape 0.08 (< 0.15) ⇒ credible:true; exactly 24 points. */
export const FORECAST_CREDIBLE: FieldForecast = {
  field_npdid: NPDID_CREDIBLE,
  target: "oil_equivalents",
  points: buildForecastPoints(2021, 5, 8.9),
  method: "arps_decline",
  backtest_mape: 0.08,
  credible: true,
  history_months: 120,
};

/** TROLL — low confidence: mape 0.22 (≥ 0.15) ⇒ credible:false; exactly 24 points. */
export const FORECAST_LOW_CONFIDENCE: FieldForecast = {
  field_npdid: NPDID_LOW_CONFIDENCE,
  target: "oil_equivalents",
  points: buildForecastPoints(2021, 5, 39.0),
  method: "holt_damped",
  backtest_mape: 0.22,
  credible: false,
  history_months: 96,
};

/** NULLGEOM — credible forecast so its detail panel renders once reached via the list. */
export const FORECAST_NULL_GEOMETRY: FieldForecast = {
  field_npdid: NPDID_NULL_GEOMETRY,
  target: "oil_equivalents",
  points: buildForecastPoints(2021, 4, 5.2),
  method: "arps_decline",
  backtest_mape: 0.11,
  credible: true,
  history_months: 84,
};

/** YME — the typed insufficient-history outcome (R4): a value, not a thrown error. */
export const FORECAST_NOT_AVAILABLE_YME: ForecastNotAvailable = {
  kind: FORECAST_NOT_AVAILABLE,
  field_npdid: NPDID_NO_FORECAST,
  detail: "Field 1003 has 3 months of history; 60 are required to forecast.",
};
