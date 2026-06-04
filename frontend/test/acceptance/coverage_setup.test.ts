/**
 * 004-R6 — The frontend SHALL have a test setup with coverage measurement established in this
 * phase (tech-standards: frontend coverage tooling is fixed in 004).
 *
 * UNLIKE the other acceptance suites, this one is EXPECTED TO PASS NOW: it guards the test +
 * coverage apparatus itself (established in T1) from regressing. It gives R6 a citing, passing
 * test for the life of the project (principle 9) — independent of any component code.
 *
 * It asserts, by reading the committed config, that:
 *  - `package.json` exposes a `coverage` script that runs Vitest WITH coverage, and
 *  - `vite.config.ts` configures the V8 coverage provider (the official Vitest provider, the JS
 *    analogue of pytest-cov).
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// This file lives at frontend/test/acceptance/ — the frontend root is two levels up.
const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = resolve(HERE, "..", "..");

function read(relPath: string): string {
  return readFileSync(resolve(FRONTEND_ROOT, relPath), "utf8");
}

describe("004-R6 — frontend test + coverage tooling is established (apparatus guard, expected GREEN)", () => {
  it("004-R6: package.json defines a `coverage` script that runs Vitest with coverage", () => {
    const pkg = JSON.parse(read("package.json")) as {
      scripts?: Record<string, string>;
      devDependencies?: Record<string, string>;
    };

    const coverageScript = pkg.scripts?.coverage ?? "";
    expect(coverageScript).toMatch(/vitest/);
    expect(coverageScript).toMatch(/--coverage/);

    // The official V8 coverage provider must be a declared dependency.
    const devDeps = pkg.devDependencies ?? {};
    expect(devDeps).toHaveProperty("@vitest/coverage-v8");
  });

  it("004-R6: there is a `test` script that runs Vitest", () => {
    const pkg = JSON.parse(read("package.json")) as { scripts?: Record<string, string> };
    expect(pkg.scripts?.test ?? "").toMatch(/vitest/);
  });

  it("004-R6: vite.config.ts configures the V8 coverage provider", () => {
    const viteConfig = read("vite.config.ts");
    expect(viteConfig).toMatch(/coverage\s*:/);
    expect(viteConfig).toMatch(/provider\s*:\s*["']v8["']/);
  });

  it("004-R6: the suite runs under jsdom with the jest-dom setup file wired", () => {
    const viteConfig = read("vite.config.ts");
    expect(viteConfig).toMatch(/environment\s*:\s*["']jsdom["']/);
    expect(viteConfig).toMatch(/setupFiles/);
  });
});
