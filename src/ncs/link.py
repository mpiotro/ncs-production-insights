"""NPDID link reconcile — match production to fields, report the mismatches (T10; R8).

After both datasets normalize, reconcile by field NPDID (``MonthlyProduction.field_npdid`` =
``Field.field_npdid``), many production rows → one field (plan.md §Link). This module computes only
the two **unmatched** sets; it drops nothing — the unmatched records are still persisted and counted
elsewhere. The mismatch is *reported* (R8), never used to filter.

- ``unmatched_production_npdids`` = production NPDIDs with **no** matching ``Field``.
- ``unmatched_field_npdids``      = field NPDIDs **absent** from production.

Each list is de-duplicated (a production NPDID appears on many rows but is reported once) and sorted
for a stable, readable result; the contract types both as ``list[int]`` and promises no ordering, so
sorting is a courtesy, not a contract.
"""

from __future__ import annotations

from collections.abc import Iterable

from ncs.contracts import Field, MonthlyProduction


def reconcile_npdids(
    production: Iterable[MonthlyProduction], fields: Iterable[Field]
) -> tuple[list[int], list[int]]:
    """Return ``(unmatched_production_npdids, unmatched_field_npdids)`` as the set differences (R8).

    Builds the distinct NPDID set on each side and takes the two one-directional differences:
    production-only NPDIDs and field-only NPDIDs. Matched NPDIDs (present on both sides) appear in
    neither list. Sorted and duplicate-free.
    """
    production_npdids = {record.field_npdid for record in production}
    field_npdids = {field.field_npdid for field in fields}

    unmatched_production = sorted(production_npdids - field_npdids)
    unmatched_field = sorted(field_npdids - production_npdids)
    return unmatched_production, unmatched_field
