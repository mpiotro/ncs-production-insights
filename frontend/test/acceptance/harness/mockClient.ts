/**
 * A typed mock NcsApiClient for the acceptance suites (test-author–owned, principle 4).
 *
 * It satisfies the SAME `NcsApiClient` interface (src/api/contracts) the real httpClient and the
 * shipping dev mock satisfy — that is the whole point of R5: components take `NcsApiClient`, so a
 * test injects this mock with zero production-code change. Methods are `vi.fn()`-backed so a suite
 * can also assert *which* field was fetched when that is the user-visible behavior under test.
 *
 * Resolution rules mirror the contract's endpoint binding:
 *  - listFields / getFieldsGeoJson → the fixture collections.
 *  - getField / getProduction      → the matching fixture, else THROW (404 field_not_found analogue).
 *  - getForecast                   → a FieldForecast for forecastable fields; the typed
 *                                     ForecastNotAvailable VALUE for the insufficient-history field
 *                                     (never a thrown error, never an empty forecast) — R4.
 */
import { vi } from "vitest";

import type {
  Field,
  FieldForecast,
  FieldListResponse,
  FieldFeatureCollection,
  ForecastResult,
  NcsApiClient,
  ProductionHistoryResponse,
} from "../../../src/api/contracts";
import {
  FIELD_LIST,
  FIELDS,
  FIELDS_GEOJSON,
  FORECAST_CREDIBLE,
  FORECAST_LOW_CONFIDENCE,
  FORECAST_NOT_AVAILABLE_YME,
  FORECAST_NULL_GEOMETRY,
  NPDID_CREDIBLE,
  NPDID_LOW_CONFIDENCE,
  NPDID_NO_FORECAST,
  NPDID_NULL_GEOMETRY,
  PRODUCTION_CREDIBLE,
  PRODUCTION_LOW_CONFIDENCE,
  PRODUCTION_NO_FORECAST,
  PRODUCTION_NULL_GEOMETRY,
} from "./fixtures";

const PRODUCTION_BY_NPDID: Record<number, ProductionHistoryResponse> = {
  [NPDID_CREDIBLE]: PRODUCTION_CREDIBLE,
  [NPDID_LOW_CONFIDENCE]: PRODUCTION_LOW_CONFIDENCE,
  [NPDID_NO_FORECAST]: PRODUCTION_NO_FORECAST,
  [NPDID_NULL_GEOMETRY]: PRODUCTION_NULL_GEOMETRY,
};

const FORECAST_BY_NPDID: Record<number, ForecastResult> = {
  [NPDID_CREDIBLE]: FORECAST_CREDIBLE,
  [NPDID_LOW_CONFIDENCE]: FORECAST_LOW_CONFIDENCE,
  [NPDID_NULL_GEOMETRY]: FORECAST_NULL_GEOMETRY,
  [NPDID_NO_FORECAST]: FORECAST_NOT_AVAILABLE_YME,
};

/**
 * A mock client whose methods are spies (so `expect(client.getProduction).toHaveBeenCalledWith(…)`
 * works) while still being assignable to `NcsApiClient`.
 */
export type MockNcsApiClient = {
  [K in keyof NcsApiClient]: ReturnType<typeof vi.fn> & NcsApiClient[K];
};

export function createMockClient(): MockNcsApiClient {
  const client = {
    listFields: vi.fn(async (): Promise<FieldListResponse> => FIELD_LIST),

    getField: vi.fn(async (npdid: number): Promise<Field> => {
      const field = FIELDS.find((f) => f.field_npdid === npdid);
      if (!field) {
        throw new Error(`field_not_found: ${npdid}`);
      }
      return field;
    }),

    getProduction: vi.fn(async (npdid: number): Promise<ProductionHistoryResponse> => {
      const production = PRODUCTION_BY_NPDID[npdid];
      if (!production) {
        throw new Error(`field_not_found: ${npdid}`);
      }
      return production;
    }),

    getForecast: vi.fn(async (npdid: number): Promise<ForecastResult> => {
      const forecast = FORECAST_BY_NPDID[npdid];
      if (forecast === undefined) {
        throw new Error(`field_not_found: ${npdid}`);
      }
      return forecast;
    }),

    getFieldsGeoJson: vi.fn(async (): Promise<FieldFeatureCollection> => FIELDS_GEOJSON),
  };

  return client as unknown as MockNcsApiClient;
}
