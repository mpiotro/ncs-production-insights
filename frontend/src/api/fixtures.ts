/**
 * Shipping DEV-MODE mock data (004-R5) — the in-memory dataset `mockClient` serves when the app
 * runs with `VITE_API_SOURCE=mock` (so `npm run dev` works with NO live 003 and no network).
 *
 * This is the DEVELOPER's fixture set — deliberately SEPARATE from the test-author's acceptance
 * fixtures (`test/acceptance/harness/fixtures.ts`, principle 4). It exists to make the running
 * dashboard demonstrable; it must exercise every UI branch so the demo shows them all:
 *  - JOHAN SVERDRUP (npdid 2001) — CREDIBLE forecast (mape 0.07): exercises R2 + R3 "Credible".
 *  - GULLFAKS       (npdid 2002) — LOW-CONFIDENCE forecast (mape 0.19): exercises R3 "Low confidence".
 *  - GINA KROG      (npdid 2003) — INSUFFICIENT HISTORY: getForecast resolves to a typed
 *                                  ForecastNotAvailable value (R4). Short history, still charted.
 *  - VOLVE          (npdid 2004) — NULL geometry (no map polygon): reachable only via the list
 *                                  fallback (R1's list-selectability of a geometry-less field).
 *
 * The shapes are the friendly contracts in `./contracts` — identical to what the http client parses,
 * so swapping mock <-> live is config only (R5). A null oil_equivalents month is kept as a real gap.
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
} from "./contracts";
import { FORECAST_NOT_AVAILABLE } from "./contracts";

export const DEV_NPDID_CREDIBLE = 2001;
export const DEV_NPDID_LOW_CONFIDENCE = 2002;
export const DEV_NPDID_NO_FORECAST = 2003;
export const DEV_NPDID_NULL_GEOMETRY = 2004;

const SVERDRUP_POLYGON = {
  type: "Polygon",
  coordinates: [
    [
      [2.6, 58.8],
      [2.9, 58.8],
      [2.9, 59.0],
      [2.6, 59.0],
      [2.6, 58.8],
    ],
  ],
};

const GULLFAKS_POLYGON = {
  type: "Polygon",
  coordinates: [
    [
      [2.1, 61.1],
      [2.3, 61.1],
      [2.3, 61.3],
      [2.1, 61.3],
      [2.1, 61.1],
    ],
  ],
};

const GINA_KROG_POLYGON = {
  type: "Polygon",
  coordinates: [
    [
      [1.8, 58.1],
      [2.0, 58.1],
      [2.0, 58.3],
      [1.8, 58.3],
      [1.8, 58.1],
    ],
  ],
};

export const DEV_FIELDS: Field[] = [
  {
    field_npdid: DEV_NPDID_CREDIBLE,
    field_name: "JOHAN SVERDRUP",
    current_activity_status: "Producing",
    hc_type: "OIL",
    main_area: "North sea",
    operator: "Equinor Energy AS",
    discovery_year: 2010,
    geometry_wkt: "POLYGON ((2.6 58.8, 2.9 58.8, 2.9 59.0, 2.6 59.0, 2.6 58.8))",
  },
  {
    field_npdid: DEV_NPDID_LOW_CONFIDENCE,
    field_name: "GULLFAKS",
    current_activity_status: "Producing",
    hc_type: "OIL",
    main_area: "North sea",
    operator: "Equinor Energy AS",
    discovery_year: 1978,
    geometry_wkt: "POLYGON ((2.1 61.1, 2.3 61.1, 2.3 61.3, 2.1 61.3, 2.1 61.1))",
  },
  {
    field_npdid: DEV_NPDID_NO_FORECAST,
    field_name: "GINA KROG",
    current_activity_status: "Producing",
    hc_type: "OIL/GAS",
    main_area: "North sea",
    operator: "Equinor Energy AS",
    discovery_year: 1974,
    geometry_wkt: "POLYGON ((1.8 58.1, 2.0 58.1, 2.0 58.3, 1.8 58.3, 1.8 58.1))",
  },
  {
    field_npdid: DEV_NPDID_NULL_GEOMETRY,
    field_name: "VOLVE",
    current_activity_status: "Shut down",
    hc_type: "OIL",
    main_area: "North sea",
    operator: "Equinor Energy AS",
    discovery_year: 1993,
    geometry_wkt: null,
  },
];

export const DEV_FIELD_LIST: FieldListResponse = {
  count: DEV_FIELDS.length,
  fields: DEV_FIELDS,
};

/** GeoJSON source for the map. The null-geometry field is KEPT with `geometry: null` (R1/R5). */
export const DEV_FIELDS_GEOJSON: FieldFeatureCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      geometry: SVERDRUP_POLYGON,
      properties: { field_npdid: DEV_NPDID_CREDIBLE, field_name: "JOHAN SVERDRUP" },
    },
    {
      type: "Feature",
      geometry: GULLFAKS_POLYGON,
      properties: { field_npdid: DEV_NPDID_LOW_CONFIDENCE, field_name: "GULLFAKS" },
    },
    {
      type: "Feature",
      geometry: GINA_KROG_POLYGON,
      properties: { field_npdid: DEV_NPDID_NO_FORECAST, field_name: "GINA KROG" },
    },
    {
      type: "Feature",
      geometry: null,
      properties: { field_npdid: DEV_NPDID_NULL_GEOMETRY, field_name: "VOLVE" },
    },
  ],
};

function devProductionRow(
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
    ngl: oe === null ? null : oe * 0.05,
    condensate: 0.0,
    oil_equivalents: oe,
    produced_water: oe === null ? null : oe * 1.5,
  };
}

/** Build a smoothly declining monthly history for `months` months from a start (year, month). */
function buildHistory(
  npdid: number,
  name: string,
  startYear: number,
  startMonth: number,
  months: number,
  base: number,
  decay: number,
  nullAt?: number,
): MonthlyProduction[] {
  const rows: MonthlyProduction[] = [];
  let year = startYear;
  let month = startMonth;
  for (let i = 0; i < months; i += 1) {
    const oe = i === nullAt ? null : Math.max(0, base - i * decay);
    rows.push(devProductionRow(npdid, name, year, month, oe));
    month += 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
  }
  return rows;
}

/** JOHAN SVERDRUP — long history with one null gap month (index 6) to show the gap rule (R2). */
export const DEV_PRODUCTION_CREDIBLE: ProductionHistoryResponse = (() => {
  const production = buildHistory(
    DEV_NPDID_CREDIBLE,
    "JOHAN SVERDRUP",
    2019,
    10,
    36,
    62.0,
    0.4,
    6,
  );
  return { field_npdid: DEV_NPDID_CREDIBLE, count: production.length, production };
})();

export const DEV_PRODUCTION_LOW_CONFIDENCE: ProductionHistoryResponse = (() => {
  const production = buildHistory(DEV_NPDID_LOW_CONFIDENCE, "GULLFAKS", 2019, 1, 36, 18.0, 0.2);
  return { field_npdid: DEV_NPDID_LOW_CONFIDENCE, count: production.length, production };
})();

/** GINA KROG — only a few months of history (R4: history still shown, no forecast). */
export const DEV_PRODUCTION_NO_FORECAST: ProductionHistoryResponse = (() => {
  const production = buildHistory(DEV_NPDID_NO_FORECAST, "GINA KROG", 2023, 9, 5, 4.5, 0.1);
  return { field_npdid: DEV_NPDID_NO_FORECAST, count: production.length, production };
})();

export const DEV_PRODUCTION_NULL_GEOMETRY: ProductionHistoryResponse = (() => {
  const production = buildHistory(DEV_NPDID_NULL_GEOMETRY, "VOLVE", 2018, 1, 12, 8.0, 0.3);
  return { field_npdid: DEV_NPDID_NULL_GEOMETRY, count: production.length, production };
})();

/** The canonical 24 forecast points (the horizon) starting the month after the history. */
function buildForecastPoints(startYear: number, startMonth: number, base: number): ForecastPoint[] {
  const points: ForecastPoint[] = [];
  let year = startYear;
  let month = startMonth;
  for (let i = 0; i < 24; i += 1) {
    points.push({ year, month, value: Math.max(0, base - i * 0.3) });
    month += 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
  }
  return points;
}

/** JOHAN SVERDRUP — credible: mape 0.07 (< 0.15) ⇒ credible:true; exactly 24 points. */
export const DEV_FORECAST_CREDIBLE: FieldForecast = {
  field_npdid: DEV_NPDID_CREDIBLE,
  target: "oil_equivalents",
  points: buildForecastPoints(2022, 10, 47.0),
  method: "arps_decline",
  backtest_mape: 0.07,
  credible: true,
  history_months: 120,
};

/** GULLFAKS — low confidence: mape 0.19 (≥ 0.15) ⇒ credible:false; exactly 24 points. */
export const DEV_FORECAST_LOW_CONFIDENCE: FieldForecast = {
  field_npdid: DEV_NPDID_LOW_CONFIDENCE,
  target: "oil_equivalents",
  points: buildForecastPoints(2022, 1, 11.0),
  method: "holt_damped",
  backtest_mape: 0.19,
  credible: false,
  history_months: 180,
};

/** VOLVE — credible forecast so its detail panel renders once reached via the list (R1 fallback). */
export const DEV_FORECAST_NULL_GEOMETRY: FieldForecast = {
  field_npdid: DEV_NPDID_NULL_GEOMETRY,
  target: "oil_equivalents",
  points: buildForecastPoints(2019, 1, 4.5),
  method: "arps_decline",
  backtest_mape: 0.12,
  credible: true,
  history_months: 96,
};

/** GINA KROG — the typed insufficient-history outcome (R4): a value, not a thrown error. */
export const DEV_FORECAST_NOT_AVAILABLE: ForecastNotAvailable = {
  kind: FORECAST_NOT_AVAILABLE,
  field_npdid: DEV_NPDID_NO_FORECAST,
  detail: "Field 2003 has 5 months of history; 60 are required to forecast.",
};
