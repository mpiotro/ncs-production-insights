/**
 * Unit tests (developer-owned, principle 4) for useFieldData (004-R2/R3/R4).
 * Verifies: parallel fetch resolves to {production, forecastResult}; the R4 ForecastNotAvailable
 * VALUE is threaded as data (not an error); a genuine fault surfaces as `error`; and a null npdid
 * yields the empty, not-loading state. Uses small in-test fakes (not the acceptance harness mock).
 */
import { describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

import { useFieldData } from "./useFieldData";
import { FORECAST_NOT_AVAILABLE } from "../api/contracts";
import type {
  FieldForecast,
  ForecastResult,
  NcsApiClient,
  ProductionHistoryResponse,
} from "../api/contracts";

const PRODUCTION: ProductionHistoryResponse = {
  field_npdid: 1,
  count: 1,
  production: [
    {
      field_npdid: 1,
      field_name: "F",
      year: 2021,
      month: 1,
      oil: 1,
      gas: null,
      ngl: null,
      condensate: null,
      oil_equivalents: 1,
      produced_water: null,
    },
  ],
};

const FORECAST: FieldForecast = {
  field_npdid: 1,
  target: "oil_equivalents",
  points: [],
  method: "arps_decline",
  backtest_mape: 0.1,
  credible: true,
  history_months: 120,
};

/** Build a stub client; only the two methods the hook calls need real behavior. */
function stubClient(overrides: Partial<NcsApiClient>): NcsApiClient {
  return {
    listFields: vi.fn(),
    getField: vi.fn(),
    getProduction: vi.fn(async () => PRODUCTION),
    getForecast: vi.fn(async () => FORECAST as ForecastResult),
    getFieldsGeoJson: vi.fn(),
    ...overrides,
  } as NcsApiClient;
}

describe("useFieldData", () => {
  it("returns the empty, not-loading state for a null npdid (no selection)", () => {
    const client = stubClient({});
    const { result } = renderHook(() => useFieldData(client, null));

    expect(result.current).toEqual({
      production: null,
      forecastResult: null,
      loading: false,
      error: null,
    });
    expect(client.getProduction).not.toHaveBeenCalled();
  });

  it("resolves production + a FieldForecast in parallel for a selected npdid", async () => {
    const client = stubClient({});
    const { result } = renderHook(() => useFieldData(client, 1));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.production).toEqual(PRODUCTION);
    expect(result.current.forecastResult).toEqual(FORECAST);
    expect(result.current.error).toBeNull();
    expect(client.getProduction).toHaveBeenCalledWith(1);
    expect(client.getForecast).toHaveBeenCalledWith(1);
  });

  it("threads a ForecastNotAvailable VALUE as data (not an error) — R4", async () => {
    const notAvailable: ForecastResult = {
      kind: FORECAST_NOT_AVAILABLE,
      field_npdid: 1,
      detail: "insufficient history",
    };
    const client = stubClient({ getForecast: vi.fn(async () => notAvailable) });
    const { result } = renderHook(() => useFieldData(client, 1));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeNull();
    expect(result.current.forecastResult).toEqual(notAvailable);
    // The production history is still present (R4: history shown even with no forecast).
    expect(result.current.production).toEqual(PRODUCTION);
  });

  it("surfaces a genuine fault as `error` (e.g. a thrown field_not_found / network down)", async () => {
    const client = stubClient({
      getProduction: vi.fn(async () => {
        throw new Error("field_not_found: 1");
      }),
    });
    const { result } = renderHook(() => useFieldData(client, 1));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.error?.message).toMatch(/field_not_found/);
    expect(result.current.production).toBeNull();
  });

  it("re-fetches when the npdid changes", async () => {
    const client = stubClient({});
    const { result, rerender } = renderHook(({ id }) => useFieldData(client, id), {
      initialProps: { id: 1 as number | null },
    });
    await waitFor(() => expect(result.current.loading).toBe(false));

    rerender({ id: 2 });
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(client.getProduction).toHaveBeenCalledWith(2);
  });
});
