"""Acceptance suite: ingestion report & completeness — EARS 001-R9 (task 001-T6).

R9: "WHEN an ingestion run completes, the system SHALL emit a typed ingestion report recording
the source(s) used, the retrieval timestamp, and per-dataset record counts, and listing every
NPDID present in one dataset but unmatched in the other; the persisted production-record count
SHALL equal the source record count (no record is silently dropped)."

This suite treats the report as an **artifact**: that it is a typed ``IngestionReport`` carrying
every required part, a timezone-aware UTC ``retrieved_at`` stamped at run time, correct per-dataset
counts, the **completeness invariant** (persisted production count == *source* row count — the crux
of R9), both unmatched lists present, and — the half T4 deferred here — that the report is also
**persisted** to the DuckDB ``ingestion_report`` table (plan.md §"Ingestion report").

Boundary (split with T4 / ``test_link.py``): T4 owns the R8 reconcile *set-algebra* and already
checks the *returned* report's ``unmatched_*`` lists against the persisted data. This suite does
**not** re-prove that algebra; it asserts the unmatched lists are *present and listed* in the report
(R9 requires it) and adds the report-as-artifact guarantees (timestamp, counts, completeness,
persisted table) that T4 left to T6.

All tests are black-box through the public seam ``ingest(con, settings)`` against the shared
canonical SODIR fixtures (``fixtures/sodir/``, see its README manifest) — no live network. They
import ``ncs.ingest`` / ``ncs.contracts``, which do not exist yet, so the module is **red at
collection time** until the developer builds the seam and the report + completeness check
(001-T12) over persisted data. That is the intended TDD starting state; the assertions are written
to go green once the seam exists exactly as the conftest constructs it and the report is built and
persisted as designed in plan.md.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

# Frozen contract types (contracts.md). Importing at module scope makes the whole suite go red for
# the right reason — these resolve only once the developer adds the package modules.
from ncs import ingest
from ncs.contracts import (
    Dataset,
    IngestionReport,
    RecordCounts,
    SourceRef,
    Transport,
)

# Path to the production primary CSV — re-derived locally (mirroring conftest's own
# ``SODIR_FIXTURES`` definition) so the completeness invariant counts the *same* source file the
# happy-path ``good_settings`` points ``ingest`` at. Re-derived rather than imported from conftest
# to match the siblings' pattern (none import conftest as a module).
PRODUCTION_PRIMARY: Path = (
    Path(__file__).parent / "fixtures" / "sodir" / "production_primary.csv"
)

# --- Expected derived values, pinned to the canonical fixture set --------------------------------
# (fixtures/sodir/README.md "Expected derived values" + the files themselves.) The completeness
# invariant below derives the production count straight from production_primary.csv rather than
# trusting this constant — these are the cross-check / guard values.

EXPECTED_PRODUCTION_RECORDS = 10
EXPECTED_DISTINCT_PRODUCTION_FIELDS = 4  # NPDIDs 1001, 1002, 1003, 1009
EXPECTED_FIELDS = 4  # NPDIDs 1001, 1002, 1003, 1004

EXPECTED_UNMATCHED_PRODUCTION = {1009}  # ORPHANPROD — in production, no field
EXPECTED_UNMATCHED_FIELD = {1004}  # DELTA — a field, no production

# Happy-path winning transports per dataset (good_settings: both primaries valid).
EXPECTED_PRODUCTION_TRANSPORT = Transport.csv  # production primary is CSV
EXPECTED_FIELD_TRANSPORT = Transport.rest  # field primary is REST (layer 7100)

# The persisted-report table the run must also write (plan.md §"Ingestion report").
INGESTION_REPORT_TABLE = "ingestion_report"


# --- Helpers -------------------------------------------------------------------------------------


def _source_for(report: IngestionReport, dataset: Dataset) -> SourceRef:
    """Return the single ``SourceRef`` the run recorded for ``dataset`` (one per dataset, R9)."""
    matches = [s for s in report.sources if s.dataset == dataset]
    assert matches, f"report.sources has no entry for dataset {dataset!r}: {report.sources!r}"
    assert len(matches) == 1, f"expected exactly one source for {dataset!r}, got {matches!r}"
    return matches[0]


def _source_production_row_count() -> int:
    """Count the **source** production data rows straight from ``production_primary.csv``.

    The completeness invariant (R9) is "persisted production count == source row count". To prove
    it honestly the source count must come from the file, not a hardcoded literal: read the CSV the
    happy-path ``good_settings`` points at, count non-empty lines, and subtract the single header
    row. (Whitespace-only lines / a trailing newline do not count as data rows.)
    """
    text = PRODUCTION_PRIMARY.read_text(encoding="utf-8")
    nonblank_lines = [line for line in text.splitlines() if line.strip()]
    assert nonblank_lines, f"{PRODUCTION_PRIMARY} appears empty"
    return len(nonblank_lines) - 1  # minus the header row


def _report_table_columns(con: duckdb.DuckDBPyConnection) -> set[str]:
    """Column names present on the persisted ``ingestion_report`` table."""
    rows = con.execute(f"PRAGMA table_info('{INGESTION_REPORT_TABLE}')").fetchall()
    # PRAGMA table_info → (cid, name, type, notnull, dflt_value, pk); name is index 1.
    return {row[1] for row in rows}


# ============================================================ R9 — structure (required parts) =====
# The report is a typed IngestionReport carrying every part R9 enumerates.


def test_r9_report_is_typed_with_every_required_part(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R9: the run returns a typed ``IngestionReport`` carrying all required parts.

    R9 enumerates: the source(s) used, the retrieval timestamp, per-dataset counts, and both
    unmatched-NPDID lists. Assert each is present and correctly typed — ``sources`` a non-empty
    ``list[SourceRef]``, ``retrieved_at`` a ``datetime``, ``counts`` a ``RecordCounts``, and both
    ``unmatched_*`` attributes present as lists.
    """
    report = ingest(con, good_settings)

    assert isinstance(report, IngestionReport)

    # sources — a non-empty list, every element a SourceRef.
    assert isinstance(report.sources, list)
    assert report.sources, "report.sources must list the dataset(s) retrieved (R9)"
    assert all(isinstance(s, SourceRef) for s in report.sources)

    # retrieved_at — a datetime (timezone discipline asserted in the timestamp section).
    assert isinstance(report.retrieved_at, datetime)

    # counts — the typed RecordCounts (values asserted in the counts section).
    assert isinstance(report.counts, RecordCounts)

    # both unmatched lists present (contents asserted in the unmatched section).
    assert isinstance(report.unmatched_production_npdids, list)
    assert isinstance(report.unmatched_field_npdids, list)


def test_r9_sources_one_sourceref_per_dataset_retrieved(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R9: ``sources`` carries exactly one ``SourceRef`` per dataset retrieved (2 total).

    Both datasets are retrieved, so the report records exactly one source for ``Dataset.production``
    and one for ``Dataset.field`` (no more, no fewer); each carries a ``url`` and a ``transport``.
    On the happy path the production primary (CSV) and field primary (REST) win, so the recorded
    transports are ``csv`` and ``rest`` respectively — making a fallback (R3), had one occurred,
    visible here.
    """
    report = ingest(con, good_settings)

    # Exactly the two datasets, one source each.
    datasets = [s.dataset for s in report.sources]
    assert set(datasets) == {Dataset.production, Dataset.field}
    assert len(report.sources) == 2, f"expected one source per dataset, got {report.sources!r}"

    production_source = _source_for(report, Dataset.production)
    field_source = _source_for(report, Dataset.field)

    # Each source records where (url) and over which transport.
    for source in (production_source, field_source):
        assert source.url is not None, f"SourceRef.url missing: {source!r}"
        assert isinstance(source.transport, Transport)

    # Happy-path winning transports (primary served for each dataset).
    assert production_source.transport == EXPECTED_PRODUCTION_TRANSPORT
    assert field_source.transport == EXPECTED_FIELD_TRANSPORT


# ============================================================ R9 — timestamp ======================
# retrieved_at is a timezone-aware UTC datetime, stamped at run time (not a constant).


def test_r9_retrieved_at_is_timezone_aware_utc_at_run_time(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R9: ``retrieved_at`` is a timezone-aware UTC timestamp captured at run time.

    Two things proven: (1) it is timezone-aware UTC — ``tzinfo is not None`` and the UTC offset is
    zero; (2) it is stamped *now*, not a hardcoded constant — it falls within ``[before, after]``,
    the wall-clock window bracketing the ``ingest`` call. The bounds are themselves timezone-aware
    UTC so the comparison is unambiguous.
    """
    before = datetime.now(timezone.utc)
    report = ingest(con, good_settings)
    after = datetime.now(timezone.utc)

    retrieved_at = report.retrieved_at

    # (1) Timezone-aware, and the offset is UTC (zero).
    assert retrieved_at.tzinfo is not None, "retrieved_at must be timezone-aware (R9: UTC)"
    offset = retrieved_at.utcoffset()
    assert offset is not None and offset.total_seconds() == 0, (
        f"retrieved_at must be UTC (zero offset), got offset {offset!r}"
    )

    # (2) Stamped at run time — within the window bracketing the call (not a constant).
    assert before <= retrieved_at <= after, (
        f"retrieved_at {retrieved_at!r} not within run window [{before!r}, {after!r}] "
        "— it must be stamped at run time, not a fixed value"
    )


# ============================================================ R9 — counts =========================
# The three per-dataset counts are correct, each cross-checked against the persisted DuckDB tables.


def test_r9_counts_are_correct_and_match_persisted_tables(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R9: ``counts`` reports production records, distinct production fields, and fields right.

    Assert the three counts equal the canonical expected values (10 / 4 / 4) **and** cross-check
    each against DuckDB so the report mirrors what actually landed: ``count(*)`` and
    ``count(DISTINCT field_npdid)`` on ``monthly_production`` and ``count(*)`` on ``field``.
    """
    report = ingest(con, good_settings)
    counts = report.counts

    # Expected canonical values.
    assert counts.production_records == EXPECTED_PRODUCTION_RECORDS
    assert counts.distinct_production_fields == EXPECTED_DISTINCT_PRODUCTION_FIELDS
    assert counts.fields == EXPECTED_FIELDS

    # Cross-check each against the persisted tables (the report must reflect reality, not a guess).
    (persisted_production,) = con.execute(
        "SELECT count(*) FROM monthly_production"
    ).fetchone()
    (persisted_distinct,) = con.execute(
        "SELECT count(DISTINCT field_npdid) FROM monthly_production"
    ).fetchone()
    (persisted_fields,) = con.execute("SELECT count(*) FROM field").fetchone()

    assert counts.production_records == persisted_production
    assert counts.distinct_production_fields == persisted_distinct
    assert counts.fields == persisted_fields


# ============================================================ R9 — completeness invariant =========
# The crux of R9: persisted production count == SOURCE production row count (no record dropped).


def test_r9_completeness_invariant_persisted_equals_source_row_count(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R9 (the crux): the persisted production count equals the **source** row count.

    R9's "no record is silently dropped" guarantee. Three quantities must agree:

    * the **source** count — derived by reading ``production_primary.csv`` and counting its data
      rows (non-blank lines minus the header), *not* a hardcoded 10 (deriving it from the file is
      the whole point of the invariant);
    * ``report.counts.production_records`` — what the report claims landed;
    * the **persisted** ``count(*)`` on ``monthly_production`` — what actually landed.

    All three equal (10 for the canonical sample). If the report claimed fewer than the source had,
    a record was silently dropped — which R9 forbids — and this assertion fails.
    """
    source_rows = _source_production_row_count()

    report = ingest(con, good_settings)
    (persisted_rows,) = con.execute("SELECT count(*) FROM monthly_production").fetchone()

    # Guard: the derived source count is the canonical 10 (a fixture drift surfaces here loudly).
    assert source_rows == EXPECTED_PRODUCTION_RECORDS, (
        f"derived source row count {source_rows} != expected {EXPECTED_PRODUCTION_RECORDS} "
        f"— recount production_primary.csv / re-sync the manifest"
    )

    # The literal R9 invariant: report count == source count == persisted count, all equal.
    assert report.counts.production_records == source_rows == persisted_rows, (
        f"completeness invariant violated: report={report.counts.production_records}, "
        f"source={source_rows}, persisted={persisted_rows} — a record was silently dropped (R9)"
    )


# ============================================================ R9 — unmatched lists listed =========
# R9 requires the report list every NPDID present in one dataset but unmatched in the other.
# (The reconcile set-algebra that *produces* these lists is T4's; here we only assert they are
# present and listed correctly in the report artifact.)


def test_r9_both_unmatched_lists_are_listed_in_the_report(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R9: the report lists both unmatched-NPDID lists (every one-sided NPDID present).

    R9 "listing every NPDID present in one dataset but unmatched in the other": ORPHANPROD/1009 is
    in production with no field, DELTA/1004 is a field with no production. Set-compared because the
    contract types both as ``list[int]`` and promises no ordering. This asserts the lists are
    *present and correct in the artifact*; T4 owns proving the reconcile algebra that derives them.
    """
    report = ingest(con, good_settings)

    assert set(report.unmatched_production_npdids) == EXPECTED_UNMATCHED_PRODUCTION
    assert set(report.unmatched_field_npdids) == EXPECTED_UNMATCHED_FIELD


# ============================================================ R9 — persisted to DuckDB table ======
# The half T4 deferred: the report is also written to the ``ingestion_report`` DuckDB table
# (plan.md §"Ingestion report"), so a run leaves an auditable provenance/completeness row.


def test_r9_report_is_persisted_as_single_row_with_correct_counts(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R9: the run writes exactly one ``ingestion_report`` row carrying the counts.

    plan.md §"Ingestion report" persists the report to a DuckDB ``ingestion_report`` table (one row
    per run). After a single run, that table holds exactly one row, and its
    ``production_records`` / ``distinct_production_fields`` / ``fields`` columns equal 10 / 4 / 4 —
    the same counts the returned report carries.
    """
    ingest(con, good_settings)

    (row_count,) = con.execute(
        f"SELECT count(*) FROM {INGESTION_REPORT_TABLE}"
    ).fetchone()
    assert row_count == 1, f"expected exactly one persisted ingestion_report row, got {row_count}"

    production_records, distinct_production_fields, fields = con.execute(
        f"SELECT production_records, distinct_production_fields, fields "
        f"FROM {INGESTION_REPORT_TABLE}"
    ).fetchone()

    assert production_records == EXPECTED_PRODUCTION_RECORDS
    assert distinct_production_fields == EXPECTED_DISTINCT_PRODUCTION_FIELDS
    assert fields == EXPECTED_FIELDS


def test_r9_persisted_report_unmatched_array_columns(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R9: the persisted row's unmatched ``BIGINT[]`` columns equal ``[1009]`` / ``[1004]``.

    The two unmatched lists are stored as DuckDB native array columns
    (``unmatched_production_npdids`` / ``unmatched_field_npdids``, ``BIGINT[]`` per plan.md). DuckDB
    returns an array column to Python as a ``list``; set-compare to stay order-independent (the
    contract promises no ordering on these lists).
    """
    ingest(con, good_settings)

    unmatched_production, unmatched_field = con.execute(
        f"SELECT unmatched_production_npdids, unmatched_field_npdids "
        f"FROM {INGESTION_REPORT_TABLE}"
    ).fetchone()

    # DuckDB BIGINT[] → Python list; guard the type then set-compare the contents.
    assert isinstance(unmatched_production, list), (
        f"unmatched_production_npdids should read back as a list, got {type(unmatched_production)}"
    )
    assert isinstance(unmatched_field, list), (
        f"unmatched_field_npdids should read back as a list, got {type(unmatched_field)}"
    )
    assert set(unmatched_production) == EXPECTED_UNMATCHED_PRODUCTION
    assert set(unmatched_field) == EXPECTED_UNMATCHED_FIELD


def test_r9_persisted_report_has_sources_and_timestamp(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R9: the persisted row carries the run's sources and a timezone-aware UTC timestamp.

    The other two required parts survive persistence: ``retrieved_at`` (a timezone-aware UTC
    ``TIMESTAMPTZ`` per plan.md) is non-null and UTC, and ``sources`` is present/non-null. ``sources``
    is stored as JSON, so this only parses it and checks it lists the two datasets retrieved — kept
    deliberately loose so it does not over-couple to the exact JSON serialization the developer picks
    (the typed ``SourceRef`` shape is asserted on the *returned* report above).
    """
    ingest(con, good_settings)

    retrieved_at, sources_raw = con.execute(
        f"SELECT retrieved_at, sources FROM {INGESTION_REPORT_TABLE}"
    ).fetchone()

    # Timestamp persisted, timezone-aware, UTC (DuckDB TIMESTAMPTZ → aware datetime).
    assert isinstance(retrieved_at, datetime)
    assert retrieved_at.tzinfo is not None, "persisted retrieved_at must be timezone-aware (UTC)"
    offset = retrieved_at.utcoffset()
    assert offset is not None and offset.total_seconds() == 0, (
        f"persisted retrieved_at must be UTC (zero offset), got offset {offset!r}"
    )

    # sources persisted and non-null; parse the JSON loosely (one entry per dataset retrieved).
    assert sources_raw is not None, "persisted ingestion_report.sources must be non-null (R9)"
    sources = sources_raw if isinstance(sources_raw, list) else json.loads(sources_raw)
    assert isinstance(sources, list)
    assert len(sources) == 2, (
        f"persisted sources should list both datasets retrieved (2 entries), got {sources!r}"
    )


def test_r9_persisted_report_table_has_all_required_columns(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R9: the ``ingestion_report`` table exposes every column the report artifact requires.

    A structural guard on the persisted artifact (plan.md §"Ingestion report" schema): after a run
    the table carries ``retrieved_at``, ``sources``, the three count columns, and the two unmatched
    array columns — so every part of the report is actually durable, not just the ones spot-checked
    above.
    """
    ingest(con, good_settings)

    columns = _report_table_columns(con)
    required = {
        "retrieved_at",
        "sources",
        "production_records",
        "distinct_production_fields",
        "fields",
        "unmatched_production_npdids",
        "unmatched_field_npdids",
    }
    missing = required - columns
    assert not missing, f"ingestion_report is missing required column(s): {sorted(missing)}"
