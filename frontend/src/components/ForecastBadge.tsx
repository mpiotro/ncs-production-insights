/**
 * ForecastBadge (004-R3) — the backtest MAPE + a credible / low-confidence indicator.
 *
 * MAPE is a FRACTION on the wire (contracts): `backtest_mape` 0.08 ⇒ "8%". The credible/low-
 * confidence wording is driven by `credible` (002's classification: mape < 0.15, guard-adjusted),
 * NOT recomputed here — the badge reflects 002's decision so the two never disagree (R3).
 */
import type { FieldForecast } from "../api/contracts";

interface ForecastBadgeProps {
  forecast: FieldForecast;
}

/** Render the held-out MAPE as a whole-percent and the credibility indicator (R3). */
export function ForecastBadge({ forecast }: ForecastBadgeProps) {
  const mapePercent = Math.round(forecast.backtest_mape * 100);
  const indicator = forecast.credible ? "Credible" : "Low confidence";

  return (
    <div className="forecast-badge" data-credible={String(forecast.credible)}>
      <span className="forecast-badge__mape">Backtest MAPE: {mapePercent}%</span>
      <span className="forecast-badge__indicator">{indicator}</span>
      <span className="forecast-badge__method">Method: {forecast.method}</span>
    </div>
  );
}
