/**
 * Unit tests (developer-owned, principle 4) for ForecastBadge (004-R3).
 * MAPE is a fraction on the wire → rendered as round(mape*100)%; the indicator follows `credible`.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ForecastBadge } from "./ForecastBadge";
import type { FieldForecast } from "../api/contracts";

function forecast(overrides: Partial<FieldForecast>): FieldForecast {
  return {
    field_npdid: 1,
    target: "oil_equivalents",
    points: [],
    method: "arps_decline",
    backtest_mape: 0.08,
    credible: true,
    history_months: 120,
    ...overrides,
  };
}

describe("ForecastBadge", () => {
  it("renders MAPE as a rounded whole percent (0.08 → 8%)", () => {
    render(<ForecastBadge forecast={forecast({ backtest_mape: 0.08 })} />);
    expect(screen.getByText(/8\s*%/)).toBeInTheDocument();
  });

  it("rounds the MAPE to the nearest percent (0.156 → 16%)", () => {
    render(<ForecastBadge forecast={forecast({ backtest_mape: 0.156, credible: false })} />);
    expect(screen.getByText(/16\s*%/)).toBeInTheDocument();
  });

  it("shows 'Credible' when credible is true and not 'Low confidence'", () => {
    render(<ForecastBadge forecast={forecast({ credible: true })} />);
    expect(screen.getByText(/^credible$/i)).toBeInTheDocument();
    expect(screen.queryByText(/low[\s-]?confidence/i)).not.toBeInTheDocument();
  });

  it("shows 'Low confidence' when credible is false", () => {
    render(<ForecastBadge forecast={forecast({ credible: false, backtest_mape: 0.22 })} />);
    expect(screen.getByText(/low[\s-]?confidence/i)).toBeInTheDocument();
  });

  it("shows the selected method as a detail", () => {
    render(<ForecastBadge forecast={forecast({ method: "holt_damped" })} />);
    expect(screen.getByText(/holt_damped/i)).toBeInTheDocument();
  });
});
