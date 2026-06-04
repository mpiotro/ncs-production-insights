/**
 * 004-R4 — IF a selected field has no forecast (insufficient history), THEN the system SHALL show
 * its history AND clearly indicate "no credible forecast is available" — never a blank or
 * fabricated curve.
 *
 * Driven through the TYPED `ForecastNotAvailable` outcome the mock resolves for the
 * insufficient-history field (YME, npdid 1003) — a value, not a thrown error, not an empty
 * FieldForecast. The panel must branch on that value: render the history chart + an explicit
 * notice, and draw NO forecast trace.
 *
 * Black-box (principle 4). RED until the developer builds `src/components/NoForecastNotice` (T10),
 * the panel branching, and the `getForecast` → ForecastNotAvailable mapping path (T8).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("react-leaflet", async () => (await import("./harness/viewMocks")).reactLeafletMock());
vi.mock("react-plotly.js", async () => (await import("./harness/viewMocks")).reactPlotlyMock());

import App from "../../src/App";
import { NoForecastNotice } from "../../src/components/NoForecastNotice";
import { createMockClient } from "./harness/mockClient";
import { NPDID_NO_FORECAST } from "./harness/fixtures";

let client: ReturnType<typeof createMockClient>;

beforeEach(() => {
  client = createMockClient();
});

async function selectNoForecastField(): Promise<void> {
  render(<App client={client} />);
  const features = await screen.findAllByTestId("geojson-feature");
  const yme = features.find(
    (el) => el.getAttribute("data-field-npdid") === String(NPDID_NO_FORECAST),
  );
  await userEvent.click(yme!);
}

describe("004-R4 — insufficient-history field: history + explicit no-forecast notice, no fabricated curve", () => {
  it("004-R4: the standalone notice clearly states no credible forecast is available", () => {
    render(<NoForecastNotice />);
    expect(screen.getByText(/no credible forecast/i)).toBeInTheDocument();
  });

  it("004-R4: selecting the insufficient-history field still renders its history chart (never blank)", async () => {
    await selectNoForecastField();

    // The history chart is present — the panel is never blank for a real, selectable field.
    const chart = await screen.findByTestId("plotly-chart");
    expect(chart).toBeInTheDocument();

    // The forecast was resolved as the typed ForecastNotAvailable VALUE, not thrown.
    await vi.waitFor(() => expect(client.getForecast).toHaveBeenCalledWith(NPDID_NO_FORECAST));
  });

  it("004-R4: an explicit 'no credible forecast' notice is shown for the selected field", async () => {
    await selectNoForecastField();
    expect(await screen.findByText(/no credible forecast/i)).toBeInTheDocument();
  });

  it("004-R4: NO forecast trace is drawn — history only, never a fabricated 24-point curve", async () => {
    await selectNoForecastField();
    const chart = await screen.findByTestId("plotly-chart");

    const traces = within(chart).getAllByTestId("plotly-trace");
    // History only: a single trace, and crucially none with the 24-point forecast horizon.
    expect(traces).toHaveLength(1);
    expect(traces.some((t) => t.getAttribute("data-point-count") === "24")).toBe(false);

    // The lone trace is the field's real history (YME's fixture has 3 months), not a fabrication.
    expect(traces[0].getAttribute("data-point-count")).toBe("3");
  });
});
