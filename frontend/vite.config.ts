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
      // Generated schema, type-only declarations, and entrypoints carry no testable logic.
      exclude: [
        "src/api/schema.gen.ts",
        "src/main.tsx",
        "src/**/*.d.ts",
        "**/*.test.{ts,tsx}",
        "**/*.test-d.ts",
      ],
      // 004-T11 ratchet (principle 9, separate from the Python baseline). The suite landed at
      // 100% statements/functions/lines and 96.45% branches; thresholds are set a couple of points
      // below measured for headroom (mirroring the Python 0→92-under-95.7 precedent). CI fails any
      // drop below these; a deliberate reduction needs a coordinator-recorded COVERAGE-WAIVER.
      thresholds: {
        statements: 98,
        branches: 94,
        functions: 98,
        lines: 98,
      },
    },
  },
});
