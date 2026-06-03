"""Unit tests for ``ncs.forecast.contracts`` (developer-owned, white-box) — 002-T6 / R7.

White-box checks of the frozen forecast models' cross-field invariants (the bodies the contract left
to ``src/``):

* exactly 24 forecast points (R1) — 23 or 25 is rejected;
* the **one-directional** ``credible`` ⟹ ``backtest_mape < 0.15`` invariant (R4): a credible forecast
  must clear the gate, but a low-MAPE forecast may still be ``credible=False`` (the producer's guard);
* the target is fixed to oil-equivalents (R1);
* models are frozen/strict and coerce plain strings to their enums — the exact behaviour the
  persistence round-trip relies on when it rebuilds a ``FieldForecast`` from DuckDB string columns.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ncs.forecast.contracts import (
    FieldForecast,
    ForecastMethod,
    ForecastPoint,
    ForecastRun,
    ForecastTarget,
)


def _points(n: int) -> list[ForecastPoint]:
    """``n`` well-formed forecast points (calendar is irrelevant to the count invariant)."""
    return [ForecastPoint(year=2020, month=(i % 12) + 1, value=1.0) for i in range(n)]


def _forecast(**overrides) -> FieldForecast:
    base = dict(
        field_npdid=1,
        points=_points(24),
        method=ForecastMethod.arps_decline,
        backtest_mape=0.05,
        credible=True,
        history_months=72,
    )
    base.update(overrides)
    return FieldForecast(**base)


def test_valid_forecast_constructs() -> None:
    fc = _forecast()
    assert fc.target is ForecastTarget.oil_equivalents
    assert len(fc.points) == 24


@pytest.mark.parametrize("n", [0, 23, 25])
def test_wrong_point_count_is_rejected(n: int) -> None:
    """Anything other than exactly 24 points is rejected (R1)."""
    with pytest.raises(ValidationError):
        _forecast(points=_points(n))


def test_credible_true_requires_mape_below_gate() -> None:
    """``credible=True`` with MAPE ≥ 0.15 violates the one-directional invariant (R4)."""
    with pytest.raises(ValidationError):
        _forecast(credible=True, backtest_mape=0.20)


def test_credible_true_at_exactly_the_gate_is_rejected() -> None:
    """The gate is strict ``< 0.15`` — credible at exactly 0.15 is not allowed (R4)."""
    with pytest.raises(ValidationError):
        _forecast(credible=True, backtest_mape=0.15)


def test_low_mape_may_still_be_low_confidence() -> None:
    """The converse is **not** enforced: ``credible=False`` at low MAPE is valid (the guard, R4)."""
    fc = _forecast(credible=False, backtest_mape=0.01)
    assert fc.credible is False
    assert fc.backtest_mape == 0.01


def test_high_mape_low_confidence_is_valid() -> None:
    """A flagged low-confidence forecast (MAPE ≥ 0.15, ``credible=False``) is constructable (R4)."""
    fc = _forecast(credible=False, backtest_mape=0.42)
    assert fc.credible is False


def test_negative_mape_is_rejected() -> None:
    """``backtest_mape`` is a non-negative fraction (``ge=0``)."""
    with pytest.raises(ValidationError):
        _forecast(backtest_mape=-0.01)


def test_history_months_below_sixty_is_rejected() -> None:
    """A ``FieldForecast`` cannot exist below the 60-month gate (R1, R5)."""
    with pytest.raises(ValidationError):
        _forecast(history_months=59)


def test_negative_point_value_is_rejected() -> None:
    """``ForecastPoint.value`` is clamped at ``ge=0`` — a negative oe is rejected (R1)."""
    with pytest.raises(ValidationError):
        ForecastPoint(year=2020, month=1, value=-0.5)


def test_point_month_out_of_range_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ForecastPoint(year=2020, month=13, value=1.0)


def test_extra_field_is_forbidden() -> None:
    """``extra='forbid'`` — a stray field is rejected (immutable value object)."""
    with pytest.raises(ValidationError):
        _forecast(unexpected="x")


def test_string_method_and_target_coerce_to_enums() -> None:
    """Plain strings coerce to the enums — the persistence round-trip depends on this (R8)."""
    fc = FieldForecast(
        field_npdid=1,
        target="oil_equivalents",
        points=_points(24),
        method="holt_damped",
        backtest_mape=0.05,
        credible=True,
        history_months=72,
    )
    assert fc.method is ForecastMethod.holt_damped
    assert fc.target is ForecastTarget.oil_equivalents


def test_model_round_trips_through_dump_and_validate() -> None:
    """A forecast re-validates from its own dump (the acceptance round-trip, in miniature)."""
    fc = _forecast()
    assert FieldForecast.model_validate(fc.model_dump()) == fc


def test_forecast_run_defaults_unforecastable_to_empty() -> None:
    """``ForecastRun.unforecastable_npdids`` defaults to an empty list (the common case)."""
    run = ForecastRun(forecasts=[], insufficient_history_npdids=[3])
    assert run.unforecastable_npdids == []
    assert run.insufficient_history_npdids == [3]
