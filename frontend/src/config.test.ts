/**
 * Unit tests (developer-owned, principle 4) for readConfig (004-R5).
 * It reads the two public knobs from import.meta.env and falls back to safe defaults when unset, so
 * a missing .env never crashes the app (the demo defaults to the mock). Uses vi.stubEnv.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { readConfig } from "./config";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("readConfig", () => {
  it("reads VITE_API_BASE_URL and VITE_API_SOURCE from the env", () => {
    vi.stubEnv("VITE_API_BASE_URL", "http://example.test:9000");
    vi.stubEnv("VITE_API_SOURCE", "http");

    expect(readConfig()).toEqual({
      apiBaseUrl: "http://example.test:9000",
      apiSource: "http",
    });
  });

  it("falls back to safe defaults (local 003 + mock) when the env is unset", () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    vi.stubEnv("VITE_API_SOURCE", "");

    // Empty-string env vars are absent values → defaults apply (mock keeps `npm run dev` zero-config).
    const config = readConfig();
    expect(config.apiBaseUrl).toBe("http://localhost:8003");
    expect(config.apiSource).toBe("mock");
  });
});
