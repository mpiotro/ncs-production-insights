"""Acceptance suite: backtest, approach selection & credibility — EARS 002-R2, R3, R4 (task 002-T3).

Black-box through ``Forecaster.forecast(history)`` on two contrasting synthetic histories
(``forecast_histories.py``): a **clean decline** that must backtest *credible* and a **volatile**
field that must backtest *low-confidence* — proving R4's "flagged, not hidden". No DuckDB, no
network.

* **002-R2** — produce every forecast through one ``Forecaster`` interface that evaluates >= 2
  competing approaches (Arps decline + a statistical method) and selects the **lowest held-out
  backtest MAPE**. Acceptance here: the result's ``method`` is one of the two ``ForecastMethod``
  members (a selection *was* made and recorded). We assert the method is *set and valid*, plus the
  credibility/MAPE relationship below — not the internal A-vs-B comparison (a white-box concern the
  developer unit-tests).

* **002-R3** — backtest each candidate by holding out the **final 24 months**, fitting on the
  earlier history, forecasting those 24, and computing MAPE against held-out actuals (principle 6).
  Acceptance here: a ``backtest_mape`` is recorded as a fraction >= 0, and for the clean decline it
  is small enough to clear the gate — i.e. a real held-out error was computed, not a placeholder.

* **002-R4** — classify ``credible`` WHEN selected MAPE < 0.15, else **low-confidence**, *flagged,
  never silently presented as credible*. Acceptance here: the clean field is ``credible is True``
  with ``backtest_mape < 0.15``; the volatile field **still produces a ``FieldForecast``** but is
  ``credible is False`` (>= 0.15) — present and flagged, not omitted. The frozen contract's
  one-directional invariant (``credible`` => ``backtest_mape < 0.15``) is asserted to hold on every
  produced forecast.

Red at collection time until 002-T8/T9/T10 implement the approaches, backtest and classification.
The volatile-field threshold (MAPE >= 0.15) is a **designed property of the synthetic series**
(large non-decline swings neither approach can fit) — see ``forecast_histories.volatile``.
"""

from __future__ import annotations

import pytest

from forecast_histories import clean_decline, volatile

from ncs.forecast import Forecaster
from ncs.forecast.contracts import FieldForecast, ForecastMethod

# The spec-fixed credibility gate (restated; the suite asserts the implementation honours it).
CREDIBLE_GATE = 0.15

CLEAN_NPDID = 7301
VOLATILE_NPDID = 7302
HISTORY_MONTHS = 72


# --- Module-scoped forecasts: the fit is the same for every assertion about a given field ---------


@pytest.fixture(scope="module")
def clean_forecast() -> FieldForecast:
    """Forecast of the clean-decline field — expected credible (selected MAPE < 0.15)."""
    return Forecaster().forecast(clean_decline(CLEAN_NPDID, HISTORY_MONTHS))


@pytest.fixture(scope="module")
def volatile_forecast() -> FieldForecast:
    """Forecast of the volatile field — expected low-confidence (selected MAPE >= 0.15), still produced."""
    return Forecaster().forecast(volatile(VOLATILE_NPDID, HISTORY_MONTHS))


# ============================================================ R2 — selection among >= 2 approaches =


def test_r2_a_method_was_selected_and_recorded(clean_forecast: FieldForecast) -> None:
    """002-R2: a selected approach is recorded, drawn from the closed set of competing methods.

    R2 requires the forecast be produced through the one interface that adjudicates >= 2 approaches
    and records the winner. We assert the recorded ``method`` is a valid ``ForecastMethod`` member
    (one of the two the enum fixes) — i.e. a selection happened. *Which* one wins on a given field,
    and the lowest-MAPE rule, are the developer's unit concern; the acceptance-level evidence that
    selection is MAPE-driven is the credibility/MAPE relationship asserted under R4 below.
    """
    assert isinstance(clean_forecast.method, ForecastMethod)
    assert clean_forecast.method in set(ForecastMethod), (
        "the selected method must be one of the two competing approaches (ForecastMethod)"
    )


def test_r2_volatile_field_also_records_a_selected_method(volatile_forecast: FieldForecast) -> None:
    """002-R2: even a low-confidence field goes through selection and records a valid method.

    Selection is not skipped for a field that backtests poorly — the volatile field still names which
    of the two approaches it selected (the better of two poor candidates).
    """
    assert volatile_forecast.method in set(ForecastMethod)


# ============================================================ R3 — held-out backtest MAPE ==========


def test_r3_backtest_mape_is_recorded_as_a_non_negative_fraction(
    clean_forecast: FieldForecast,
) -> None:
    """002-R3: the selected approach's held-out MAPE is recorded as a fraction >= 0.

    A real error over the held-out final 24 months (principle 6) — a non-negative float. The exact
    value depends on the developer's fit; the credible bound is asserted next.
    """
    assert isinstance(clean_forecast.backtest_mape, float)
    assert clean_forecast.backtest_mape >= 0.0


def test_r3_clean_decline_backtests_below_the_credible_gate(
    clean_forecast: FieldForecast,
) -> None:
    """002-R3/R4: a clean Arps-shaped decline backtests **< 15% MAPE** on its held-out final 24.

    This is the representative "credible NCS field" of the acceptance criteria: holding out the last
    24 months and fitting the earlier history, the selected approach predicts them to within 15%.
    The synthetic series is built clean precisely so a correct backtest lands here; a forecaster that
    fed nulls as zero, mis-split the holdout, or mis-computed MAPE would miss this bound.
    """
    assert clean_forecast.backtest_mape < CREDIBLE_GATE, (
        f"clean-decline held-out MAPE must clear the {CREDIBLE_GATE:.0%} gate; "
        f"got {clean_forecast.backtest_mape:.4f}"
    )


# ============================================================ R4 — credibility (flagged, not hidden) =


def test_r4_clean_decline_is_classified_credible(clean_forecast: FieldForecast) -> None:
    """002-R4: the clean field is marked **credible** (and its MAPE indeed cleared the gate).

    The credible side of R4: ``credible is True`` *and* the recorded MAPE is below 0.15 — the flag
    and the metric agree on the happy path.
    """
    assert clean_forecast.credible is True
    assert clean_forecast.backtest_mape < CREDIBLE_GATE


def test_r4_volatile_field_still_produces_a_forecast(volatile_forecast: FieldForecast) -> None:
    """002-R4: a low-confidence field is **not hidden** — a ``FieldForecast`` is still produced.

    The "never silently dropped" half of R4: an erratic >= 60-month field yields a full, valid
    ``FieldForecast`` (24 points, all the scalar fields) — it is flagged, not omitted. (Only a
    *< 60-month* field yields no forecast — that is R5, in ``test_eligibility.py``.)
    """
    assert isinstance(volatile_forecast, FieldForecast)
    assert volatile_forecast.field_npdid == VOLATILE_NPDID
    assert len(volatile_forecast.points) == 24


def test_r4_volatile_field_is_classified_low_confidence(volatile_forecast: FieldForecast) -> None:
    """002-R4: the volatile field is marked **low-confidence** (``credible is False``, MAPE >= 0.15).

    The low-confidence side of R4: the best of the two approaches still can't predict this field's
    held-out 24 months to 15%, so it is flagged ``credible is False`` and its recorded MAPE is at or
    above the gate — the forecast is presented *with* the warning, never badged credible.
    """
    assert volatile_forecast.credible is False, (
        "a field whose selected backtest MAPE is >= 15% must be flagged low-confidence (R4)"
    )
    assert volatile_forecast.backtest_mape >= CREDIBLE_GATE, (
        f"the volatile field's selected MAPE must be at/above the {CREDIBLE_GATE:.0%} gate; "
        f"got {volatile_forecast.backtest_mape:.4f}"
    )


@pytest.mark.parametrize("fixture_name", ["clean_forecast", "volatile_forecast"])
def test_r4_credible_implies_below_gate_invariant(
    fixture_name: str, request: pytest.FixtureRequest
) -> None:
    """002-R4: the one-directional invariant ``credible`` => ``backtest_mape < 0.15`` on every forecast.

    The frozen contract enforces only that a credible forecast *must* have cleared the gate (never the
    reverse — the too-few-scorable-months guard may set ``credible=False`` even at low MAPE). Asserted
    on **both** produced forecasts (credible and low-confidence): a true ``credible`` always implies a
    sub-0.15 MAPE; a low-confidence one places no constraint on its MAPE here. This holds the same
    direction the ``FieldForecast`` validator does, so it can never go green by the contract being
    laxer than the spec.
    """
    forecast: FieldForecast = request.getfixturevalue(fixture_name)

    if forecast.credible:
        assert forecast.backtest_mape < CREDIBLE_GATE, (
            "a forecast flagged credible must have a backtest MAPE below the 15% gate (R4)"
        )
