/**
 * The single config-only live↔mock switch (004-R5).
 *
 * `apiSource === "mock"` ⇒ the in-memory dev mock (no network); any other source ⇒ the fetch-backed
 * http client hitting `apiBaseUrl`. The app/components depend on `NcsApiClient`, never on a concrete
 * implementation, so this one function is the ONLY place the choice is made — that is what makes
 * "mock ↔ live with no code change" (R5) structurally true.
 */
import type { AppConfig } from "../config";
import type { NcsApiClient } from "./contracts";
import { createHttpClient } from "./httpClient";
import { createMockClient } from "./mockClient";

/** The data-source value that selects the in-memory mock; anything else selects the http client. */
export const MOCK_SOURCE = "mock";

/**
 * Resolve the client from configuration. `apiSource: "mock"` returns the dev mock; any other value
 * returns the http client bound to `apiBaseUrl`.
 */
export function selectClient(config: AppConfig): NcsApiClient {
  if (config.apiSource === MOCK_SOURCE) {
    return createMockClient();
  }
  return createHttpClient(config.apiBaseUrl);
}
