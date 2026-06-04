/**
 * Unit tests (developer-owned, principle 4) for the forecast series builder (004-R2).
 * The horizon is 24 points; the builder maps each point to a label + value and orders by month.
 */
import { describe, expect, it } from "vitest";

import { buildForecastSeries } from "./forecastSeries";
import type { FieldForecast, ForecastPoint } from "../api/contracts";

function forecast(points: ForecastPoint[]): FieldForecast {
  return {
    field_npdid: 1,
    target: "oil_equivalents",
    points,
    method: "arps_decline",
    backtest_mape: 0.1,
    credible: true,
    history_months: 120,
  };
}

function buildPoints(startYear: number, startMonth: number, base: number): ForecastPoint[] {
  const points: ForecastPoint[] = [];
  let year = startYear;
  let month = startMonth;
  for (let i = 0; i < 24; i += 1) {
    points.push({ year, month, value: base - i });
    month += 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
  }
  return points;
}

describe("buildForecastSeries", () => {
  it("maps each forecast point to a parallel label + value", () => {
    const series = buildForecastSeries(
      forecast([
        { year: 2021, month: 5, value: 8.9 },
        { year: 2021, month: 6, value: 8.8 },
      ]),
    );
    expect(series.x).toEqual(["2021-05", "2021-06"]);
    expect(series.y).toEqual([8.9, 8.8]);
  });

  it("preserves the full 24-point horizon", () => {
    const series = buildForecastSeries(forecast(buildPoints(2021, 5, 8.9)));
    expect(series.x).toHaveLength(24);
    expect(series.y).toHaveLength(24);
  });

  it("orders points ascending by (year, month) even if given out of order", () => {
    const series = buildForecastSeries(
      forecast([
        { year: 2022, month: 1, value: 1 },
        { year: 2021, month: 12, value: 2 },
      ]),
    );
    expect(series.x).toEqual(["2021-12", "2022-01"]);
    expect(series.y).toEqual([2, 1]);
  });

  it("does not mutate the input points array", () => {
    const points = [
      { year: 2021, month: 6, value: 1 },
      { year: 2021, month: 5, value: 2 },
    ];
    const before = points.map((p) => `${p.year}-${p.month}`);
    buildForecastSeries(forecast(points));
    expect(points.map((p) => `${p.year}-${p.month}`)).toEqual(before);
  });
});
