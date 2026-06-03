"""Acceptance suite: eligibility & absent-is-missing — EARS 002-R5, 002-R6 (task 002-T4).

Black-box through ``Forecaster.forecast(history)`` on synthetic histories
(``forecast_histories.py``). Two requirements, the second being the null-vs-zero crux:

* **002-R5** — "IF a field has fewer than 60 months of production history, THEN the system SHALL NOT
  produce a credible forecast for it and SHALL record it as insufficient-history." Acceptance at the
  single-field seam: ``forecast`` of a < 60-month history **raises ``InsufficientHistoryError``** —
  the absence of a ``FieldForecast`` *is* the R5 outcome (a < 60-month ``FieldForecast`` is
  unconstructable, ``history_months >= 60``). The run-level collection into
  ``ForecastRun.insufficient_history_npdids`` is exercised in the persistence suite (T5).

* **002-R6** — "WHEN fitting a series or computing MAPE, the system SHALL treat an absent (null)
  monthly oil-equivalents value as a missing observation, never as zero production." Acceptance — the
  **None ≡ missing ≡ absent** equivalence: a history with explicit ``oil_equivalents=None`` rows for
  the gap months must forecast **identically** to one where those same months are simply **not
  present** (no row at all). And a real ``0.0`` oe month is an *observation* that is **kept** — it
  must not be deleted as if missing, nor must the ``None`` months drag the fit toward zero.
  ``history_months`` counts only **non-null** oe observations (the ``0.0`` counts; the ``None``s do
  not).

Red at collection time until 002-T7 (series build, gaps = missing) and 002-T10 (the < 60 raise).
The two ``with_gaps`` variants differ **only** in how the absent months are expressed, so any
difference in their forecasts is exactly a violation of R6.
"""

from __future__ import annotations

import pytest

from forecast_histories import (
    GAP_NONE_OFFSETS,
    GAP_ZERO_OFFSET,
    MIN_HISTORY_MONTHS,
    add_months,
    clean_decline,
    expected_history_months_with_gaps,
    short_history,
    with_gaps,
)

from ncs.forecast import Forecaster, InsufficientHistoryError
from ncs.forecast.contracts import FieldForecast

SHORT_NPDID = 7401
GAPS_NPDID = 7402
GAPS_MONTHS = 72


# ============================================================ R5 — < 60 months => no forecast ======


def test_r5_short_history_raises_insufficient_history() -> None:
    """002-R5: a field with < 60 months of oe history raises ``InsufficientHistoryError``.

    A 40-month clean decline is below the 60-month gate, so ``forecast`` must refuse it rather than
    return a non-credible stand-in — the raise *is* the insufficient-history outcome at this seam.
    """
    history = short_history(SHORT_NPDID, months=40)

    with pytest.raises(InsufficientHistoryError):
        Forecaster().forecast(history)


def test_r5_just_below_threshold_raises() -> None:
    """002-R5 (boundary): 59 observed months is still insufficient — the gate is >= 60, not > 59.

    Pins the exact threshold so an off-by-one (treating 59 as enough, leaving train < 36 for the
    24-month holdout) is caught. 59 is one short of the 60 the spec fixes.
    """
    history = short_history(SHORT_NPDID, months=MIN_HISTORY_MONTHS - 1)  # 59

    with pytest.raises(InsufficientHistoryError):
        Forecaster().forecast(history)


def test_r5_sixty_months_is_eligible() -> None:
    """002-R5/R1 (boundary, the other side): exactly 60 observed months **is** forecastable.

    The complement of the boundary test: at the threshold the field is eligible, so ``forecast``
    returns a ``FieldForecast`` (it must *not* raise). 60 observed months => train = 36, test = 24 —
    the minimal valid split. Confirms the gate is ``>= 60`` inclusive, exactly as designed.
    """
    result = Forecaster().forecast(clean_decline(SHORT_NPDID, months=60))

    assert isinstance(result, FieldForecast)
    assert result.history_months == 60


# ============================================================ R6 — absent oe is missing, never 0 ===


def _forecast_gaps(*, drop_missing: bool) -> FieldForecast:
    """Forecast the ``with_gaps`` field, gaps expressed as ``None`` rows or as absent rows."""
    return Forecaster().forecast(
        with_gaps(GAPS_NPDID, GAPS_MONTHS, drop_missing=drop_missing)
    )


def test_r6_none_rows_equal_absent_rows() -> None:
    """002-R6: ``None``-oe rows forecast **identically** to wholly-absent rows (None ≡ missing ≡ absent).

    The crux of R6. ``with_gaps`` is built two ways that differ *only* in how the gap months are
    expressed — explicit ``oil_equivalents=None`` rows vs no row at all for those months — and every
    other month is identical. A forecaster that treats absent-as-missing must produce the **same**
    ``FieldForecast`` from both. Equality of the full frozen models (points + every scalar field)
    means the ``None`` rows contributed nothing the missing rows didn't: they were excluded, not fed
    in as data (and certainly not as zeros).
    """
    via_none = _forecast_gaps(drop_missing=False)
    via_absent = _forecast_gaps(drop_missing=True)

    assert via_none == via_absent, (
        "a history with None-oe gap rows must forecast identically to one where those months are "
        "absent — None must be treated as a missing observation, not as data/zero (R6)"
    )


def test_r6_history_months_counts_only_non_null_observations() -> None:
    """002-R6: ``history_months`` counts only **non-null** oe observations (the ``0.0`` counts).

    The absent months (``None`` or dropped) are *not* observations, so they don't count toward the
    60-month history; the real ``0.0`` month *is* an observation and does. For the 72-month
    ``with_gaps`` series with two absent months, that is exactly 70 — and both expression variants
    must agree on it (the absent rows can't inflate the count).
    """
    expected = expected_history_months_with_gaps(GAPS_MONTHS)  # 72 - 2 = 70
    assert expected == 70  # anchor the arithmetic so a helper regression can't mask a real bug

    via_none = _forecast_gaps(drop_missing=False)
    via_absent = _forecast_gaps(drop_missing=True)

    assert via_none.history_months == expected, (
        "history_months must count only non-null oe observations; the two absent months must not "
        f"count and the real 0.0 month must (expected {expected})"
    )
    assert via_absent.history_months == expected


def test_r6_gappy_field_is_still_forecastable_and_credible() -> None:
    """002-R6/R1: 70 non-null months (>= 60) is forecastable, and the clean shape stays credible.

    The gaps don't break eligibility (70 >= 60) and — because the underlying series is the same clean
    decline as the credible case, merely with two months excluded and one genuine zero kept — the
    backtest still clears the gate. This guards against the ``None`` months poisoning the fit (e.g.
    being read as zeros, which would distort the held-out error).
    """
    result = _forecast_gaps(drop_missing=False)

    assert isinstance(result, FieldForecast)
    assert result.history_months >= 60
    assert result.credible is True
    assert result.backtest_mape < 0.15


def test_r6_real_zero_month_is_kept_not_collapsed() -> None:
    """002-R6: a real ``0.0`` oe month is **kept** as an observation — the fit isn't collapsed to zero.

    Two pieces of evidence that ``0.0`` is "present and zero" (not missing, and not allowed to drag
    the whole forecast down):

    1. The ``0.0`` month counts toward ``history_months`` — already implied by the count being 70
       (72 minus the two *absent* months only); if the ``0.0`` were dropped as missing the count
       would be 69. We re-assert it here as the explicit "kept" check.
    2. The forward forecast is **not** collapsed toward zero: a clean decline's 24 forward oe values
       are not all ~0. We assert the forecast retains real positive production (its max is clearly
       above zero), so the single ``0.0`` interior month did not zero-out the fit, and the ``None``
       months were not silently turned into a run of zeros either.
    """
    result = _forecast_gaps(drop_missing=False)

    # (1) the 0.0 month was kept as an observation (70 = 72 - 2 absent; the zero is counted).
    assert result.history_months == 70

    # (2) the forward forecast still carries genuine production — not collapsed toward zero.
    values = [p.value for p in result.points]
    assert max(values) > 0.1, (
        "the forward forecast collapsed toward zero — a single real 0.0 month (or None-as-zero) must "
        "not zero-out a clean decline fit (R6)"
    )


def test_r6_special_months_are_interior_to_the_series() -> None:
    """002-R6 (guard on the fixture): the special months sit inside the series, not at its ends.

    A guard so the equivalence/kept-zero assertions are meaningful: the ``None`` gap months and the
    real ``0.0`` month must be **interior** offsets (neither the first month nor the last), so they
    genuinely exercise the series-interior null handling and the holdout window — not a trailing edge
    the split would ignore. Pins the fixture's design, surfacing drift here rather than as a confusing
    failure elsewhere.
    """
    last_offset = GAPS_MONTHS - 1
    special = (*GAP_NONE_OFFSETS, GAP_ZERO_OFFSET)

    for offset in special:
        assert 0 < offset < last_offset, (
            f"special month offset {offset} must be interior to the 0..{last_offset} series"
        )

    # And the special months are distinct calendar months (no None/zero collision).
    special_months = {add_months((2014, 1), off) for off in special}
    assert len(special_months) == len(special), "special months must be distinct calendar months"
