/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite + React plugin, and the Vitest test+coverage block (004-R6: establish the
// frontend test + coverage toolchain here — the JS analogue of pytest + pytest-cov).
export default defineConfig({
  plugins: [react()],
  test: {
    // Component tests render into a DOM (Testing-Library + jsdom), plan §2.
    environment: "jsdom",
    // jest-dom matchers are registered here once for the whole suite.
    setupFiles: ["./test/setup.ts"],
    // describe/it/expect available without imports (mirrors pytest's bare asserts).
    globals: true,
    // Unit specs are co-located as *.test.ts(x); acceptance specs live in test/acceptance/
    // (owned by the test-author, principle 4).
    include: ["src/**/*.{test,spec}.{ts,tsx}", "test/**/*.{test,spec}.{ts,tsx}"],
    coverage: {
      // Official Vitest V8 provider — emits text (console) + lcov (CI) like pytest-cov.
      provider: "v8",
      reporters: ["text", "lcov"],
      // Only measure src/ application logic — the ratchet (T11) tracks real code, not config.
      include: ["src/**/*.{ts,tsx}"],
      // Generated schema, type-only contracts, and entrypoints carry no testable logic.
      exclude: [
        "src/api/schema.gen.ts",
        "src/main.tsx",
        "**/*.test.{ts,tsx}",
        "**/*.test-d.ts",
      ],
      // NOTE: thresholds are 0 until the suite lands; the coordinator RATCHETS this to the
      // landed frontend baseline in 004-T11 (principle 9 — separate from the Python ratchet).
      thresholds: {
        statements: 0,
        branches: 0,
        functions: 0,
        lines: 0,
      },
    },
  },
});
