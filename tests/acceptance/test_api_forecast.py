"""Acceptance suite: per-field forecast; insufficient-history -> distinct 404 — EARS 003-R4 (003-T4).

Black-box over HTTP through the seeded read-only store (``conftest_api.py``). ``GET
/fields/{npdid}/forecast`` returns the frozen ``FieldForecast`` for a forecastable field, and the R4
"insufficient history" case is a **distinct** HTTP outcome — 404 with ``code ==
"forecast_not_available"`` — never an empty or fabricated forecast.

* **003-R4** — "WHEN a client requests a field's forecast, the system SHALL return that field's
  ``FieldForecast`` (24-month oil-equivalents forecast, selected method, backtest MAPE, credibility);
  IF the field has no forecast (insufficient history), THEN the system SHALL indicate that distinctly
  (not an empty or fabricated forecast)." Proven three ways:
  - the ``CLEAN_POLYGON`` field (72 months) -> 200 + a frozen ``FieldForecast``: exactly 24 points, a
    selected ``method``, a ``backtest_mape``, and ``credible`` (this clean decline backtests credible).
    The served body equals the **persisted** forecast (the ``seeded_forecasts`` oracle), so the API
    serves the precomputed forecast, not a recomputation;
  - the ``SHORT_WITH_OUTLINE`` field (40 months — **exists**, but has no forecast row) -> **404** with
    ``code == "forecast_not_available"``, a code **distinct** from ``field_not_found``;
  - an **unknown** NPDID -> 404 with ``code == "field_not_found"`` — so "field exists, no forecast" and
    "no such field" are cleanly separable (the distinctness R4 demands).

The two outcomes are seeded structurally: ``run_forecasts`` persists a forecast for the >= 60-month
fields only, so the 40-month field's *absent* row is the genuine insufficient-history signal. Red
until ``ncs.api`` exists and 003-T7/T8 implement the forecast read + the two-code 404 handler.
"""

from __future__ import annotations

from conftest_api import (
    CLEAN_POLYGON_NPDID,
    NON_FORECASTABLE_NPDID,
    SHORT_MONTHS,
    UNKNOWN_NPDID,
)

# The forecastable field this suite asserts the success path on (72 months, clean decline → credible).
FORECASTABLE_NPDID = CLEAN_POLYGON_NPDID
FORECAST_HORIZON = 24  # the spec-fixed horizon (002 FORECAST_HORIZON); a served forecast has 24 points.


# ============================================================ R4 — the success path ================


def test_r4_forecast_returns_200_and_field_forecast(client) -> None:
    """003-R4: a forecastable field returns 200 with the frozen ``FieldForecast`` served verbatim.

    The success path returns the bare frozen ``FieldForecast`` (no wrapper — contracts.md), so the
    body validates against the 002 model. A valid body therefore *means* a real forecast (the
    insufficient-history case is a 404, asserted below — never an empty 200).
    """
    from ncs.forecast.contracts import FieldForecast

    response = client.get(f"/fields/{FORECASTABLE_NPDID}/forecast")

    assert response.status_code == 200, response.text
    forecast = FieldForecast.model_validate(response.json())  # validates 24-pt + invariants
    assert forecast.field_npdid == FORECASTABLE_NPDID


def test_r4_forecast_has_24_points_method_mape_and_credibility(client) -> None:
    """003-R4: the served forecast carries the 24-month horizon, a method, a MAPE, and credibility.

    R4 names the payload explicitly: a 24-month oe forecast, the selected method, the backtest MAPE,
    and the credibility flag. Each is asserted present and well-formed on the served body.
    """
    from ncs.forecast.contracts import FieldForecast, ForecastMethod, ForecastTarget

    body = client.get(f"/fields/{FORECASTABLE_NPDID}/forecast").json()
    forecast = FieldForecast.model_validate(body)

    assert len(forecast.points) == FORECAST_HORIZON           # 24-month horizon
    assert forecast.method in set(ForecastMethod)             # a selected approach
    assert forecast.target is ForecastTarget.oil_equivalents  # oil-equivalents (the one target)
    assert forecast.backtest_mape >= 0.0                      # a held-out MAPE fraction
    assert isinstance(forecast.credible, bool)                # credibility flag present
    assert forecast.history_months >= 60                      # only >= 60-month fields are forecast


def test_r4_clean_decline_field_is_credible(client) -> None:
    """003-R4: the clean-decline field's forecast is **credible** (backtest MAPE < 0.15).

    ``CLEAN_POLYGON`` is a smooth Arps decline engineered to backtest credible; the served forecast
    must reflect that — ``credible is True`` with ``backtest_mape < 0.15`` (the gate). This pins the
    *credible* side of R4 (the low-confidence side is exercised in 002's own suites).
    """
    from ncs.forecast.contracts import FieldForecast

    forecast = FieldForecast.model_validate(client.get(f"/fields/{FORECASTABLE_NPDID}/forecast").json())

    assert forecast.credible is True
    assert forecast.backtest_mape < 0.15


def test_r4_served_forecast_equals_the_persisted_forecast(client, seeded_forecasts) -> None:
    """003-R4: the API serves **exactly** the precomputed, persisted ``FieldForecast`` (no recompute).

    003 reads 002's persisted forecast rather than recomputing the backtest live (plan.md §Forecast
    coupling). The served body must equal the forecast read straight from the store (the
    ``seeded_forecasts`` oracle) — same points, method, MAPE, credibility. Catches any drift between
    what was persisted and what is served.
    """
    from ncs.forecast.contracts import FieldForecast

    served = FieldForecast.model_validate(client.get(f"/fields/{FORECASTABLE_NPDID}/forecast").json())

    assert served == seeded_forecasts[FORECASTABLE_NPDID]


def test_r4_forecast_points_are_ordered_by_calendar(client) -> None:
    """003-R4: the 24 forecast points are in ascending calendar order (the forward horizon).

    The forward forecast is a contiguous 24-month calendar; the served points come back ordered by
    ``(year, month)`` so 004 can plot them directly against the history.
    """
    from ncs.forecast.contracts import FieldForecast

    forecast = FieldForecast.model_validate(client.get(f"/fields/{FORECASTABLE_NPDID}/forecast").json())

    calendar = [(p.year, p.month) for p in forecast.points]
    assert calendar == sorted(calendar), "forecast points must be in ascending calendar order (R4)"


# ============================================================ R4 — insufficient history => 404 =====


def test_r4_insufficient_history_field_returns_404(client) -> None:
    """003-R4: a field that exists but has < 60 months (no forecast) returns HTTP 404 — not an empty 200.

    ``SHORT_WITH_OUTLINE`` (40 months) is a real, listed field, but ``run_forecasts`` produced no
    forecast for it. Requesting its forecast is a 404 ("this field's forecast does not exist"), never
    a 200 carrying an empty or fabricated forecast (the R4 "not an empty or fabricated forecast" bar).
    """
    assert SHORT_MONTHS < 60  # the seed makes this field insufficient-history by construction
    response = client.get(f"/fields/{NON_FORECASTABLE_NPDID}/forecast")
    assert response.status_code == 404


def test_r4_insufficient_history_uses_distinct_forecast_not_available_code(client) -> None:
    """003-R4: the insufficient-history 404 carries ``code == "forecast_not_available"`` — the distinct code.

    The heart of R4's "indicate that **distinctly**": the body is a typed ``ErrorResponse`` whose
    ``code`` is ``forecast_not_available`` (field exists, no forecast), explicitly **not**
    ``field_not_found``. The detail echoes the NPDID so 004 can message it.
    """
    from ncs.api.responses import ErrorCode, ErrorResponse

    response = client.get(f"/fields/{NON_FORECASTABLE_NPDID}/forecast")

    assert response.status_code == 404
    error = ErrorResponse.model_validate(response.json())
    assert error.code == ErrorCode.forecast_not_available
    assert error.code != ErrorCode.field_not_found       # distinct from the unknown-field 404
    assert str(NON_FORECASTABLE_NPDID) in error.detail


# ============================================================ R4/R6 — unknown field is a *different* 404


def test_r4_unknown_field_forecast_uses_field_not_found_code(client) -> None:
    """003-R4/R6: an **unknown** NPDID's forecast is 404 with ``field_not_found`` — not forecast-not-available.

    The contrast that proves the two 404s are distinct: an NPDID absent from the store gets
    ``field_not_found`` (no such field), whereas the existing-but-short field got
    ``forecast_not_available``. Same status (404), different typed ``code`` — exactly the distinction
    R4 requires and 004 branches on.
    """
    from ncs.api.responses import ErrorCode, ErrorResponse

    response = client.get(f"/fields/{UNKNOWN_NPDID}/forecast")

    assert response.status_code == 404
    error = ErrorResponse.model_validate(response.json())
    assert error.code == ErrorCode.field_not_found
    assert error.code != ErrorCode.forecast_not_available


def test_r4_two_404s_are_distinguishable_by_code(client) -> None:
    """003-R4: the two 404 conditions are told apart **by ``code``** on the same status (the R4 distinctness).

    A single test putting them side by side: forecast-of-short-field and forecast-of-unknown-field are
    both 404, but their ``ErrorResponse.code`` values differ (``forecast_not_available`` vs
    ``field_not_found``). This is the machine-readable distinctness R4 mandates — not prose in
    ``detail``.
    """
    from ncs.api.responses import ErrorCode, ErrorResponse

    short = client.get(f"/fields/{NON_FORECASTABLE_NPDID}/forecast")
    unknown = client.get(f"/fields/{UNKNOWN_NPDID}/forecast")

    assert short.status_code == unknown.status_code == 404
    short_code = ErrorResponse.model_validate(short.json()).code
    unknown_code = ErrorResponse.model_validate(unknown.json()).code

    assert short_code == ErrorCode.forecast_not_available
    assert unknown_code == ErrorCode.field_not_found
    assert short_code != unknown_code, (
        "the insufficient-history 404 and the unknown-field 404 must carry distinct codes (R4)"
    )
