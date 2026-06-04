/**
 * Unit tests (developer-owned, principle 4) for the real http client's R4-critical 404 handling
 * (004-R4, 004-R5). The load-bearing branch: a 404 `forecast_not_available` becomes a typed VALUE;
 * a 404 `field_not_found` (and other faults) THROW. Also covers the success path and the
 * malformed-body / network-error faults so the transport seam is white-box tested in isolation.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpClient } from "./httpClient";
import { FORECAST_NOT_AVAILABLE } from "./contracts";

const BASE = "http://localhost:8003";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const realFetch = globalThis.fetch;

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = realFetch;
  vi.restoreAllMocks();
});

describe("createHttpClient — getForecast 404 → outcome mapping (R4)", () => {
  it("maps 404 `forecast_not_available` to a typed ForecastNotAvailable VALUE (not a throw)", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        { code: "forecast_not_available", detail: "3 months; 60 required." },
        404,
      ),
    );
    const client = createHttpClient(BASE);

    const result = await client.getForecast(1003);

    // It resolves to a value, and that value is the R4 outcome with the echoed npdid + detail.
    expect("kind" in result).toBe(true);
    if ("kind" in result) {
      expect(result.kind).toBe(FORECAST_NOT_AVAILABLE);
      expect(result.field_npdid).toBe(1003);
      expect(result.detail).toBe("3 months; 60 required.");
    }
  });

  it("THROWS on a 404 `field_not_found` (a genuine fault, not an expected outcome)", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ code: "field_not_found", detail: "No such field." }, 404),
    );
    const client = createHttpClient(BASE);

    await expect(client.getForecast(9999)).rejects.toThrow();
  });

  it("THROWS on a non-404 error status (e.g. 500) even with a parseable body", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ code: "forecast_not_available", detail: "ignored" }, 500),
    );
    const client = createHttpClient(BASE);

    await expect(client.getForecast(1003)).rejects.toThrow();
  });

  it("returns the FieldForecast directly on a 2xx", async () => {
    const forecast = {
      field_npdid: 1001,
      target: "oil_equivalents",
      points: [],
      method: "arps_decline",
      backtest_mape: 0.08,
      credible: true,
      history_months: 120,
    };
    fetchMock.mockResolvedValueOnce(jsonResponse(forecast, 200));
    const client = createHttpClient(BASE);

    const result = await client.getForecast(1001);

    expect("kind" in result).toBe(false);
    expect((result as typeof forecast).backtest_mape).toBe(0.08);
  });

  it("hits the un-prefixed forecast path under the base URL", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ code: "forecast_not_available", detail: "x" }, 404),
    );
    const client = createHttpClient(BASE);

    await client.getForecast(1003);

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(`${BASE}/fields/1003/forecast`);
  });
});

describe("createHttpClient — success + fault paths on the plain endpoints", () => {
  it("listFields parses a 2xx body and hits /fields", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ count: 0, fields: [] }, 200));
    const client = createHttpClient(BASE);

    const result = await client.listFields();

    expect(result).toEqual({ count: 0, fields: [] });
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(`${BASE}/fields`);
  });

  it("getProduction THROWS on a 404 field_not_found", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ code: "field_not_found", detail: "No such field." }, 404),
    );
    const client = createHttpClient(BASE);

    await expect(client.getProduction(9999)).rejects.toThrow();
  });

  it("THROWS on a malformed (non-JSON) body even with a 2xx status", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("not json", { status: 200, headers: { "content-type": "text/plain" } }),
    );
    const client = createHttpClient(BASE);

    await expect(client.listFields()).rejects.toThrow(/Malformed JSON/i);
  });

  it("propagates a network failure as a throw", async () => {
    fetchMock.mockRejectedValueOnce(new Error("network down"));
    const client = createHttpClient(BASE);

    await expect(client.getFieldsGeoJson()).rejects.toThrow(/network down/i);
  });

  it("joins the base URL without doubling the slash when base has a trailing slash", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ count: 0, fields: [] }, 200));
    const client = createHttpClient("http://localhost:8003/");

    await client.listFields();

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("http://localhost:8003/fields");
  });

  it("getField parses a 2xx body and hits /fields/{npdid}", async () => {
    const field = { field_npdid: 1001, field_name: "SNORRE" };
    fetchMock.mockResolvedValueOnce(jsonResponse(field, 200));
    const client = createHttpClient(BASE);

    const result = await client.getField(1001);

    expect(result).toMatchObject({ field_npdid: 1001 });
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(`${BASE}/fields/1001`);
  });

  it("THROWS with the status text when an error body is not JSON (no typed detail to read)", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("upstream boom", { status: 503, statusText: "Service Unavailable" }),
    );
    const client = createHttpClient(BASE);

    await expect(client.listFields()).rejects.toThrow(/503/);
  });
});
