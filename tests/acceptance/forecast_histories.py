"""Shared synthetic ``MonthlyProduction`` histories for the 002 forecasting acceptance suites.

These are **plain builder functions** (no pytest, no fixtures) imported by the four 002 suites
(``test_forecast`` / ``test_backtest`` / ``test_eligibility`` / ``test_forecast_persistence``).
They construct ``list[MonthlyProduction]`` series with **known, controlled properties** so each
EARS requirement can be asserted black-box through the ``Forecaster.forecast(history)`` seam
without any SODIR CSV or network (tasks.md §Resolved — "forecasting wants controlled series with
known properties").

Every series is built only from the **frozen 001** ``MonthlyProduction`` contract
(``ncs.contracts``): ``field_npdid``/``field_name``/``year``/``month`` are required; every stream
volume (including ``oil_equivalents``) is optional and defaults to ``None`` ("SODIR published no
value", distinct from a real ``0.0`` — 001-R6 / 002-R6).

Calendar anchoring (so the 24 forecast months are predictable)
--------------------------------------------------------------
All histories start at a fixed anchor **2014-01** and run consecutively month-by-month (month wraps
12 -> 1, year increments). A history of ``months`` observed months therefore has a **last observed
month** of ``add_months((2014, 1), months - 1)``; the forecast covers ``months 1..24`` after that.
The month arithmetic helpers below are the single source of truth for that calendar; the suites
re-derive expected forecast ``(year, month)`` pairs from the same helpers rather than trusting a
builder's internal bookkeeping.

The builders, and what each one is designed to prove
----------------------------------------------------
* ``clean_decline(npdid, months=72)`` — a smooth (hyperbolic) oe decline with mild deterministic
  noise over >= 60 months. Designed to backtest **credible** (selected MAPE < 0.15): the R1/R2/R4
  "happy path" and the credible side of R4.
* ``short_history(npdid, months=40)`` — a clean decline but **< 60 observed oe months**: the R5
  insufficient-history case (``forecast`` must raise ``InsufficientHistoryError``).
* ``with_gaps(npdid, ...)`` — a clean decline >= 60 oe months carrying **both** a real ``0.0`` oe
  month (genuine zero production, kept as an observation) **and** at least one absent oe month; the
  absent month can be expressed either as an explicit ``oil_equivalents=None`` row or as a wholly
  missing calendar row (``drop_missing=True``). This is the R6 ``None`` ≡ missing ≡ absent crux.
* ``volatile(npdid, months=72)`` — >= 60 oe months but **erratic** (large swings) so that the best
  backtest MAPE is **>= 0.15**: the low-confidence side of R4 (``credible is False``, still a
  ``FieldForecast`` — "flagged, not hidden").

Determinism: every series uses a fixed seed / closed-form noise so the suites are reproducible (no
``random`` global state). Noise is small relative to level for the clean series and large for the
volatile one — that contrast is what makes the credible-vs-low-confidence split robust.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from ncs.contracts import MonthlyProduction

# --- Fixed calendar anchor: every synthetic history starts here (2014-01) -------------------------
ANCHOR_YEAR: int = 2014
ANCHOR_MONTH: int = 1

# The spec-fixed forecast horizon and eligibility threshold, restated here only so the *expected*
# values in the suites read off named constants (they are NOT imported from src — the suites assert
# the implementation honours them).
HORIZON: int = 24
MIN_HISTORY_MONTHS: int = 60


def add_months(anchor: tuple[int, int], offset: int) -> tuple[int, int]:
    """Return the ``(year, month)`` ``offset`` calendar months after ``anchor`` (month wraps 12->1).

    ``offset`` may be 0 (the anchor itself) or any positive integer. This is the single month-
    arithmetic primitive both the builders and the suites use, so an "expected forecast calendar"
    in a test is derived the same way the history's own months are.
    """
    year, month = anchor
    # months are 1-based; shift into 0-based, add, then shift back.
    total = (year * 12 + (month - 1)) + offset
    return total // 12, (total % 12) + 1


def month_sequence(anchor: tuple[int, int], count: int) -> list[tuple[int, int]]:
    """The ``count`` consecutive ``(year, month)`` pairs starting at ``anchor`` (inclusive)."""
    return [add_months(anchor, i) for i in range(count)]


def last_observed_month(months: int, anchor: tuple[int, int] = (ANCHOR_YEAR, ANCHOR_MONTH)) -> tuple[int, int]:
    """The ``(year, month)`` of the **last** observed month of a ``months``-long history from ``anchor``."""
    return add_months(anchor, months - 1)


def expected_forecast_months(
    history_len: int,
    anchor: tuple[int, int] = (ANCHOR_YEAR, ANCHOR_MONTH),
    horizon: int = HORIZON,
) -> list[tuple[int, int]]:
    """The ``horizon`` ``(year, month)`` pairs a forecast must cover: the months **after** the last.

    These are the months ``1..horizon`` following ``last_observed_month(history_len)`` — exactly the
    forward calendar 002-R1 fixes. The suites compare ``[(p.year, p.month) for p in points]`` to this.
    """
    last = last_observed_month(history_len, anchor)
    # The first forecast month is one month *after* the last observed month.
    first_forecast = add_months(last, 1)
    return month_sequence(first_forecast, horizon)


# --- Small deterministic noise (no global RNG state) ----------------------------------------------


def _wobble(t: int, amplitude: float) -> float:
    """A deterministic, mean-near-zero multiplicative wobble in roughly ``[-amplitude, +amplitude]``.

    A closed-form function of the month offset ``t`` (two incommensurate sinusoids) — reproducible
    with no seed, and not a pure trend the models could fit away. ``amplitude`` controls how noisy
    the series is: small for the clean/credible series, large for the volatile/low-confidence one.
    """
    return amplitude * (math.sin(t * 1.7) + 0.5 * math.cos(t * 0.9))


# --- The builders ---------------------------------------------------------------------------------

_DEFAULT_NAME = "SYNTH"


def _hyperbolic_oe(t: int, q_i: float, d_i: float, b: float) -> float:
    """Arps hyperbolic rate ``q(t) = q_i / (1 + b*d_i*t) ** (1/b)`` (the clean-decline backbone)."""
    return q_i / (1.0 + b * d_i * t) ** (1.0 / b)


def clean_decline(
    npdid: int,
    months: int = 72,
    *,
    field_name: str = _DEFAULT_NAME,
    q_i: float = 5.0,
    d_i: float = 0.03,
    b: float = 0.5,
    noise: float = 0.01,
) -> list[MonthlyProduction]:
    """A smooth hyperbolic oil-equivalents decline over ``months`` (>= 60) consecutive months.

    Designed to **backtest credible** (selected MAPE < 0.15): a clean Arps-shaped decline with only
    mild deterministic wobble, so both candidate approaches extrapolate the held-out final 24 months
    well. Every month carries a real ``oil_equivalents`` value (no gaps, no nulls), so
    ``history_months == months``. Starts at the fixed 2014-01 anchor (predictable forecast calendar).

    The decline is steep-early / flattening-tail (hyperbolic with ``b`` in ``(0, 1]``), matching how
    NCS oil fields actually decline — the shape ``plan.md`` §Approach A fits.
    """
    rows: list[MonthlyProduction] = []
    for t, (year, month) in enumerate(month_sequence((ANCHOR_YEAR, ANCHOR_MONTH), months)):
        level = _hyperbolic_oe(t, q_i, d_i, b)
        oe = level * (1.0 + _wobble(t, noise))
        rows.append(
            MonthlyProduction(
                field_npdid=npdid,
                field_name=field_name,
                year=year,
                month=month,
                oil_equivalents=max(oe, 0.0),
            )
        )
    return rows


def short_history(
    npdid: int,
    months: int = 40,
    *,
    field_name: str = _DEFAULT_NAME,
) -> list[MonthlyProduction]:
    """A clean decline with **fewer than 60** observed oe months — the R5 insufficient-history case.

    Same shape as ``clean_decline`` but only ``months`` (default 40 < 60) long, so a forecaster must
    refuse it: ``Forecaster.forecast`` raises ``InsufficientHistoryError`` and ``run_forecasts``
    records the NPDID in ``ForecastRun.insufficient_history_npdids``. ``months`` defaults below the
    60-month gate; callers may pass any value to probe the boundary.
    """
    assert months < MIN_HISTORY_MONTHS, (
        f"short_history must be < {MIN_HISTORY_MONTHS} months to exercise R5; got {months}"
    )
    return clean_decline(npdid, months, field_name=field_name)


# Offsets (months from the 2014-01 anchor) at which ``with_gaps`` places its special months.
# Chosen to sit comfortably *inside* the series (neither first nor last) so they affect the fit/
# series interior, and away from each other.
GAP_NONE_OFFSETS: tuple[int, ...] = (20, 33)   # absent oe months (None-row, or dropped row)
GAP_ZERO_OFFSET: int = 27                       # a real 0.0 oe month (genuine zero production)


def with_gaps(
    npdid: int,
    months: int = 72,
    *,
    field_name: str = _DEFAULT_NAME,
    drop_missing: bool = False,
) -> list[MonthlyProduction]:
    """A clean >= 60-month decline carrying the R6 crux: an absent oe month **and** a real ``0.0``.

    Built two interchangeable ways so the suite can prove **None ≡ missing ≡ absent**:

    * ``drop_missing=False`` (default) — the absent months (``GAP_NONE_OFFSETS``) are present rows
      with ``oil_equivalents=None`` (SODIR published the row but no oe value).
    * ``drop_missing=True`` — those same calendar months have **no row at all** (a hole in the
      series). Every other month is byte-for-byte identical to the ``None`` variant.

    A forecaster that treats absent-as-missing (002-R6) must produce the **same** ``FieldForecast``
    from both variants. The ``GAP_ZERO_OFFSET`` month always carries a real ``oil_equivalents=0.0``
    — a genuine zero-production observation that must be **kept** (not deleted as if missing, and not
    confused with the ``None`` months); it must not collapse the fit toward zero.

    Because the absent months are *not* counted as observations (002-R6), the number of non-null oe
    rows is ``months - len(GAP_NONE_OFFSETS)`` (the ``0.0`` month **does** count — it is observed).
    ``months`` defaults to 72 so that count stays comfortably >= 60. See
    ``expected_history_months_with_gaps`` for the exact figure.
    """
    rows: list[MonthlyProduction] = []
    none_offsets = set(GAP_NONE_OFFSETS)
    for t, (year, month) in enumerate(month_sequence((ANCHOR_YEAR, ANCHOR_MONTH), months)):
        if t in none_offsets:
            if drop_missing:
                # No row at all for this calendar month — a wholly absent observation.
                continue
            # Present row, but oe is explicitly absent (None) — distinct from 0.0.
            rows.append(
                MonthlyProduction(
                    field_npdid=npdid,
                    field_name=field_name,
                    year=year,
                    month=month,
                    oil_equivalents=None,
                )
            )
            continue

        if t == GAP_ZERO_OFFSET:
            # A real zero-production month — an *observation* of 0.0, kept in the series (R6).
            oe = 0.0
        else:
            level = _hyperbolic_oe(t, 5.0, 0.03, 0.5)
            oe = max(level * (1.0 + _wobble(t, 0.01)), 0.0)

        rows.append(
            MonthlyProduction(
                field_npdid=npdid,
                field_name=field_name,
                year=year,
                month=month,
                oil_equivalents=oe,
            )
        )
    return rows


def expected_history_months_with_gaps(months: int = 72) -> int:
    """Non-null oe observation count for ``with_gaps`` — the ``history_months`` R6 expects.

    Absent (``None`` / dropped) months do **not** count; the real ``0.0`` month does. So it is
    ``months - len(GAP_NONE_OFFSETS)`` (both variants agree — that is the point of R6).
    """
    return months - len(GAP_NONE_OFFSETS)


def volatile(
    npdid: int,
    months: int = 72,
    *,
    field_name: str = _DEFAULT_NAME,
) -> list[MonthlyProduction]:
    """A >= 60-month oe series that is **erratic** — engineered so the best backtest MAPE is >= 0.15.

    The low-confidence side of 002-R4: a field that still yields a ``FieldForecast`` (it has >= 60 oe
    months) but is marked ``credible is False`` — *flagged, not hidden*. The series has a modest
    underlying level with **large, non-decline swings** (big closed-form wobble) so neither a
    monotone Arps decline nor a damped Holt trend can predict the held-out final 24 months to within
    15% — the selected MAPE lands above the gate.

    Values are kept strictly positive (so the MAPE denominator has plenty of scorable months — the
    low confidence comes from *error*, not from too-few-positive actuals). No gaps, no nulls, so
    ``history_months == months``.
    """
    rows: list[MonthlyProduction] = []
    base = 3.0
    for t, (year, month) in enumerate(month_sequence((ANCHOR_YEAR, ANCHOR_MONTH), months)):
        # Big multi-frequency swing around a gently drifting base — erratic, not a clean trend.
        swing = (
            math.sin(t * 1.3) * 1.6
            + math.cos(t * 0.55) * 1.3
            + math.sin(t * 2.9) * 0.9
        )
        oe = base + swing + 0.4 * math.sin(t * 0.13)
        # Keep strictly positive so every held-out month is MAPE-scorable (>0 actual).
        rows.append(
            MonthlyProduction(
                field_npdid=npdid,
                field_name=field_name,
                year=year,
                month=month,
                oil_equivalents=max(oe, 0.2),
            )
        )
    return rows


# --- Convenience: flatten a set of histories into rows for direct DuckDB seeding ------------------


def all_rows(*histories: Sequence[MonthlyProduction]) -> list[MonthlyProduction]:
    """Concatenate several histories into one ``list[MonthlyProduction]`` (store-seeding helper).

    The persistence suite seeds ``monthly_production`` from several fields at once; this keeps that
    call site readable. Pure data — no DuckDB, no pytest.
    """
    rows: list[MonthlyProduction] = []
    for history in histories:
        rows.extend(history)
    return rows
