"""Unit tests for ``ncs.forecast.forecaster`` (developer-owned, white-box) — 002-T10 / R1, R4, R5.

White-box checks of the ``Forecaster`` orchestration — the parts the acceptance suite can't easily
reach with its synthetic fixtures:

* the < 60-month eligibility boundary raises ``InsufficientHistoryError`` (R5), exactly at 59/60;
* the ``MIN_SCORABLE`` guard forces ``credible=False`` even when the numeric MAPE clears the gate —
  the credibility safeguard (R4), driven here by patching ``select`` to report too few scorable months;
* the forward forecast is a refit on the **full** history projecting the 24 months after the last
  observed month, with the right calendar stamps (R1);
* a selected approach that backtests but fails to refit on full history surfaces as
  ``AllApproachesFailedError`` (plan edge case), not an uncaught crash.
"""

from __future__ import annotations

import numpy as np
import pytest

from ncs.contracts import MonthlyProduction
from ncs.forecast import backtest as bt
from ncs.forecast import forecaster as fmod
from ncs.forecast.backtest import AllApproachesFailedError, Selection
from ncs.forecast.contracts import ForecastMethod, ForecastTarget
from ncs.forecast.forecaster import Forecaster, InsufficientHistoryError


def _hyperbolic(t: float) -> float:
    return 5.0 / (1.0 + 0.5 * 0.03 * t) ** (1.0 / 0.5)


def _clean(npdid: int, months: int) -> list[MonthlyProduction]:
    """A clean hyperbolic decline of ``months`` consecutive months from 2014-01 (all observed)."""
    rows = []
    y, m = 2014, 1
    for t in range(months):
        rows.append(
            MonthlyProduction(
                field_npdid=npdid, field_name="F", year=y, month=m, oil_equivalents=_hyperbolic(t)
            )
        )
        m += 1
        if m > 12:
            m = 1
            y += 1
    return rows


# --- eligibility (R5) ------------------------------------------------------------------------------


def test_fifty_nine_months_raises_insufficient_history() -> None:
    with pytest.raises(InsufficientHistoryError):
        Forecaster().forecast(_clean(1, 59))


def test_sixty_months_is_eligible() -> None:
    result = Forecaster().forecast(_clean(2, 60))
    assert result.history_months == 60
    assert result.field_npdid == 2


def test_insufficient_history_counts_only_non_null_oe() -> None:
    """A field with 70 rows but only 50 non-null oe months is still insufficient (R5/R6)."""
    rows = _clean(3, 70)
    # Null out 20 of the oe values → 50 non-null observations (< 60), even though 70 rows exist.
    nulled = [
        MonthlyProduction(
            field_npdid=r.field_npdid,
            field_name=r.field_name,
            year=r.year,
            month=r.month,
            oil_equivalents=None if i < 20 else r.oil_equivalents,
        )
        for i, r in enumerate(rows)
    ]
    with pytest.raises(InsufficientHistoryError):
        Forecaster().forecast(nulled)


# --- the MIN_SCORABLE guard forces low-confidence (R4) --------------------------------------------


def test_guard_forces_low_confidence_even_below_gate(monkeypatch) -> None:
    """Too few scorable months ⇒ ``credible=False`` despite ``backtest_mape < 0.15`` (R4 safeguard).

    Patch ``select`` to report a low MAPE but a scorable count below ``MIN_SCORABLE`` — the producer
    must classify the forecast low-confidence even though the numeric MAPE clears the gate. (The
    frozen contract permits ``credible=False`` at low MAPE; it forbids only the reverse.)
    """

    def _fake_select(series):
        return Selection(
            method=ForecastMethod.arps_decline,
            backtest_mape=0.01,  # well below the 0.15 gate
            scorable_months=bt.MIN_SCORABLE - 1,  # but too few scorable months
        )

    monkeypatch.setattr(fmod, "select", _fake_select)

    result = Forecaster().forecast(_clean(4, 72))

    assert result.backtest_mape == 0.01
    assert result.credible is False, "the scorable-months guard must force low-confidence (R4)"


def test_enough_scorable_below_gate_is_credible(monkeypatch) -> None:
    """At/above ``MIN_SCORABLE`` scorable months and MAPE < gate ⇒ credible (the happy path, R4)."""

    def _fake_select(series):
        return Selection(
            method=ForecastMethod.arps_decline,
            backtest_mape=0.05,
            scorable_months=bt.MIN_SCORABLE,
        )

    monkeypatch.setattr(fmod, "select", _fake_select)

    result = Forecaster().forecast(_clean(5, 72))

    assert result.credible is True


# --- forward forecast shape & calendar (R1) -------------------------------------------------------


def test_forward_forecast_has_24_points_after_last_observed() -> None:
    """The forward points are the 24 consecutive months after the last observed month (R1)."""
    result = Forecaster().forecast(_clean(6, 72))  # 2014-01 .. 2019-12

    cal = [(p.year, p.month) for p in result.points]
    assert len(cal) == 24
    assert cal[0] == (2020, 1)
    assert cal[-1] == (2021, 12)
    # strictly consecutive
    idx = [y * 12 + (m - 1) for (y, m) in cal]
    assert {b - a for a, b in zip(idx, idx[1:])} == {1}
    assert result.target is ForecastTarget.oil_equivalents


def test_forward_refit_failure_raises_all_approaches_failed(monkeypatch) -> None:
    """A selected approach that backtests but fails the full-history refit surfaces as the edge case."""
    from ncs.forecast.methods import FitError

    def _fake_select(series):
        return Selection(
            method=ForecastMethod.arps_decline, backtest_mape=0.05, scorable_months=24
        )

    def _fail_forward(series, horizon):
        raise FitError("refit failed")

    monkeypatch.setattr(fmod, "select", _fake_select)
    # Patch the forward fit registry entry for the selected method.
    monkeypatch.setitem(fmod._FORWARD_FIT, ForecastMethod.arps_decline, _fail_forward)

    with pytest.raises(AllApproachesFailedError):
        Forecaster().forecast(_clean(7, 72))


def test_forward_values_are_clamped_non_negative(monkeypatch) -> None:
    """Forward values are non-negative — a model that would go negative is clamped at the producer."""
    result = Forecaster().forecast(_clean(8, 72))
    assert all(p.value >= 0 for p in result.points)
    assert np.isfinite([p.value for p in result.points]).all()
