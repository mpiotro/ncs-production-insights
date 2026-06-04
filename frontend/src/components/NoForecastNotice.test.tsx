/**
 * Unit tests (developer-owned, principle 4) for NoForecastNotice (004-R4).
 * It must clearly state no credible forecast is available, and optionally show the API's detail.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { NoForecastNotice } from "./NoForecastNotice";

describe("NoForecastNotice", () => {
  it("states plainly that no credible forecast is available (no props required)", () => {
    render(<NoForecastNotice />);
    expect(screen.getByText(/no credible forecast/i)).toBeInTheDocument();
  });

  it("renders the optional detail message when provided", () => {
    render(<NoForecastNotice detail="3 months of history; 60 required." />);
    expect(screen.getByText(/3 months of history/i)).toBeInTheDocument();
  });

  it("omits the detail paragraph when no detail is given", () => {
    const { container } = render(<NoForecastNotice />);
    expect(container.querySelector(".no-forecast-notice__detail")).toBeNull();
  });
});
