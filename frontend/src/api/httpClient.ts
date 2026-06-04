/**
 * The real `NcsApiClient` (004-R5) — `fetch` against the live 003 API.
 *
 * Endpoint binding (verified against 003's routes, contracts.md): paths are **un-prefixed** and
 * joined to `apiBaseUrl` (`VITE_API_BASE_URL`). The only method carrying the R4 branch is
 * `getForecast`: a **404 `forecast_not_available`** resolves to a typed `ForecastNotAvailable`
 * VALUE (an expected, rendered state — never a thrown error); every other non-2xx (incl. 404
 * `field_not_found`), a network failure, or a malformed body THROWS (a genuine fault).
 *
 * Transport only — no shape-building (that is `lib/*`) and no React. One small `getJson` helper
 * keeps the success path uniform; `getForecast` adds the single R4-specific 404 handling.
 */
import type {
  ErrorResponse,
  Field,
  FieldFeatureCollection,
  FieldForecast,
  FieldListResponse,
  ForecastResult,
  NcsApiClient,
  ProductionHistoryResponse,
} from "./contracts";
import { FORECAST_NOT_AVAILABLE } from "./contracts";

/** Trim a trailing slash so `base + "/fields"` never doubles the separator. */
function joinUrl(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/+$/, "")}${path}`;
}

/** Parse a response body as JSON, throwing a clear error if the body is not valid JSON. */
async function parseJson<T>(response: Response, url: string): Promise<T> {
  try {
    return (await response.json()) as T;
  } catch {
    throw new Error(`Malformed JSON body from ${url}`);
  }
}

/** Best-effort read of a typed ErrorResponse body (for branching/messages); null if unreadable. */
async function readErrorBody(response: Response): Promise<ErrorResponse | null> {
  try {
    return (await response.json()) as ErrorResponse;
  } catch {
    return null;
  }
}

/**
 * Build the real client. Each method `fetch`es the un-prefixed path under `apiBaseUrl`; a non-2xx
 * (other than the R4 forecast case) or malformed body throws.
 */
export function createHttpClient(apiBaseUrl: string): NcsApiClient {
  /** GET + 2xx-or-throw + JSON-parse — the uniform success path for the non-R4 endpoints. */
  async function getJson<T>(path: string): Promise<T> {
    const url = joinUrl(apiBaseUrl, path);
    const response = await fetch(url);
    if (!response.ok) {
      const body = await readErrorBody(response);
      const detail = body?.detail ?? response.statusText;
      throw new Error(`GET ${url} failed: ${response.status} ${detail}`);
    }
    return parseJson<T>(response, url);
  }

  return {
    listFields(): Promise<FieldListResponse> {
      return getJson<FieldListResponse>("/fields");
    },

    getField(npdid: number): Promise<Field> {
      return getJson<Field>(`/fields/${npdid}`);
    },

    getProduction(npdid: number): Promise<ProductionHistoryResponse> {
      return getJson<ProductionHistoryResponse>(`/fields/${npdid}/production`);
    },

    async getForecast(npdid: number): Promise<ForecastResult> {
      const url = joinUrl(apiBaseUrl, `/fields/${npdid}/forecast`);
      const response = await fetch(url);

      if (response.ok) {
        return parseJson<FieldForecast>(response, url);
      }

      // R4: a 404 whose typed code is `forecast_not_available` is a NORMAL outcome — surface it as
      // a value the UI renders. A 404 `field_not_found` (or anything else) is a genuine fault.
      const body = await readErrorBody(response);
      if (response.status === 404 && body?.code === FORECAST_NOT_AVAILABLE) {
        return {
          kind: FORECAST_NOT_AVAILABLE,
          field_npdid: npdid,
          detail: body.detail,
        };
      }

      const detail = body?.detail ?? response.statusText;
      throw new Error(`GET ${url} failed: ${response.status} ${detail}`);
    },

    getFieldsGeoJson(): Promise<FieldFeatureCollection> {
      return getJson<FieldFeatureCollection>("/fields.geojson");
    },
  };
}
