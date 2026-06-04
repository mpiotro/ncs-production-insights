/**
 * The shipping DEV-MODE mock `NcsApiClient` (004-R5) — serves `./fixtures` in-memory, NO network.
 *
 * Selected by `selectClient` when `VITE_API_SOURCE=mock`, so `npm run dev` and the hermetic CI run
 * against a realistic dataset without a live 003. It satisfies the SAME `NcsApiClient` interface as
 * the http client, so swapping mock <-> live is a config change, not a code change (R5).
 *
 * Resolution rules mirror the contract's endpoint binding:
 *  - listFields / getFieldsGeoJson → the fixture collections.
 *  - getField / getProduction      → the matching fixture, else THROW (404 field_not_found analogue).
 *  - getForecast                   → a FieldForecast for forecastable fields; the typed
 *                                     ForecastNotAvailable VALUE for the insufficient-history field
 *                                     (never thrown, never an empty forecast) — R4.
 *
 * Distinct from the test-author's acceptance mock (`test/acceptance/harness/mockClient.ts`,
 * principle 4): this one ships in the bundle for the running dashboard.
 */
import type {
  Field,
  FieldFeatureCollection,
  FieldListResponse,
  ForecastResult,
  NcsApiClient,
  ProductionHistoryResponse,
} from "./contracts";
import {
  DEV_FIELD_LIST,
  DEV_FIELDS,
  DEV_FIELDS_GEOJSON,
  DEV_FORECAST_CREDIBLE,
  DEV_FORECAST_LOW_CONFIDENCE,
  DEV_FORECAST_NOT_AVAILABLE,
  DEV_FORECAST_NULL_GEOMETRY,
  DEV_NPDID_CREDIBLE,
  DEV_NPDID_LOW_CONFIDENCE,
  DEV_NPDID_NO_FORECAST,
  DEV_NPDID_NULL_GEOMETRY,
  DEV_PRODUCTION_CREDIBLE,
  DEV_PRODUCTION_LOW_CONFIDENCE,
  DEV_PRODUCTION_NO_FORECAST,
  DEV_PRODUCTION_NULL_GEOMETRY,
} from "./fixtures";

const PRODUCTION_BY_NPDID: Record<number, ProductionHistoryResponse> = {
  [DEV_NPDID_CREDIBLE]: DEV_PRODUCTION_CREDIBLE,
  [DEV_NPDID_LOW_CONFIDENCE]: DEV_PRODUCTION_LOW_CONFIDENCE,
  [DEV_NPDID_NO_FORECAST]: DEV_PRODUCTION_NO_FORECAST,
  [DEV_NPDID_NULL_GEOMETRY]: DEV_PRODUCTION_NULL_GEOMETRY,
};

const FORECAST_BY_NPDID: Record<number, ForecastResult> = {
  [DEV_NPDID_CREDIBLE]: DEV_FORECAST_CREDIBLE,
  [DEV_NPDID_LOW_CONFIDENCE]: DEV_FORECAST_LOW_CONFIDENCE,
  [DEV_NPDID_NULL_GEOMETRY]: DEV_FORECAST_NULL_GEOMETRY,
  [DEV_NPDID_NO_FORECAST]: DEV_FORECAST_NOT_AVAILABLE,
};

/** Build the shipping dev mock client (the `Promise.resolve` keeps every method truly async). */
export function createMockClient(): NcsApiClient {
  return {
    listFields(): Promise<FieldListResponse> {
      return Promise.resolve(DEV_FIELD_LIST);
    },

    getField(npdid: number): Promise<Field> {
      const field = DEV_FIELDS.find((f) => f.field_npdid === npdid);
      if (!field) {
        return Promise.reject(new Error(`field_not_found: ${npdid}`));
      }
      return Promise.resolve(field);
    },

    getProduction(npdid: number): Promise<ProductionHistoryResponse> {
      const production = PRODUCTION_BY_NPDID[npdid];
      if (!production) {
        return Promise.reject(new Error(`field_not_found: ${npdid}`));
      }
      return Promise.resolve(production);
    },

    getForecast(npdid: number): Promise<ForecastResult> {
      const forecast = FORECAST_BY_NPDID[npdid];
      if (forecast === undefined) {
        return Promise.reject(new Error(`field_not_found: ${npdid}`));
      }
      return Promise.resolve(forecast);
    },

    getFieldsGeoJson(): Promise<FieldFeatureCollection> {
      return Promise.resolve(DEV_FIELDS_GEOJSON);
    },
  };
}
