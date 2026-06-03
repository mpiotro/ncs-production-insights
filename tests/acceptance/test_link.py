"""Acceptance suite: NPDID link reconcile — EARS 001-R8 (task 001-T4).

R8: "The system SHALL link each ``MonthlyProduction`` record to a ``Field`` through the field
NPDID (``prfNpdidInformationCarrier`` = ``fldNpdidField``)." Its acceptance criterion: *each
production record's ``field_npdid`` either resolves to a ``Field`` or appears in the report* — and
(plan.md §Link) the link is **many production → one field**, with mismatches in **either** direction
**reported, never dropped**. R8 therefore has two halves this suite pins:

* **reported** — the two ``IngestionReport.unmatched_*`` lists are exactly the either-direction
  mismatch sets, contain the matched NPDIDs in neither list, and are duplicate-free; and the set
  algebra that produces them holds against the *persisted* data (not just a hardcoded answer).
* **kept** — every unmatched record still has its row in DuckDB after the run; nothing is dropped.

All tests are black-box through the public seam ``ingest(con, settings)`` against the shared
canonical SODIR fixtures (``fixtures/sodir/``, see its README manifest) — no live network. They
import ``ncs.ingest`` / ``ncs.contracts``, which do not exist yet, so the module is **red at
collection time** until the developer builds the seam and link reconcile (001-T9/T10/T11). That is
the intended TDD starting state; the assertions are written to go green once the seam exists exactly
as the conftest constructs it and link reconcile is implemented as designed in plan.md §Link.

Boundary (task hard rule): this suite asserts that the unmatched records *survive* persistence (the
"kept" half of R8). The formal **R9** completeness invariant — persisted production count equals the
*source* row count — is **T6's**, and is not replicated here.
"""

from __future__ import annotations

import duckdb

# Frozen contract types (contracts.md). Importing at module scope makes the whole suite go red for
# the right reason — these resolve only once the developer adds the package modules.
from ncs import ingest
from ncs.contracts import IngestionReport

# --- Expected reconcile result, pinned to the canonical fixture set ------------------------------
# (fixtures/sodir/README.md "EARS edge cases" + the files themselves; confirmed against
# production_primary.csv and field_primary.json / field_fallback.csv.)
#
#   Distinct production NPDIDs : {1001, 1002, 1003, 1009}   (1009 = ORPHANPROD)
#   Field NPDIDs               : {1001, 1002, 1003, 1004}   (1004 = DELTA)
#   Matched (resolve both ways): {1001, 1002, 1003}
#   unmatched_production_npdids: [1009]   ORPHANPROD — in production, no field
#   unmatched_field_npdids     : [1004]   DELTA      — a field, no production
#   Many-to-one production-row counts per matched field: 1001→4, 1002→3, 1003→2

EXPECTED_PRODUCTION_NPDIDS = {1001, 1002, 1003, 1009}
EXPECTED_FIELD_NPDIDS = {1001, 1002, 1003, 1004}
MATCHED_NPDIDS = {1001, 1002, 1003}

NPDID_ORPHANPROD = 1009  # production-only → expected in unmatched_production_npdids
NPDID_DELTA = 1004  # field-only        → expected in unmatched_field_npdids

EXPECTED_UNMATCHED_PRODUCTION = {NPDID_ORPHANPROD}
EXPECTED_UNMATCHED_FIELD = {NPDID_DELTA}

# Supporting totals (full row counts the unmatched records must NOT reduce). The authoritative
# source-vs-persisted completeness invariant is T6's; here these only show nothing was dropped.
EXPECTED_PRODUCTION_ROWS = 10
EXPECTED_FIELD_ROWS = 4

# Many-to-one fidelity: a matched field carrying several production months (1001 → 4 rows).
NPDID_MANY_TO_ONE = 1001
EXPECTED_MANY_TO_ONE_ROWS = 4


# --- Helpers: read the reconcile inputs back out of the persisted DuckDB tables ------------------


def _distinct_production_npdids(con: duckdb.DuckDBPyConnection) -> set[int]:
    """Distinct ``field_npdid`` actually persisted in ``monthly_production`` (a reconcile input)."""
    return {
        row[0]
        for row in con.execute(
            "SELECT DISTINCT field_npdid FROM monthly_production"
        ).fetchall()
    }


def _field_npdids(con: duckdb.DuckDBPyConnection) -> set[int]:
    """All ``field_npdid`` actually persisted in ``field`` (the other reconcile input)."""
    return {row[0] for row in con.execute("SELECT field_npdid FROM field").fetchall()}


def _count_production_rows_for(con: duckdb.DuckDBPyConnection, field_npdid: int) -> int:
    """How many ``monthly_production`` rows carry this ``field_npdid`` (many-to-one fan-out)."""
    (count,) = con.execute(
        "SELECT count(*) FROM monthly_production WHERE field_npdid = ?", [field_npdid]
    ).fetchone()
    return count


def _field_rows_for(con: duckdb.DuckDBPyConnection, field_npdid: int) -> int:
    """How many ``field`` rows exist for this NPDID (the "one" side of the link; expected 0 or 1)."""
    (count,) = con.execute(
        "SELECT count(*) FROM field WHERE field_npdid = ?", [field_npdid]
    ).fetchone()
    return count


# ============================================================ R8 — reported (report-output) ======
# These assert the two unmatched lists the run returns are exactly right, order-independently, and
# clean (no duplicates), and that matched NPDIDs are flagged in neither list.


def test_r8_unmatched_lists_are_exactly_the_either_direction_mismatches(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R8: the report's two unmatched lists are exactly the either-direction mismatch sets.

    ORPHANPROD/1009 is in production but is no field → ``unmatched_production_npdids``; DELTA/1004 is
    a field with no production → ``unmatched_field_npdids``. Compared as **sets** because the
    contract types both ``list[int]`` and promises no ordering.
    """
    report = ingest(con, good_settings)

    assert isinstance(report, IngestionReport)
    assert set(report.unmatched_production_npdids) == EXPECTED_UNMATCHED_PRODUCTION
    assert set(report.unmatched_field_npdids) == EXPECTED_UNMATCHED_FIELD


def test_r8_unmatched_lists_have_no_duplicates(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R8: each unmatched list reports every mismatched NPDID once (no duplicate entries).

    Many-to-one means a production NPDID can appear on many rows; the reconcile must report a
    mismatched NPDID a single time, so each list's length equals its distinct-element count.
    """
    report = ingest(con, good_settings)

    prod_unmatched = report.unmatched_production_npdids
    field_unmatched = report.unmatched_field_npdids

    assert len(prod_unmatched) == len(set(prod_unmatched)), (
        f"unmatched_production_npdids has duplicates: {prod_unmatched!r}"
    )
    assert len(field_unmatched) == len(set(field_unmatched)), (
        f"unmatched_field_npdids has duplicates: {field_unmatched!r}"
    )


def test_r8_matched_npdids_appear_in_neither_unmatched_list(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R8: a matched NPDID (resolves both ways) is flagged unmatched in neither direction.

    1001/1002/1003 each have both a ``Field`` row and production rows, so they must be absent from
    both ``unmatched_*`` lists — a matched record must never be reported as unmatched.
    """
    report = ingest(con, good_settings)

    prod_unmatched = set(report.unmatched_production_npdids)
    field_unmatched = set(report.unmatched_field_npdids)

    for npdid in MATCHED_NPDIDS:
        assert npdid not in prod_unmatched, (
            f"matched NPDID {npdid} wrongly flagged in unmatched_production_npdids"
        )
        assert npdid not in field_unmatched, (
            f"matched NPDID {npdid} wrongly flagged in unmatched_field_npdids"
        )


# ===================================================== R8 — set algebra over persisted data =======
# Prove the reconcile logic is correct against the data actually in DuckDB, not just the hardcoded
# answer above — so the test still holds if the fixtures evolve.


def test_r8_unmatched_lists_equal_set_difference_of_persisted_npdids(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R8: the unmatched lists equal the set differences of the persisted reconcile inputs.

    Derive the distinct production NPDIDs and the field NPDIDs from DuckDB and assert
    ``unmatched_production_npdids == prod - field`` and ``unmatched_field_npdids == field - prod``.
    This pins the set algebra of the reconcile (plan.md §Link), independent of the literal answer.
    """
    report = ingest(con, good_settings)

    prod_npdids = _distinct_production_npdids(con)
    field_npdids = _field_npdids(con)

    # Guard: the fixtures are what we think (so a fixture drift surfaces here, not as a silent pass).
    assert prod_npdids == EXPECTED_PRODUCTION_NPDIDS
    assert field_npdids == EXPECTED_FIELD_NPDIDS

    assert set(report.unmatched_production_npdids) == prod_npdids - field_npdids
    assert set(report.unmatched_field_npdids) == field_npdids - prod_npdids


def test_r8_every_production_npdid_resolves_xor_is_reported_unmatched(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R8 (acceptance invariant): for each distinct production ``field_npdid``, **exactly one**
    of {resolves to a ``field`` row, is in ``unmatched_production_npdids``} holds — never both,
    never neither.

    This is the literal R8 acceptance criterion ("either resolves to a ``Field`` or appears in the
    report") expressed as an exclusive-or over every distinct production NPDID.
    """
    report = ingest(con, good_settings)

    unmatched_production = set(report.unmatched_production_npdids)

    for npdid in _distinct_production_npdids(con):
        resolves = _field_rows_for(con, npdid) == 1
        reported = npdid in unmatched_production
        assert resolves != reported, (
            f"production field_npdid {npdid}: resolves-to-Field={resolves}, "
            f"reported-unmatched={reported} — R8 requires exactly one to be true"
        )


# ============================================================ R8 — kept (nothing is dropped) ======
# The "kept" half of R8 (plan.md §Link: "Nothing is dropped — unmatched records are still persisted
# and counted, the mismatch is reported"). The unmatched records must SURVIVE in DuckDB. (The formal
# source-row-count completeness invariant is T6's; here we only show the unmatched rows persisted.)


def test_r8_unmatched_production_record_is_kept_not_dropped(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R8 (kept): the orphan production NPDID 1009 keeps its production row(s) in DuckDB.

    Being reported as ``unmatched_production`` must not delete it — ORPHANPROD/1009 still has its
    ``monthly_production`` row(s) after the run, even though no ``field`` row resolves it.
    """
    report = ingest(con, good_settings)

    # It is reported as unmatched ...
    assert NPDID_ORPHANPROD in set(report.unmatched_production_npdids)
    # ... and it has no field (that is *why* it is unmatched) ...
    assert _field_rows_for(con, NPDID_ORPHANPROD) == 0
    # ... yet its production rows were KEPT, not dropped.
    assert _count_production_rows_for(con, NPDID_ORPHANPROD) >= 1, (
        "unmatched production NPDID 1009 must keep its monthly_production row(s) (R8: never dropped)"
    )


def test_r8_unmatched_field_record_is_kept_not_dropped(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R8 (kept): the production-less field DELTA/1004 keeps its row in the ``field`` table.

    Being reported as ``unmatched_field`` must not delete it — DELTA/1004 still has its ``field``
    row after the run, even though no production references it.
    """
    report = ingest(con, good_settings)

    # It is reported as unmatched ...
    assert NPDID_DELTA in set(report.unmatched_field_npdids)
    # ... and no production references it ...
    assert NPDID_DELTA not in _distinct_production_npdids(con)
    # ... yet its field row was KEPT, not dropped.
    assert _field_rows_for(con, NPDID_DELTA) == 1, (
        "unmatched field NPDID 1004 must keep its field row (R8: never dropped)"
    )


def test_r8_unmatched_records_do_not_shrink_the_totals(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R8 (kept, supporting): reporting mismatches leaves the full row totals intact.

    Supporting evidence that the unmatched records survived: all 10 production rows and all 4 field
    rows are still present (the orphan/production-less rows were not pruned). The authoritative
    source-vs-persisted completeness invariant (R9) is **T6's** — this only shows nothing shrank.
    """
    ingest(con, good_settings)

    (production_rows,) = con.execute("SELECT count(*) FROM monthly_production").fetchone()
    (field_rows,) = con.execute("SELECT count(*) FROM field").fetchone()

    assert production_rows == EXPECTED_PRODUCTION_ROWS
    assert field_rows == EXPECTED_FIELD_ROWS


# ============================================================ R8 — many-to-one link fidelity ======


def test_r8_link_is_many_production_to_one_field(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R8: the link is many production rows → one ``Field`` (matched field 1001 fans in 4 rows).

    Field 1001 carries 4 production months, all stamped with the same ``field_npdid``, and that
    NPDID resolves to **exactly one** ``field`` row — demonstrating the many-to-one direction of the
    link rather than a 1:1 or duplicated-field mapping.
    """
    ingest(con, good_settings)

    # Many production rows for this NPDID ...
    assert _count_production_rows_for(con, NPDID_MANY_TO_ONE) == EXPECTED_MANY_TO_ONE_ROWS

    # ... every one of which carries that single field_npdid (no stray/transposed key) ...
    (distinct_keys_on_those_rows,) = con.execute(
        "SELECT count(DISTINCT field_npdid) FROM monthly_production WHERE field_npdid = ?",
        [NPDID_MANY_TO_ONE],
    ).fetchone()
    assert distinct_keys_on_those_rows == 1

    # ... and they resolve to exactly ONE field row (the "one" side of many-to-one).
    assert _field_rows_for(con, NPDID_MANY_TO_ONE) == 1
