/**
 * 004-R3 — WHILE a field's forecast is displayed, the system SHALL show its backtest MAPE and a
 * credible / low-confidence indicator matching 002's classification (`credible` / `backtest_mape`).
 *
 * Black-box (principle 4). Two angles:
 *  (a) the `ForecastBadge` component directly (crisp, props-in / text-out), and
 *  (b) end-to-end through `App` (selecting a field surfaces the right badge), so the wiring counts.
 *
 * MAPE is a FRACTION on the wire (contracts): 0.08 ⇒ "8%", 0.22 ⇒ "22%" (×100 to display).
 *
 * RED until the developer builds `src/components/ForecastBadge` (T10) + App/panel wiring.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("react-leaflet", async () => (await import("./harness/viewMocks")).reactLeafletMock());
vi.mock("react-plotly.js", async () => (await import("./harness/viewMocks")).reactPlotlyMock());

import App from "../../src/App";
import { ForecastBadge } from "../../src/components/ForecastBadge";
import { createMockClient } from "./harness/mockClient";
import {
  FORECAST_CREDIBLE,
  FORECAST_LOW_CONFIDENCE,
  NPDID_CREDIBLE,
  NPDID_LOW_CONFIDENCE,
} from "./harness/fixtures";

let client: ReturnType<typeof createMockClient>;

beforeEach(() => {
  client = createMockClient();
});

async function selectFeature(npdid: number): Promise<void> {
  render(<App client={client} />);
  const features = await screen.findAllByTestId("geojson-feature");
  const target = features.find((el) => el.getAttribute("data-field-npdid") === String(npdid));
  await userEvent.click(target!);
}

describe("004-R3 — backtest MAPE % + credible / low-confidence indicator", () => {
  it("004-R3: a CREDIBLE forecast (mape 0.08) shows '8%' and a 'Credible' indicator", () => {
    render(<ForecastBadge forecast={FORECAST_CREDIBLE} />);

    // MAPE as a percentage: 0.08 × 100 = 8%.
    expect(screen.getByText(/8\s*%/)).toBeInTheDocument();
    // Credible indicator (matches `credible: true`).
    expect(screen.getByText(/credible/i)).toBeInTheDocument();
    expect(screen.queryByText(/low[\s-]?confidence/i)).not.toBeInTheDocument();
  });

  it("004-R3: a LOW-CONFIDENCE forecast (mape 0.22) shows '22%' and a 'Low confidence' indicator", () => {
    render(<ForecastBadge forecast={FORECAST_LOW_CONFIDENCE} />);

    // MAPE as a percentage: 0.22 × 100 = 22%.
    expect(screen.getByText(/22\s*%/)).toBeInTheDocument();
    // Low-confidence indicator (matches `credible: false`).
    expect(screen.getByText(/low[\s-]?confidence/i)).toBeInTheDocument();
  });

  it("004-R3 (end-to-end): selecting the credible field surfaces '8%' + 'Credible'", async () => {
    await selectFeature(NPDID_CREDIBLE);

    expect(await screen.findByText(/8\s*%/)).toBeInTheDocument();
    expect(screen.getByText(/credible/i)).toBeInTheDocument();
  });

  it("004-R3 (end-to-end): selecting the low-confidence field surfaces '22%' + 'Low confidence'", async () => {
    await selectFeature(NPDID_LOW_CONFIDENCE);

    expect(await screen.findByText(/22\s*%/)).toBeInTheDocument();
    expect(screen.getByText(/low[\s-]?confidence/i)).toBeInTheDocument();
  });
});
