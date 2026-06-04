/**
 * FieldDetailPanel (004-R2/R3/R4) — orchestrates the selected field's view.
 *
 * It fetches via `useFieldData`, then branches ON THE DATA (never on a caught exception):
 *  - no selection            → a prompt to pick a field;
 *  - loading / error         → a status line;
 *  - a real `FieldForecast`  → the chart (history + forecast) + the `ForecastBadge` (R2/R3);
 *  - `ForecastNotAvailable`  → the chart (history ONLY, no forecast trace) + `NoForecastNotice` (R4).
 *
 * The history chart is rendered whenever production loaded — so a selected field is never blank, and
 * the no-forecast field still shows its real history with NO fabricated curve (R4).
 *
 * Header: the selected field's NAME is the detail heading (the demo's visible surface — 004-R2), with
 * NPDID + operator/area/status as the sub-line. The name also labels the map polygon / list control;
 * the acceptance "selected field" assertion is scoped to this detail region so it stays unambiguous.
 */
import type { Field, NcsApiClient } from "../api/contracts";
import { useFieldData } from "../hooks/useFieldData";
import { ForecastBadge } from "./ForecastBadge";
import { NoForecastNotice } from "./NoForecastNotice";
import { ProductionForecastChart } from "./ProductionForecastChart";

interface FieldDetailPanelProps {
  client: NcsApiClient;
  /** The selected field (its identity/attributes); null when nothing is selected. */
  field: Field | null;
}

export function FieldDetailPanel({ client, field }: FieldDetailPanelProps) {
  const npdid = field?.field_npdid ?? null;
  const { production, forecastResult, loading, error } = useFieldData(client, npdid);

  if (field === null) {
    return (
      <section className="field-detail field-detail--empty" aria-label="Field detail">
        <p>Select a field on the map or from the list to see its production and forecast.</p>
      </section>
    );
  }

  // A real FieldForecast has no `kind`; ForecastNotAvailable carries `kind` (the R4 discriminant).
  const noForecast = forecastResult !== null && "kind" in forecastResult;
  const forecast = forecastResult !== null && !("kind" in forecastResult) ? forecastResult : null;

  return (
    <section className="field-detail" aria-label="Field detail">
      <header className="field-detail__header">
        <h2 className="field-detail__title">{field.field_name}</h2>
        <p className="field-detail__meta">
          {[`NPDID ${field.field_npdid}`, field.operator, field.main_area, field.current_activity_status]
            .filter((attr): attr is string => Boolean(attr))
            .join(" · ")}
        </p>
      </header>

      {loading ? <p className="field-detail__status">Loading…</p> : null}
      {error ? (
        <p className="field-detail__status field-detail__status--error" role="alert">
          Could not load this field’s data: {error.message}
        </p>
      ) : null}

      {production ? (
        <>
          <ProductionForecastChart production={production} forecast={forecast} />
          {forecast ? <ForecastBadge forecast={forecast} /> : null}
          {noForecast ? (
            <NoForecastNotice
              detail={forecastResult && "kind" in forecastResult ? forecastResult.detail : undefined}
            />
          ) : null}
        </>
      ) : null}
    </section>
  );
}
