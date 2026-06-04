/**
 * 004-R2 — WHEN a user selects a field, the system SHALL display that field's monthly
 * oil-equivalents history AND its 24-month forecast on a single Plotly chart, visually
 * distinguishing history from forecast.
 *
 * Black-box (principle 4): real components + injected mock NcsApiClient; `react-plotly.js` is
 * replaced by the shared stand-in (harness/viewMocks) that surfaces each trace's name, dash,
 * point-count and serialized y. We assert on that data, not on Plotly internals.
 *
 * RED until the developer builds the series builders (T9) + chart/panel/App wiring (T10).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("react-leaflet", async () => (await import("./harness/viewMocks")).reactLeafletMock());
vi.mock("react-plotly.js", async () => (await import("./harness/viewMocks")).reactPlotlyMock());

import App from "../../src/App";
import { createMockClient } from "./harness/mockClient";
import { NPDID_CREDIBLE } from "./harness/fixtures";

let client: ReturnType<typeof createMockClient>;

beforeEach(() => {
  client = createMockClient();
});

/** Select the credible field (SNORRE) on the map and return the rendered chart element. */
async function selectCredibleField(): Promise<HTMLElement> {
  render(<App client={client} />);
  const features = await screen.findAllByTestId("geojson-feature");
  const snorre = features.find(
    (el) => el.getAttribute("data-field-npdid") === String(NPDID_CREDIBLE),
  );
  await userEvent.click(snorre!);
  return await screen.findByTestId("plotly-chart");
}

describe("004-R2 — oe history + 24-month forecast on one Plotly chart, visually distinct", () => {
  it("004-R2: selecting a field shows exactly ONE chart", async () => {
    await selectCredibleField();
    expect(screen.getAllByTestId("plotly-chart")).toHaveLength(1);
  });

  it("004-R2: the chart carries a history trace AND a forecast trace (two traces)", async () => {
    const chart = await selectCredibleField();
    const traces = within(chart).getAllByTestId("plotly-trace");
    expect(traces).toHaveLength(2);
  });

  it("004-R2: the forecast trace has exactly 24 points (the horizon)", async () => {
    const chart = await selectCredibleField();
    const traces = within(chart).getAllByTestId("plotly-trace");

    const forecast = traces.find((t) => t.getAttribute("data-point-count") === "24");
    expect(forecast, "a 24-point forecast trace must be present").toBeDefined();
  });

  it("004-R2: history and forecast are VISUALLY DISTINCT (distinct names and dash styling)", async () => {
    const chart = await selectCredibleField();
    const traces = within(chart).getAllByTestId("plotly-trace");
    expect(traces).toHaveLength(2);

    const forecast = traces.find((t) => t.getAttribute("data-point-count") === "24")!;
    const history = traces.find((t) => t !== forecast)!;

    // Distinct trace names (the legend tells history from forecast).
    const fName = forecast.getAttribute("data-trace-name") ?? "";
    const hName = history.getAttribute("data-trace-name") ?? "";
    expect(fName).not.toBe("");
    expect(hName).not.toBe("");
    expect(fName).not.toBe(hName);

    // Distinct line styling: plan §3 specifies solid history vs dashed forecast — the forecast
    // line carries a dash style the history line does not.
    const fDash = forecast.getAttribute("data-trace-dash") ?? "";
    const hDash = history.getAttribute("data-trace-dash") ?? "";
    expect(fDash).not.toBe(hDash);
    expect(fDash).not.toBe("");
  });

  it("004-R2: the history trace reflects the oe stream and keeps a null month as a GAP (null, not 0.0)", async () => {
    const chart = await selectCredibleField();
    const traces = within(chart).getAllByTestId("plotly-trace");
    const forecast = traces.find((t) => t.getAttribute("data-point-count") === "24")!;
    const history = traces.find((t) => t !== forecast)!;

    // SNORRE's fixture history has 6 month rows, one of which (2021-03) has a null
    // oil_equivalents. The null is a real gap: it must survive as `null` and must NOT be
    // coerced to 0.0 (001-R6 / 003-R3). JSON.stringify renders a JS null as the literal "null".
    const yRaw = history.getAttribute("data-trace-y") ?? "[]";
    const y = JSON.parse(yRaw) as Array<number | null>;

    expect(y).toContain(null);
    expect(y).not.toContain(0);
    expect(y).not.toContain(0.0);
  });
});
