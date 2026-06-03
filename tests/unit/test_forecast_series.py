"""Unit tests for ``ncs.forecast.series`` (developer-owned, white-box) — 002-T7 / R6.

White-box checks of the per-field oe series builder: the null/zero handling that is the crux of R6
(absent oe — ``None`` row or calendar hole — is missing/NaN, never 0; a real ``0.0`` is kept), the
calendar-spaced month offsets, the non-null ``history_months`` count, and the forward-month calendar
arithmetic the forecast points are stamped with. These exercise the series in isolation from any fit
or DuckDB, so a regression in the missing-data rule surfaces here directly.
"""

from __future__ import annotations

import math

import numpy as np

from ncs.contracts import MonthlyProduction
from ncs.forecast.series import build_series


def _row(npdid: int, year: int, month: int, oe: float | None) -> MonthlyProduction:
    return MonthlyProduction(
        field_npdid=npdid, field_name="F", year=year, month=month, oil_equivalents=oe
    )


def _consecutive(npdid: int, oes: list[float | None], start: tuple[int, int] = (2014, 1)):
    """Build consecutive monthly rows from ``start``; a ``None`` entry means a present None-oe row."""
    rows = []
    y, m = start
    for oe in oes:
        rows.append(_row(npdid, y, m, oe))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return rows


def test_clean_series_places_each_value_at_its_month_offset() -> None:
    """Each observed oe lands at ``t = 0, 1, 2…`` from the first observed month, in order."""
    rows = _consecutive(10, [5.0, 4.0, 3.0])

    series = build_series(rows)

    assert np.allclose(series.values, [5.0, 4.0, 3.0])
    assert series.first_year == 2014 and series.first_month == 1
    assert series.last_year == 2014 and series.last_month == 3
    assert series.history_months == 3


def test_none_oe_row_becomes_nan_not_zero() -> None:
    """A present row with ``oil_equivalents=None`` is a missing observation (NaN), never 0 (R6)."""
    rows = _consecutive(11, [5.0, None, 3.0])

    series = build_series(rows)

    assert math.isnan(series.values[1]), "None oe must be NaN (missing), not 0.0"
    assert series.values[0] == 5.0 and series.values[2] == 3.0
    assert series.history_months == 2, "the None month is not a non-null observation"


def test_calendar_hole_becomes_nan_not_zero() -> None:
    """A calendar month with no row at all (a hole) is NaN, spaced by its true offset (R6)."""
    # 2014-01 and 2014-03 present, 2014-02 entirely absent.
    rows = [_row(12, 2014, 1, 5.0), _row(12, 2014, 3, 3.0)]

    series = build_series(rows)

    assert len(series.values) == 3, "the series spans first→last observed inclusive (3 months)"
    assert series.values[0] == 5.0
    assert math.isnan(series.values[1]), "the absent middle month must be NaN, not 0.0"
    assert series.values[2] == 3.0
    assert series.history_months == 2


def test_none_row_and_absent_row_build_identical_series() -> None:
    """A None-oe gap row and a wholly-absent month produce the **same** series (R6 equivalence)."""
    via_none = build_series(_consecutive(13, [5.0, None, 3.0]))
    via_absent = build_series([_row(13, 2014, 1, 5.0), _row(13, 2014, 3, 3.0)])

    # NaN != NaN, so compare with equal_nan to assert structural identity.
    assert np.array_equal(via_none.values, via_absent.values, equal_nan=True)
    assert via_none.history_months == via_absent.history_months


def test_real_zero_is_kept_as_observation() -> None:
    """A real ``0.0`` oe month is a kept observation — counted, and not NaN (R6)."""
    rows = _consecutive(14, [5.0, 0.0, 3.0])

    series = build_series(rows)

    assert series.values[1] == 0.0, "a real 0.0 must be kept, not turned into NaN/missing"
    assert not math.isnan(series.values[1])
    assert series.history_months == 3, "the 0.0 month counts toward history_months"


def test_history_months_counts_only_non_null_observations() -> None:
    """``history_months`` counts non-null oe only — the 0.0 counts, the None does not (R6)."""
    rows = _consecutive(15, [5.0, 0.0, None, 2.0])  # 3 non-null (5.0, 0.0, 2.0), 1 None

    series = build_series(rows)

    assert series.history_months == 3


def test_rows_are_ordered_regardless_of_input_order() -> None:
    """Unordered input is sorted by ``(year, month)`` before placement (robust offsets)."""
    rows = [_row(16, 2014, 3, 3.0), _row(16, 2014, 1, 5.0), _row(16, 2014, 2, 4.0)]

    series = build_series(rows)

    assert np.allclose(series.values, [5.0, 4.0, 3.0])
    assert (series.first_year, series.first_month) == (2014, 1)
    assert (series.last_year, series.last_month) == (2014, 3)


def test_forecast_month_advances_and_wraps_the_year() -> None:
    """``forecast_month(step)`` advances calendar months after the last observed, wrapping 12→1."""
    # Last observed month 2014-12; step 1 → 2015-01, step 13 → 2016-01.
    rows = _consecutive(17, [5.0] * 12)  # 2014-01 .. 2014-12

    series = build_series(rows)

    assert series.forecast_month(1) == (2015, 1)
    assert series.forecast_month(12) == (2015, 12)
    assert series.forecast_month(13) == (2016, 1)


def test_empty_history_raises() -> None:
    """An empty history has no anchor → ``build_series`` raises ``ValueError``."""
    import pytest

    with pytest.raises(ValueError):
        build_series([])
