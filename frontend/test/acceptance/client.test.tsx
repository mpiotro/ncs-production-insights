/**
 * 004-R5 — The dashboard SHALL obtain all data from the 003 API (typed to its OpenAPI), and SHALL
 * be developable against a MOCK of that contract when 003 is unavailable, with no change beyond
 * configuration.
 *
 * Two black-box angles (principle 4):
 *  (a) Mockability by CONSTRUCTION — the SAME `App` component renders against an injected mock
 *      NcsApiClient with zero production-code change (that is what makes live↔mock a config swap).
 *  (b) `selectClient(config)` is the single switch: `apiSource: "mock"` yields the in-memory mock
 *      (no network), any other source yields the fetch-backed http client (hits the configured base
 *      URL). Same components either way — only the config differs.
 *
 * RED until the developer builds `src/api/selectClient`, `httpClient`, `mockClient`, `config`
 * (T8) and `src/App` (T10).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("react-leaflet", async () => (await import("./harness/viewMocks")).reactLeafletMock());
vi.mock("react-plotly.js", async () => (await import("./harness/viewMocks")).reactPlotlyMock());

import App from "../../src/App";
import { selectClient } from "../../src/api/selectClient";
import type { NcsApiClient } from "../../src/api/contracts";
import { createMockClient } from "./harness/mockClient";

const CLIENT_METHODS: (keyof NcsApiClient)[] = [
  "listFields",
  "getField",
  "getProduction",
  "getForecast",
  "getFieldsGeoJson",
];

function isNcsApiClient(value: unknown): value is NcsApiClient {
  return (
    typeof value === "object" &&
    value !== null &&
    CLIENT_METHODS.every((m) => typeof (value as Record<string, unknown>)[m] === "function")
  );
}

describe("004-R5 — data from 003, mockable by config alone", () => {
  describe("(a) mockability by construction — same component, injected mock", () => {
    it("004-R5: <App> renders the dashboard against an injected mock client (no code change)", async () => {
      const client = createMockClient();
      render(<App client={client} />);

      // The app drives the map+detail surface from the injected client alone.
      expect(await screen.findByTestId("map-container")).toBeInTheDocument();
      await screen.findAllByTestId("geojson-feature");
      expect(client.getFieldsGeoJson).toHaveBeenCalled();
    });
  });

  describe("(b) selectClient — the config-only live↔mock switch", () => {
    const realFetch = globalThis.fetch;

    beforeEach(() => {
      vi.restoreAllMocks();
    });

    afterEach(() => {
      globalThis.fetch = realFetch;
      vi.restoreAllMocks();
    });

    it("004-R5: returns a full NcsApiClient for apiSource:'mock'", () => {
      const client = selectClient({ apiSource: "mock", apiBaseUrl: "http://localhost:8000" });
      expect(isNcsApiClient(client)).toBe(true);
    });

    it("004-R5: returns a full NcsApiClient for a non-mock (http) source", () => {
      const client = selectClient({ apiSource: "http", apiBaseUrl: "http://localhost:8000" });
      expect(isNcsApiClient(client)).toBe(true);
    });

    it("004-R5: 'mock' and 'http' select DISTINCT implementations (config drives the switch)", () => {
      const mock = selectClient({ apiSource: "mock", apiBaseUrl: "http://localhost:8000" });
      const http = selectClient({ apiSource: "http", apiBaseUrl: "http://localhost:8000" });
      expect(mock).not.toBe(http);
    });

    it("004-R5: the 'mock' client serves data with NO network (fetch is never called)", async () => {
      const fetchSpy = vi.fn();
      globalThis.fetch = fetchSpy as unknown as typeof fetch;

      const client = selectClient({ apiSource: "mock", apiBaseUrl: "http://localhost:8000" });
      const fields = await client.listFields();

      expect(fields.fields.length).toBeGreaterThanOrEqual(1);
      expect(fetchSpy).not.toHaveBeenCalled();
    });

    it("004-R5: the 'http' client FETCHES the configured base URL (live transport)", async () => {
      const fetchSpy = vi.fn(
        async () =>
          new Response(JSON.stringify({ count: 0, fields: [] }), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
      );
      globalThis.fetch = fetchSpy as unknown as typeof fetch;

      const client = selectClient({ apiSource: "http", apiBaseUrl: "http://localhost:8000" });
      await client.listFields();

      expect(fetchSpy).toHaveBeenCalledTimes(1);
      const requestedUrl = String(fetchSpy.mock.calls[0]?.[0] ?? "");
      expect(requestedUrl).toContain("http://localhost:8000");
      expect(requestedUrl).toContain("/fields");
    });
  });
});
