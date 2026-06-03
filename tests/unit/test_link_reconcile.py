"""Unit tests for ``ncs.link`` (developer-owned, white-box) — 001-T10 / R8.

White-box checks of the NPDID reconcile: the two unmatched lists are exactly the either-direction
set differences, de-duplicated despite the many-to-one fan-out, and matched NPDIDs land in neither
list. The acceptance suite proves the same against persisted data; here it is unit-level on the
function inputs (typed models), independent of the store.
"""

from __future__ import annotations

from ncs.contracts import Field, MonthlyProduction
from ncs.link import reconcile_npdids

_POLYGON = "POLYGON ((2.0 60.0, 2.5 60.0, 2.5 60.5, 2.0 60.5, 2.0 60.0))"


def _prod(npdid: int, year: int, month: int) -> MonthlyProduction:
    return MonthlyProduction(field_npdid=npdid, field_name=f"F{npdid}", year=year, month=month)


def _field(npdid: int) -> Field:
    return Field(field_npdid=npdid, field_name=f"F{npdid}", geometry_wkt=_POLYGON)


def test_either_direction_set_differences() -> None:
    """unmatched_production = prod − field; unmatched_field = field − prod (R8)."""
    production = [_prod(1001, 2022, 1), _prod(1002, 2022, 1), _prod(1009, 2023, 3)]
    fields = [_field(1001), _field(1002), _field(1004)]

    unmatched_production, unmatched_field = reconcile_npdids(production, fields)

    assert unmatched_production == [1009]  # in production, no field
    assert unmatched_field == [1004]  # a field, no production


def test_matched_npdids_appear_in_neither_list() -> None:
    """A NPDID present on both sides is reported unmatched in neither direction (R8)."""
    production = [_prod(1001, 2022, 1)]
    fields = [_field(1001)]

    unmatched_production, unmatched_field = reconcile_npdids(production, fields)

    assert 1001 not in unmatched_production
    assert 1001 not in unmatched_field
    assert unmatched_production == []
    assert unmatched_field == []


def test_many_to_one_does_not_duplicate_unmatched_npdid() -> None:
    """An unmatched production NPDID on many rows is reported once (de-duplicated, R8)."""
    production = [_prod(1009, 2023, 1), _prod(1009, 2023, 2), _prod(1009, 2023, 3)]
    fields: list[Field] = []

    unmatched_production, _ = reconcile_npdids(production, fields)

    assert unmatched_production == [1009]  # one entry despite three rows
    assert len(unmatched_production) == len(set(unmatched_production))


def test_results_are_sorted_and_duplicate_free() -> None:
    """Both lists come back sorted and without duplicates (a stable, clean result)."""
    production = [_prod(1009, 2023, 1), _prod(1007, 2022, 1), _prod(1007, 2022, 2)]
    fields = [_field(1005), _field(1004)]

    unmatched_production, unmatched_field = reconcile_npdids(production, fields)

    assert unmatched_production == [1007, 1009]
    assert unmatched_field == [1004, 1005]


def test_empty_inputs_yield_empty_lists() -> None:
    """No production and no fields → both unmatched lists are empty (no spurious entries)."""
    assert reconcile_npdids([], []) == ([], [])
