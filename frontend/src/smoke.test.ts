import { describe, expect, it } from "vitest";

import { scaffoldOk } from "./smoke";

// 004-T1 smoke test (004-R6): proves the Vitest runner, jsdom env, jest-dom setup, and
// V8 coverage instrumentation are all wired before any real feature code exists.
describe("frontend scaffold (004-T1, R6)", () => {
  it("runs a green test through Vitest", () => {
    expect(scaffoldOk()).toBe(true);
  });

  it("has the jsdom environment available", () => {
    expect(typeof document).toBe("object");
    expect(document.createElement("div")).toBeInstanceOf(HTMLElement);
  });
});
