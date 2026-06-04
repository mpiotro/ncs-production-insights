/**
 * ProductionForecastChart (004-R2) — one Plotly chart with the field's oil-equivalents history and,
 * when a credible forecast exists, the 24-month forecast — the two VISUALLY DISTINCT.
 *
 * Distinction (plan §3): a SOLID history line vs a DASHED forecast line, with distinct legend names.
 * The history `y` preserves a `null` month as a gap (never 0.0) — the series builders own that rule.
 * The forecast trace is drawn ONLY when `forecast` is a real `FieldForecast`; for the insufficient-
 * history outcome it is omitted entirely (no fabricated curve — R4). Plotly is the heavy view lib
 * `react-plotly.js` (mocked to a stand-in in the acceptance suites); we only hand it `data` traces.
 */
import type { Data } from "plotly.js";
import Plot from "react-plotly.js";

import type { FieldForecast, ProductionHistoryResponse } from "../api/contracts";
import { buildForecastSeries } from "../lib/forecastSeries";
import { buildProductionSeries } from "../lib/productionSeries";

interface ProductionForecastChartProps {
  production: ProductionHistoryResponse;
  /** A real forecast draws the dashed forecast trace; `null` (no credible forecast) draws none (R4). */
  forecast: FieldForecast | null;
}

/** The two distinct trace names — the legend tells history from forecast (R2). */
const HISTORY_TRACE_NAME = "History (oil equivalents)";
const FORECAST_TRACE_NAME = "Forecast (24 months)";

/** Build the chart's `data` traces and hand them to Plotly (R2). */
export function ProductionForecastChart({ production, forecast }: ProductionForecastChartProps) {
  const history = buildProductionSeries(production);

  // History: a solid line. A null oe month stays null in `y` so Plotly renders a gap (R2).
  const historyTrace: Data = {
    type: "scatter",
    mode: "lines+markers",
    name: HISTORY_TRACE_NAME,
    x: history.x,
    y: history.y,
    line: { dash: "solid", color: "#1f77b4" },
    connectgaps: false,
  };

  const data: Data[] = [historyTrace];

  // Forecast: a dashed line, ONLY when a credible forecast exists (R4 omits it otherwise).
  if (forecast !== null) {
    const forecastSeries = buildForecastSeries(forecast);
    data.push({
      type: "scatter",
      mode: "lines+markers",
      name: FORECAST_TRACE_NAME,
      x: forecastSeries.x,
      y: forecastSeries.y,
      line: { dash: "dash", color: "#ff7f0e" },
    });
  }

  return (
    <Plot
      data={data}
      layout={{
        autosize: true,
        title: { text: "Monthly oil equivalents — history and forecast" },
        xaxis: { title: { text: "Month" } },
        yaxis: { title: { text: "Oil equivalents (million Sm³)" } },
        showlegend: true,
      }}
      useResizeHandler
      style={{ width: "100%", height: "420px" }}
    />
  );
}
