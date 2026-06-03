"""Acceptance suite: sourcing & fallback — EARS 001-R1, 001-R2, 001-R3 (task 001-T2).

Black-box tests driven entirely through the public seam ``ingest(con, settings)`` against the
shared local SODIR fixtures (``fixtures/sodir/``, see its README manifest). No live network.

* **001-R1** — a run retrieves the full monthly production history (non-empty, spanning many
  distinct years); the report's production count equals the source row count.
* **001-R2** — the same run retrieves field-outline geometry (non-empty field set; WKT present).
* **001-R3** — with a dataset's **primary** source forced to fail, the run still loads that
  dataset from the documented fallback before reporting failure.

These import ``ncs.ingest`` / ``ncs.config`` / ``ncs.contracts``, which do not exist yet, so the
suite is **red at collection time** until the developer builds the seam (001-T7/T8). That is the
intended TDD starting state — the assertions below are written to go green once the seam exists
exactly as the conftest constructs it.
"""

from __future__ import annotations

import duckdb
from shapely import wkt as shapely_wkt
from shapely.geometry.base import BaseGeometry

# Frozen contract types (contracts.md). Importing at module scope makes the whole suite go
# red for the right reason — these resolve only once the developer adds the package modules.
from ncs import ingest
from ncs.contracts import (
    Dataset,
    IngestionReport,
    Transport,
)

# Expected derived values for the canonical fixture set (fixtures/sodir/README.md).
EXPECTED_PRODUCTION_ROWS = 10
EXPECTED_FIELD_ROWS = 4
EXPECTED_DISTINCT_PRODUCTION_FIELDS = 4
FALLBACK_PRODUCTION_FILENAME = "production_fallback.csv"


def _source_for(report: IngestionReport, dataset: Dataset):
    """Return the single ``SourceRef`` the run recorded for ``dataset`` (one per dataset)."""
    matches = [s for s in report.sources if s.dataset == dataset]
    assert matches, f"report.sources has no entry for dataset {dataset!r}: {report.sources!r}"
    assert len(matches) == 1, f"expected exactly one source for {dataset!r}, got {matches!r}"
    return matches[0]


# --------------------------------------------------------------------------------------- R1


def test_r1_retrieves_full_monthly_production_history(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R1: a run retrieves a non-empty monthly-production set spanning many years."""
    report = ingest(con, good_settings)

    assert isinstance(report, IngestionReport)

    # Non-empty production set, and no record silently dropped: the report's production count
    # equals the source row count (the canonical sample has 10 data rows).
    assert report.counts.production_records == EXPECTED_PRODUCTION_ROWS

    # The production landed in DuckDB and is queryable (R1 retrieval is observable downstream).
    (persisted_rows,) = con.execute("SELECT count(*) FROM monthly_production").fetchone()
    assert persisted_rows == EXPECTED_PRODUCTION_ROWS

    # "Full available history ... spanning many years": the sample carries 2021, 2022, 2023.
    distinct_years = {
        row[0]
        for row in con.execute("SELECT DISTINCT year FROM monthly_production").fetchall()
    }
    assert len(distinct_years) >= 2, f"expected production across many years, got {distinct_years}"
    assert distinct_years == {2021, 2022, 2023}


def test_r1_production_count_matches_source_row_count(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R1: the reported production count is exactly the source row count (nothing dropped)."""
    report = ingest(con, good_settings)

    assert report.counts.production_records == EXPECTED_PRODUCTION_ROWS
    assert report.counts.distinct_production_fields == EXPECTED_DISTINCT_PRODUCTION_FIELDS


# --------------------------------------------------------------------------------------- R2


def test_r2_retrieves_field_outline_geometry(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R2: the same run retrieves a non-empty field set carrying outline geometry."""
    report = ingest(con, good_settings)

    assert report.counts.fields == EXPECTED_FIELD_ROWS

    (persisted_fields,) = con.execute("SELECT count(*) FROM field").fetchone()
    assert persisted_fields == EXPECTED_FIELD_ROWS

    # Geometry came through: at least one field carries a non-null WKT outline, and every
    # non-null outline is a shapely-parseable polygon/multipolygon (full R7 sweep is T3's job;
    # here we only confirm geometry was actually retrieved, not dropped).
    wkts = [
        row[0]
        for row in con.execute(
            "SELECT geometry_wkt FROM field WHERE geometry_wkt IS NOT NULL"
        ).fetchall()
    ]
    assert wkts, "expected at least one field to carry outline geometry (R2)"
    for w in wkts:
        geom: BaseGeometry = shapely_wkt.loads(w)
        assert geom.geom_type in {"Polygon", "MultiPolygon"}


def test_r2_field_source_recorded(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R2: the run records where the field dataset came from (a SourceRef for it)."""
    report = ingest(con, good_settings)

    field_source = _source_for(report, Dataset.field)
    # Happy path: the REST primary served, so the recorded transport is REST.
    assert field_source.transport == Transport.rest


# --------------------------------------------------------------------------------------- R3


def test_r3_geometry_falls_back_to_csv_when_rest_primary_fails(
    con: duckdb.DuckDBPyConnection, settings_factory: object
) -> None:
    """001-R3: field REST primary unavailable -> run still loads geometry from the CSV fallback.

    Cleanest, transport-visible proof: the field primary (REST) is pointed at a missing path,
    so the documented CSV ``fldArea`` fallback must win. Because the fallback flips the
    transport ``rest -> csv``, success is observable directly on ``SourceRef.transport``.
    """
    settings = settings_factory(break_field_primary=True)

    report = ingest(con, settings)  # must NOT raise — fallback is tried before failure

    # Fields still loaded (same 4 fields, since the fallback CSV mirrors the REST primary).
    assert report.counts.fields == EXPECTED_FIELD_ROWS
    (persisted_fields,) = con.execute("SELECT count(*) FROM field").fetchone()
    assert persisted_fields == EXPECTED_FIELD_ROWS

    # The fallback won: the recorded field transport is CSV (the rest -> csv flip).
    field_source = _source_for(report, Dataset.field)
    assert field_source.transport == Transport.csv


def test_r3_production_falls_back_to_alternate_source_when_primary_fails(
    con: duckdb.DuckDBPyConnection, settings_factory: object
) -> None:
    """001-R3: production primary unavailable -> run still loads from the alternate source.

    The ``Transport`` enum is frozen to ``{rest, csv}`` and the production fallback is the same
    report re-served in another machine format (kept CSV-class), so the transport stays ``csv``
    both ways. The fallback is therefore proven via the **winning source location** pointing at
    the fallback file, not via a transport flip.
    """
    settings = settings_factory(break_production_primary=True)

    report = ingest(con, settings)  # must NOT raise — fallback is tried before failure

    # Production still loaded in full (the fallback holds the same rows as the primary).
    assert report.counts.production_records == EXPECTED_PRODUCTION_ROWS
    (persisted_rows,) = con.execute("SELECT count(*) FROM monthly_production").fetchone()
    assert persisted_rows == EXPECTED_PRODUCTION_ROWS

    # The fallback won: the recorded production source points at the *fallback* file.
    prod_source = _source_for(report, Dataset.production)
    assert prod_source.transport == Transport.csv  # unchanged; ordering is what we prove
    assert FALLBACK_PRODUCTION_FILENAME in str(prod_source.url), (
        "expected the recorded production source URL to be the fallback file "
        f"({FALLBACK_PRODUCTION_FILENAME}), got {prod_source.url!r}"
    )


def test_r3_both_datasets_succeed_when_each_primary_fails(
    con: duckdb.DuckDBPyConnection, settings_factory: object
) -> None:
    """001-R3: both primaries failing simultaneously still yields a complete run via fallbacks."""
    settings = settings_factory(break_production_primary=True, break_field_primary=True)

    report = ingest(con, settings)

    # Both datasets recovered from their fallbacks — full counts, no failure reported.
    assert report.counts.production_records == EXPECTED_PRODUCTION_ROWS
    assert report.counts.fields == EXPECTED_FIELD_ROWS

    # Field fell back to CSV; production source is the fallback file.
    assert _source_for(report, Dataset.field).transport == Transport.csv
    assert FALLBACK_PRODUCTION_FILENAME in str(_source_for(report, Dataset.production).url)
