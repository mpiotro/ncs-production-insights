/**
 * Unit tests (developer-owned, principle 4) for the oe history series builder (004-R2).
 * Pins the two load-bearing rules: (year,month) ordering and "null is a GAP, never 0.0".
 */
import { describe, expect, it } from "vitest";

import { buildProductionSeries } from "./productionSeries";
import type { MonthlyProduction, ProductionHistoryResponse } from "../api/contracts";

function row(year: number, month: number, oe: number | null): MonthlyProduction {
  return {
    field_npdid: 1,
    field_name: "F",
    year,
    month,
    oil: oe,
    gas: null,
    ngl: null,
    condensate: null,
    oil_equivalents: oe,
    produced_water: null,
  };
}

function response(production: MonthlyProduction[]): ProductionHistoryResponse {
  return { field_npdid: 1, count: production.length, production };
}

describe("buildProductionSeries", () => {
  it("orders rows ascending by (year, month) regardless of input order", () => {
    const series = buildProductionSeries(
      response([
        row(2021, 4, 9.0),
        row(2020, 12, 10.1),
        row(2021, 1, 9.8),
        row(2020, 11, 10.4),
      ]),
    );
    expect(series.x).toEqual(["2020-11", "2020-12", "2021-01", "2021-04"]);
    expect(series.y).toEqual([10.4, 10.1, 9.8, 9.0]);
  });

  it("keeps a null oil_equivalents month as a GAP (null, never 0.0)", () => {
    const series = buildProductionSeries(
      response([row(2021, 1, 9.8), row(2021, 2, null), row(2021, 3, 9.0)]),
    );
    expect(series.y).toEqual([9.8, null, 9.0]);
    expect(series.y).toContain(null);
    expect(series.y).not.toContain(0);
  });

  it("zero-pads single-digit months in the labels", () => {
    const series = buildProductionSeries(response([row(2021, 3, 1.0)]));
    expect(series.x).toEqual(["2021-03"]);
  });

  it("does not mutate the input production array", () => {
    const production = [row(2021, 2, 1.0), row(2021, 1, 2.0)];
    const before = production.map((r) => `${r.year}-${r.month}`);
    buildProductionSeries(response(production));
    const after = production.map((r) => `${r.year}-${r.month}`);
    expect(after).toEqual(before);
  });

  it("returns empty parallel arrays for an empty history", () => {
    const series = buildProductionSeries(response([]));
    expect(series.x).toEqual([]);
    expect(series.y).toEqual([]);
  });
});
