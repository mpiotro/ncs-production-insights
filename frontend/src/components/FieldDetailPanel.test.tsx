/**
 * Unit tests (developer-owned, principle 4) for FieldDetailPanel's data-branching (004-R2/R3/R4).
 * The panel must branch on the typed forecast OUTCOME, not on a caught exception:
 *  - a real FieldForecast → chart + ForecastBadge, no notice;
 *  - ForecastNotAvailable → chart (history only) + NoForecastNotice, no badge, NO forecast trace;
 *  - no selection         → a prompt, no chart.
 * Plotly is mocked inline (this is the developer's own mock, separate from the acceptance harness).
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

// Inline, self-contained Plotly stand-in surfacing trace count + per-trace point count.
vi.mock("react-plotly.js", () => ({
  default: ({ data = [] }: { data?: Array<{ y?: unknown[] }> }) => (
    <div data-testid="plotly-chart" data-trace-count={String(data.length)}>
      {data.map((trace, i) => (
        <div key={i} data-testid="plotly-trace" data-point-count={String((trace.y ?? []).length)} />
      ))}
    </div>
  ),
}));

import { FieldDetailPanel } from "./FieldDetailPanel";
import { FORECAST_NOT_AVAILABLE } from "../api/contracts";
import type {
  Field,
  FieldForecast,
  ForecastResult,
  NcsApiClient,
  ProductionHistoryResponse,
} from "../api/contracts";

const FIELD: Field = {
  field_npdid: 7,
  field_name: "TESTFIELD",
  current_activity_status: "Producing",
  hc_type: "OIL",
  main_area: "North sea",
  operator: "Operator AS",
  discovery_year: 1990,
  geometry_wkt: "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
};

const PRODUCTION: ProductionHistoryResponse = {
  field_npdid: 7,
  count: 2,
  production: [
    {
      field_npdid: 7,
      field_name: "TESTFIELD",
      year: 2021,
      month: 1,
      oil: 5,
      gas: null,
      ngl: null,
      condensate: null,
      oil_equivalents: 5,
      produced_water: null,
    },
    {
      field_npdid: 7,
      field_name: "TESTFIELD",
      year: 2021,
      month: 2,
      oil: 4,
      gas: null,
      ngl: null,
      condensate: null,
      oil_equivalents: 4,
      produced_water: null,
    },
  ],
};

function buildForecast(): FieldForecast {
  const points = Array.from({ length: 24 }, (_, i) => ({ year: 2021, month: (i % 12) + 1, value: 4 - i * 0.1 }));
  return {
    field_npdid: 7,
    target: "oil_equivalents",
    points,
    method: "arps_decline",
    backtest_mape: 0.09,
    credible: true,
    history_months: 120,
  };
}

function clientWith(forecast: ForecastResult): NcsApiClient {
  return {
    listFields: vi.fn(),
    getField: vi.fn(),
    getProduction: vi.fn(async () => PRODUCTION),
    getForecast: vi.fn(async () => forecast),
    getFieldsGeoJson: vi.fn(),
  } as NcsApiClient;
}

describe("FieldDetailPanel — branches on the typed forecast outcome", () => {
  it("no selection: shows a prompt and no chart", () => {
    render(<FieldDetailPanel client={clientWith(buildForecast())} field={null} />);
    expect(screen.getByText(/select a field/i)).toBeInTheDocument();
    expect(screen.queryByTestId("plotly-chart")).not.toBeInTheDocument();
  });

  it("a credible FieldForecast: renders the chart + the badge, and NO no-forecast notice", async () => {
    render(<FieldDetailPanel client={clientWith(buildForecast())} field={FIELD} />);

    const chart = await screen.findByTestId("plotly-chart");
    // Two traces: history + forecast.
    expect(within(chart).getAllByTestId("plotly-trace")).toHaveLength(2);
    // The badge shows MAPE % + Credible; the no-forecast notice is absent.
    expect(await screen.findByText(/9\s*%/)).toBeInTheDocument();
    expect(screen.getByText(/credible/i)).toBeInTheDocument();
    expect(screen.queryByText(/no credible forecast/i)).not.toBeInTheDocument();
  });

  it("a genuine fault: shows an error alert and no chart (branches on error, not data)", async () => {
    const failing = {
      listFields: vi.fn(),
      getField: vi.fn(),
      getProduction: vi.fn(async () => {
        throw new Error("field_not_found: 7");
      }),
      getForecast: vi.fn(async () => buildForecast()),
      getFieldsGeoJson: vi.fn(),
    } as NcsApiClient;

    render(<FieldDetailPanel client={failing} field={FIELD} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not load/i);
    expect(screen.queryByTestId("plotly-chart")).not.toBeInTheDocument();
  });

  it("ForecastNotAvailable: renders history-only chart + the notice, NO badge, NO forecast trace", async () => {
    const notAvailable: ForecastResult = {
      kind: FORECAST_NOT_AVAILABLE,
      field_npdid: 7,
      detail: "3 months; 60 required.",
    };
    render(<FieldDetailPanel client={clientWith(notAvailable)} field={FIELD} />);

    const chart = await screen.findByTestId("plotly-chart");
    const traces = within(chart).getAllByTestId("plotly-trace");
    // History only — one trace, none with the 24-point forecast horizon.
    expect(traces).toHaveLength(1);
    expect(traces[0].getAttribute("data-point-count")).toBe("2");
    // The explicit notice is shown; no MAPE badge.
    expect(await screen.findByText(/no credible forecast/i)).toBeInTheDocument();
    expect(screen.queryByText(/backtest mape/i)).not.toBeInTheDocument();
  });
});
