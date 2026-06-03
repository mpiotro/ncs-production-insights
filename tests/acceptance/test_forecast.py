"""Acceptance suite: a forecast is produced and contract-valid — EARS 002-R1, 002-R7 (task 002-T2).

Black-box through the single ``Forecaster.forecast(history)`` seam (plan.md §Component shape),
driven by the shared synthetic ``clean_decline`` history (``forecast_histories.py``) — no DuckDB,
no network (the store is only touched by the persistence suite, T5).

* **002-R1** — "WHEN forecasting a field with at least 60 months of monthly production history, the
  system SHALL produce a 24-month forward forecast of its oil-equivalents production, one value per
  month following the field's last observed month." Acceptance here: ``forecast`` of a >= 60-month
  history returns a ``FieldForecast`` with **exactly 24** ``ForecastPoint``s whose calendar is the 24
  consecutive months **immediately after** the last observed month (month wraps 12 -> 1), targeting
  oil-equivalents, every value non-negative.

* **002-R7** — "WHEN a forecast is produced, the system SHALL emit a typed ``FieldForecast``
  recording the field NPDID, the 24 monthly forecast points, the selected approach, the backtest
  MAPE, and the credibility classification." Acceptance here: the result **is** a ``FieldForecast``
  (the frozen 002 contract) carrying the right ``field_npdid``, a ``method`` drawn from
  ``ForecastMethod``, a non-negative ``backtest_mape``, a ``credible`` bool, and
  ``history_months >= 60`` — i.e. it validates against the frozen model and round-trips through it.

These import ``ncs.forecast`` / ``ncs.forecast.contracts``, which do not exist yet, so the module is
**red at collection time** (TDD). It goes green when the developer implements 002-T6/T10 to the seam.
The assertions pin **outcomes** (24 points, the exact forward calendar, the contract shape), never
the fitting mechanism.
"""

from __future__ import annotations

from forecast_histories import (
    HORIZON,
    clean_decline,
    expected_forecast_months,
    last_observed_month,
)

# Frozen 002 seam (plan.md §Component shape; contracts.md). Module-scope imports make the whole suite
# go red for the right reason until ``ncs.forecast`` exists.
from ncs.forecast import Forecaster
from ncs.forecast.contracts import (
    FieldForecast,
    ForecastMethod,
    ForecastPoint,
    ForecastTarget,
)

# A stable NPDID + history length for this suite. 72 >= 60, so the field is forecastable (R1).
NPDID = 7201
HISTORY_MONTHS = 72


# ============================================================ R1 — 24-month forward forecast =======


def test_r1_forecast_returns_a_fieldforecast() -> None:
    """002-R1/R7: forecasting a >= 60-month history yields a ``FieldForecast`` for that field.

    The most basic R1/R7 outcome — the seam returns the frozen contract type, keyed to the field we
    asked about. Everything else in the suite refines the shape of that object.
    """
    result = Forecaster().forecast(clean_decline(NPDID, HISTORY_MONTHS))

    assert isinstance(result, FieldForecast)
    assert result.field_npdid == NPDID


def test_r1_forecast_has_exactly_24_points() -> None:
    """002-R1: the forecast carries **exactly 24** forward points (the fixed 24-month horizon).

    Not 23, not 25 — the horizon is spec-fixed and the ``FieldForecast`` validator enforces it; this
    asserts the producer actually fills it with 24 ``ForecastPoint``s.
    """
    result = Forecaster().forecast(clean_decline(NPDID, HISTORY_MONTHS))

    assert len(result.points) == HORIZON == 24
    assert all(isinstance(p, ForecastPoint) for p in result.points)


def test_r1_forecast_calendar_is_the_24_months_after_last_observed() -> None:
    """002-R1: the 24 points are the months **immediately following the last observed month**.

    The crux of R1's calendar clause. The history ends at ``last_observed_month(72)`` = 2019-12
    (2014-01 + 71 months); the forecast must therefore cover 2020-01 .. 2021-12, consecutively, with
    the month wrapping 12 -> 1 and the year incrementing. We compare the points' ``(year, month)``
    pairs to a calendar **independently re-derived** from the same anchor arithmetic the builder used,
    so the test pins the requirement, not the builder's internal state.
    """
    result = Forecaster().forecast(clean_decline(NPDID, HISTORY_MONTHS))

    got = [(p.year, p.month) for p in result.points]
    expected = expected_forecast_months(HISTORY_MONTHS)

    # Sanity-anchor the expectation so a regression in the helper itself can't hide a real bug:
    # 2014-01 + 71 months = 2019-12 is the last observed month; the forecast starts the next month.
    assert last_observed_month(HISTORY_MONTHS) == (2019, 12)
    assert expected[0] == (2020, 1)
    assert expected[-1] == (2021, 12)

    assert got == expected, (
        "forecast points must be the 24 consecutive months after the last observed month "
        f"(2020-01..2021-12); got {got[0]}..{got[-1]}"
    )


def test_r1_forecast_months_are_consecutive_and_well_formed() -> None:
    """002-R1: each point is a valid calendar month and the 24 advance by exactly one month each.

    A structural restatement of the calendar clause that does not depend on the specific anchor:
    every ``month`` is in 1..12, and stepping from one point to the next advances the absolute
    month index by exactly 1 (so no gaps, no repeats, correct year roll-over).
    """
    points = Forecaster().forecast(clean_decline(NPDID, HISTORY_MONTHS)).points

    for p in points:
        assert 1 <= p.month <= 12, f"month out of range: {p.month}"

    indices = [p.year * 12 + (p.month - 1) for p in points]
    steps = {b - a for a, b in zip(indices, indices[1:])}
    assert steps == {1}, f"forecast months must be strictly consecutive; saw step sizes {steps}"


def test_r1_forecast_values_are_non_negative() -> None:
    """002-R1: every forecast oil-equivalents value is >= 0 (a decline never predicts negative).

    The contract clamps ``ForecastPoint.value`` at ``ge=0``; this asserts the produced values honour
    it for a real fitted forecast (a model that would go negative is clamped at the producer).
    """
    points = Forecaster().forecast(clean_decline(NPDID, HISTORY_MONTHS)).points

    assert all(p.value >= 0 for p in points), (
        "forecast values must be non-negative oil-equivalents (million Sm3)"
    )


# ============================================================ R7 — typed FieldForecast emitted =====


def test_r7_target_is_oil_equivalents() -> None:
    """002-R7/R1: the forecast target is oil-equivalents — the single fixed quantity this cycle."""
    result = Forecaster().forecast(clean_decline(NPDID, HISTORY_MONTHS))

    assert result.target is ForecastTarget.oil_equivalents


def test_r7_method_is_a_member_of_the_forecast_method_enum() -> None:
    """002-R7/R2: the recorded ``method`` is one of the closed set of competing approaches.

    R7 requires the *selected approach* be recorded; here we assert only that it is a valid
    ``ForecastMethod`` member (which of the two was selected, and that selection minimises MAPE, is
    002-R2's job, asserted in ``test_backtest.py``).
    """
    result = Forecaster().forecast(clean_decline(NPDID, HISTORY_MONTHS))

    assert isinstance(result.method, ForecastMethod)
    assert result.method in set(ForecastMethod)


def test_r7_backtest_mape_is_a_non_negative_fraction() -> None:
    """002-R7/R3: a ``backtest_mape`` is recorded, as a non-negative fraction (0.12 => 12%).

    R7 requires the held-out MAPE be recorded on the artifact; here we assert it is present and a
    sane fraction (>= 0). The credibility relationship to 0.15 is asserted in ``test_backtest.py``.
    """
    result = Forecaster().forecast(clean_decline(NPDID, HISTORY_MONTHS))

    assert isinstance(result.backtest_mape, float)
    assert result.backtest_mape >= 0.0


def test_r7_credible_flag_is_present_and_boolean() -> None:
    """002-R7/R4: the credibility classification is recorded as a bool on the artifact."""
    result = Forecaster().forecast(clean_decline(NPDID, HISTORY_MONTHS))

    assert isinstance(result.credible, bool)


def test_r7_history_months_counts_at_least_sixty() -> None:
    """002-R7/R1/R5: ``history_months`` records the field's history length and is >= 60.

    For an all-observed 72-month clean decline, every month is a non-null oe observation, so the
    recorded ``history_months`` is exactly 72 (and necessarily >= 60 — a ``FieldForecast`` cannot be
    constructed below the gate).
    """
    result = Forecaster().forecast(clean_decline(NPDID, HISTORY_MONTHS))

    assert result.history_months >= 60
    assert result.history_months == HISTORY_MONTHS, (
        "an all-observed 72-month clean decline has 72 non-null oe observations"
    )


def test_r7_result_validates_as_the_frozen_fieldforecast_contract() -> None:
    """002-R7: the produced object round-trips through the frozen ``FieldForecast`` model.

    Re-validating the result's dumped data through ``FieldForecast`` proves it satisfies **all** the
    contract invariants at once (24 points, target fixed, credible-implies-gate, non-negative values,
    history_months >= 60) — i.e. what ``forecast`` emits is a genuine, valid instance of the frozen
    seam 003 serves and 004 charts, not merely a duck-typed look-alike.
    """
    result = Forecaster().forecast(clean_decline(NPDID, HISTORY_MONTHS))

    # Re-construct from the model's own dump: if any invariant were violated this raises.
    revalidated = FieldForecast.model_validate(result.model_dump())
    assert revalidated == result
