/**
 * Unit tests (developer-owned, principle 4) for the config-only client switch (004-R5).
 * Mirrors the acceptance angle but at the unit grain: "mock" yields a no-network client; any other
 * source yields the fetch-backed http client. The switch is the ONLY place the choice is made.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { selectClient } from "./selectClient";

const realFetch = globalThis.fetch;

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  globalThis.fetch = realFetch;
  vi.restoreAllMocks();
});

describe("selectClient — config drives the live↔mock switch (R5)", () => {
  it("apiSource 'mock' returns a client that serves data with NO network", async () => {
    const fetchSpy = vi.fn();
    globalThis.fetch = fetchSpy as unknown as typeof fetch;

    const client = selectClient({ apiSource: "mock", apiBaseUrl: "http://localhost:8003" });
    const fields = await client.listFields();

    expect(fields.fields.length).toBeGreaterThanOrEqual(1);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("a non-mock source returns the fetch-backed http client (hits the base URL)", async () => {
    const fetchSpy = vi.fn(
      async () =>
        new Response(JSON.stringify({ count: 0, fields: [] }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    globalThis.fetch = fetchSpy as unknown as typeof fetch;

    const client = selectClient({ apiSource: "http", apiBaseUrl: "http://localhost:9999" });
    await client.listFields();

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("http://localhost:9999");
  });

  it("'mock' and 'http' select DISTINCT implementations", () => {
    const mock = selectClient({ apiSource: "mock", apiBaseUrl: "http://localhost:8003" });
    const http = selectClient({ apiSource: "http", apiBaseUrl: "http://localhost:8003" });
    expect(mock).not.toBe(http);
  });

  it("the dev mock exposes all five NcsApiClient methods", () => {
    const client = selectClient({ apiSource: "mock", apiBaseUrl: "http://localhost:8003" });
    for (const method of [
      "listFields",
      "getField",
      "getProduction",
      "getForecast",
      "getFieldsGeoJson",
    ] as const) {
      expect(typeof client[method]).toBe("function");
    }
  });
});
