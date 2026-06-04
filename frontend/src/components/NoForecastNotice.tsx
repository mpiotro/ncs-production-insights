/**
 * NoForecastNotice (004-R4) — the explicit "no credible forecast available" state.
 *
 * Shown for a field whose history is too short to forecast (the typed `ForecastNotAvailable`
 * outcome). It states plainly that no credible forecast exists — the panel still renders the field's
 * real history alongside this, and draws NO forecast trace, so the user never sees a blank panel or
 * a fabricated curve (R4). An optional `detail` carries 003's human message (e.g. how many months).
 */
interface NoForecastNoticeProps {
  /** Optional human detail from the API (e.g. "3 months of history; 60 required"). */
  detail?: string;
}

/** Render the explicit no-forecast notice (R4). */
export function NoForecastNotice({ detail }: NoForecastNoticeProps = {}) {
  return (
    <div className="no-forecast-notice" role="status">
      <p className="no-forecast-notice__headline">
        No credible forecast available for this field (insufficient history).
      </p>
      {detail ? <p className="no-forecast-notice__detail">{detail}</p> : null}
    </div>
  );
}
