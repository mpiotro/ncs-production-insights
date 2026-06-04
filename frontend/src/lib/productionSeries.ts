/**
 * Pure builder: a field's monthly history → a Plotly-ready oil-equivalents series (004-R2).
 *
 * Single responsibility (plan §3): keep null-handling and the (year,month)→x-axis mapping OUT of
 * the components, where it is unit-testable in isolation. Two rules this module owns:
 *  - **Ordering.** Rows arrive in any order (003 orders them, but the chart must not assume it);
 *    they are sorted ascending by (year, month) so the x-axis reads left-to-right in time.
 *  - **Null is a GAP, never 0.0.** A JSON `null` oil_equivalents month is a real absence (001-R6 /
 *    003-R3); it stays `null` in the `y` array so Plotly draws a gap, never a fabricated zero.
 *
 * No React, no fetch — a deterministic function of its input.
 */
import type { MonthlyProduction, ProductionHistoryResponse } from "../api/contracts";

/** A chart-ready series: parallel x (month labels) and y (oe values; `null` = a gap). */
export interface ProductionSeries {
  /** "YYYY-MM" month labels, ascending by (year, month). */
  x: string[];
  /** Oil-equivalents per month; a `null` entry is a real gap (never coerced to 0.0). */
  y: (number | null)[];
}

/** Zero-pad a month to "MM" so labels sort/display consistently (e.g. 3 → "03"). */
function monthLabel(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, "0")}`;
}

/** Ascending comparison by (year, month). */
function byYearMonth(a: MonthlyProduction, b: MonthlyProduction): number {
  return a.year - b.year || a.month - b.month;
}

/**
 * Build the oil-equivalents history series from a 003 production response. Rows are copied before
 * sorting (the input is never mutated). A `null` oil_equivalents survives as a `null` y entry.
 */
export function buildProductionSeries(response: ProductionHistoryResponse): ProductionSeries {
  const ordered = [...response.production].sort(byYearMonth);
  return {
    x: ordered.map((row) => monthLabel(row.year, row.month)),
    // Preserve null exactly — never `?? 0`, never a falsy coercion (the gap rule, R2).
    y: ordered.map((row) => row.oil_equivalents),
  };
}
