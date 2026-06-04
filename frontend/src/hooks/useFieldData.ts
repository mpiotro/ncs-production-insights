/**
 * useFieldData (004-R2/R3/R4) — the data-fetching hook for one selected field.
 *
 * It isolates the two PARALLEL fetches (`getProduction` + `getForecast`) and exposes
 * `{ production, forecastResult, loading, error }`. It threads the R4 typed outcome: `forecastResult`
 * is `ForecastResult | null` (`FieldForecast | ForecastNotAvailable | null`), so the panel branches
 * on DATA, never on a caught exception — the insufficient-history state can never be swallowed.
 *
 * A genuine fault (network down, 5xx, malformed body, or a `field_not_found`) surfaces as `error`.
 * A `null` npdid means "no selection": everything is null and not loading.
 */
import { useEffect, useState } from "react";

import type { NcsApiClient, ForecastResult, ProductionHistoryResponse } from "../api/contracts";

export interface FieldData {
  /** The field's monthly history (the chart's history stream), or null before/without a load. */
  production: ProductionHistoryResponse | null;
  /** The R4 typed forecast outcome (a forecast, a no-forecast value, or null), branched on by the UI. */
  forecastResult: ForecastResult | null;
  /** True while the two fetches are in flight. */
  loading: boolean;
  /** A genuine fault (not the expected no-forecast outcome), else null. */
  error: Error | null;
}

const EMPTY: FieldData = {
  production: null,
  forecastResult: null,
  loading: false,
  error: null,
};

/** Fetch a field's production + forecast in parallel; re-runs when `npdid` or `client` changes. */
export function useFieldData(client: NcsApiClient, npdid: number | null): FieldData {
  const [state, setState] = useState<FieldData>(EMPTY);

  useEffect(() => {
    if (npdid === null) {
      setState(EMPTY);
      return;
    }

    let cancelled = false;
    setState({ production: null, forecastResult: null, loading: true, error: null });

    // Parallel — the forecast is independent of the history; both load together (plan §3).
    Promise.all([client.getProduction(npdid), client.getForecast(npdid)])
      .then(([production, forecastResult]) => {
        if (!cancelled) {
          setState({ production, forecastResult, loading: false, error: null });
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          const error = cause instanceof Error ? cause : new Error(String(cause));
          setState({ production: null, forecastResult: null, loading: false, error });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [client, npdid]);

  return state;
}
