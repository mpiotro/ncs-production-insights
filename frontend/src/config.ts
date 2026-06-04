/**
 * Runtime configuration (004-R5) — read once from Vite's `import.meta.env`.
 *
 * The two public, non-sensitive knobs (documented in `.env.example`, no secrets — principle 7):
 *  - `VITE_API_BASE_URL` — base URL of the 003 API the http client fetches.
 *  - `VITE_API_SOURCE`   — which `NcsApiClient` to use: "mock" (in-memory fixtures, no network)
 *                          or anything else ("http") for the live, fetch-backed client.
 *
 * Switching mock <-> live is configuration only — no code change (004-R5). `selectClient` is the
 * single place this config is consumed.
 */

/** The resolved frontend configuration. */
export interface AppConfig {
  /** Base URL of the 003 API (joined to un-prefixed paths by the http client). */
  apiBaseUrl: string;
  /** Data-source switch: "mock" => in-memory mock client; otherwise the http client. */
  apiSource: string;
}

/** Default base URL when `VITE_API_BASE_URL` is unset (003 runs on 8003 locally). */
const DEFAULT_API_BASE_URL = "http://localhost:8003";

/** Default data source when `VITE_API_SOURCE` is unset — mock keeps `npm run dev` zero-config. */
const DEFAULT_API_SOURCE = "mock";

/**
 * Read the configuration from `import.meta.env`. Falls back to safe defaults so a missing `.env`
 * never crashes the app (the demo runs against the mock by default).
 */
export function readConfig(): AppConfig {
  const env = import.meta.env;
  // An unset OR empty env var falls back to the default (an empty string is not a usable value).
  return {
    apiBaseUrl: nonEmpty(env.VITE_API_BASE_URL) ?? DEFAULT_API_BASE_URL,
    apiSource: nonEmpty(env.VITE_API_SOURCE) ?? DEFAULT_API_SOURCE,
  };
}

/** Return the trimmed string if it has content, else undefined (so `??` applies the default). */
function nonEmpty(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}
