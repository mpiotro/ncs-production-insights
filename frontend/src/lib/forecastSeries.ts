/**
 * Pure builder: a field's forecast points → a Plotly-ready series (004-R2).
 *
 * The forecast is the 24-month horizon (`FieldForecast.points`). Like `productionSeries`, this keeps
 * the (year,month)→x-axis mapping out of the chart component. Forecast points are never null (a
 * forecast value is always present), so `y` is `number[]`; the series stays ordered as 002/003
 * produced it (already chronological), but we sort defensively to guarantee a left-to-right x-axis.
 *
 * No React, no fetch — a deterministic function of its input.
 */
import type { FieldForecast, ForecastPoint } from "../api/contracts";

/** A chart-ready forecast series: parallel x (month labels) and y (forecast oe values). */
export interface ForecastSeries {
  /** "YYYY-MM" month labels, ascending by (year, month). */
  x: string[];
  /** Forecasted oil-equivalents per month (always present — a forecast value is never null). */
  y: number[];
}

/** Zero-pad a month to "MM" so labels match the history series' labels exactly. */
function monthLabel(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, "0")}`;
}

/** Ascending comparison by (year, month). */
function byYearMonth(a: ForecastPoint, b: ForecastPoint): number {
  return a.year - b.year || a.month - b.month;
}

/** Build the forecast series from a FieldForecast (the input array is never mutated). */
export function buildForecastSeries(forecast: FieldForecast): ForecastSeries {
  const ordered = [...forecast.points].sort(byYearMonth);
  return {
    x: ordered.map((point) => monthLabel(point.year, point.month)),
    y: ordered.map((point) => point.value),
  };
}
