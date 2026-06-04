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
 * Header note: the field NAME is the selected control in the map/list (highlighted there); the detail
 * header identifies the field by NPDID + descriptive attributes rather than repeating the name, so a
 * single selection control owns each field's name in the DOM (keeps the map⇄detail query unambiguous).
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
        <h2 className="field-detail__title">Selected field — NPDID {field.field_npdid}</h2>
        <p className="field-detail__meta">
          {[field.operator, field.main_area, field.current_activity_status]
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
