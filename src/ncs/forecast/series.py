"""Per-field oil-equivalents modelling series — calendar-spaced, gaps = missing (task 002-T7; R6).

Turns one field's ``Sequence[MonthlyProduction]`` into the regular monthly series both forecasting
approaches consume (plan.md §Building the per-field series). The single rule (R6):

* **Target = oil-equivalents only** (spec; locked). Other streams are ignored this cycle.
* **Calendar-spaced, monotonic in time.** Rows are ordered by ``(year, month)`` and placed at their
  integer **month offset** from the field's **first observed month** (``t = 0`` at the first month).
  ``t`` is the Arps time axis and a regular index for Holt.
* **Gaps are explicit missing (NaN), never 0.** Two kinds of "no value" both become missing:
  1. a ``MonthlyProduction`` row whose ``oil_equivalents is None`` (SODIR published the row, no oe);
  2. a calendar month with **no row at all** between the first and last observed months (a hole).
  A literal ``0.0`` oe (a real zero-production month) **stays 0.0** — it is an observation, not
  missing. This is the crux of R6 and mirrors 001's absent→null discipline exactly.

Because both kinds of gap collapse to the *same* NaN at the *same* offset, a history expressed with
``None`` gap rows builds a byte-identical ``MonthlySeries`` to one where those months are simply
absent — which is exactly the R6 equivalence the acceptance suite asserts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ncs.contracts import MonthlyProduction


def _absolute_month_index(year: int, month: int) -> int:
    """A strictly increasing integer index for a calendar ``(year, month)`` (month is 1–12).

    ``year*12 + (month-1)`` so consecutive months differ by exactly 1 and ordering / month-offset
    arithmetic is plain subtraction — the same primitive the forward calendar uses.
    """
    return year * 12 + (month - 1)


def _month_from_absolute_index(index: int) -> tuple[int, int]:
    """Inverse of :func:`_absolute_month_index` — ``(year, month)`` for an absolute month index."""
    return index // 12, (index % 12) + 1


@dataclass(frozen=True)
class MonthlySeries:
    """A field's calendar-spaced oe series for modelling (internal — not the frozen seam).

    * ``values`` — oe per month offset ``t = 0, 1, …`` from the first observed month, with ``np.nan``
      at every missing offset (absent calendar month, or a present row with ``oil_equivalents is
      None``). A real ``0.0`` is kept as ``0.0``. Length spans first→last **observed** month
      inclusive; leading/trailing absent months outside that span are not part of the series.
    * ``first_year`` / ``first_month`` — the calendar anchor of offset ``t = 0`` (the field's first
      observed month), the Arps ``t`` origin.
    * ``last_year`` / ``last_month`` — the field's **last observed** month; the forward forecast
      covers the 24 months *after* this (plan.md §History/horizon).
    """

    values: np.ndarray  # float array, np.nan = missing observation (R6)
    first_year: int
    first_month: int
    last_year: int
    last_month: int

    @property
    def history_months(self) -> int:
        """Count of **non-null** oe observations — the field's history length (R6, plan.md).

        Pure calendar holes and null-oe months do **not** count; a real ``0.0`` does. This is the
        figure recorded as ``FieldForecast.history_months`` and tested against the 60-month gate.
        """
        return int(np.count_nonzero(~np.isnan(self.values)))

    @property
    def observed_values(self) -> np.ndarray:
        """The non-NaN oe values in time order (the points an Arps fit sees; R6 excludes nulls)."""
        return self.values[~np.isnan(self.values)]

    @property
    def observed_offsets(self) -> np.ndarray:
        """The month offsets ``t`` at which an oe observation exists (companion to ``observed_values``)."""
        return np.nonzero(~np.isnan(self.values))[0]

    def forecast_month(self, step: int) -> tuple[int, int]:
        """The ``(year, month)`` ``step`` months after the **last observed** month (``step >= 1``).

        ``step = 1`` is the first forecast month; advancing the absolute month index wraps 12→1 and
        rolls the year, matching the calendar the acceptance suite re-derives independently (R1).
        """
        return _month_from_absolute_index(
            _absolute_month_index(self.last_year, self.last_month) + step
        )


def build_series(history: Sequence[MonthlyProduction]) -> MonthlySeries:
    """Build the calendar-spaced oe ``MonthlySeries`` from a field's monthly history (R6).

    Ordered by ``(year, month)``; each present row's ``oil_equivalents`` is placed at its month
    offset from the first observed month, ``np.nan`` filling absent offsets (calendar holes) — a row
    with ``oil_equivalents is None`` contributes a ``np.nan`` exactly like an absent month (R6: absent
    is missing, never 0; a real ``0.0`` is kept). Raises ``ValueError`` on an empty history (there is
    no series, and therefore no anchor, to build).
    """
    if not history:
        raise ValueError("cannot build a series from an empty production history")

    # Order by calendar so the first/last observed months and the offsets are well-defined. A field's
    # history may carry rows for the same month only once (PK in the store), but ordering is robust
    # regardless of input order.
    rows = sorted(history, key=lambda r: _absolute_month_index(r.year, r.month))

    first = rows[0]
    last = rows[-1]
    first_index = _absolute_month_index(first.year, first.month)
    last_index = _absolute_month_index(last.year, last.month)

    span = last_index - first_index + 1  # first→last observed month inclusive
    values = np.full(span, np.nan, dtype=float)

    for row in rows:
        offset = _absolute_month_index(row.year, row.month) - first_index
        # None oe ⇒ leave NaN (missing, R6); a real value (incl. 0.0) is placed as the observation.
        if row.oil_equivalents is not None:
            values[offset] = float(row.oil_equivalents)

    return MonthlySeries(
        values=values,
        first_year=first.year,
        first_month=first.month,
        last_year=last.year,
        last_month=last.month,
    )
