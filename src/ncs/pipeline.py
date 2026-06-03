"""End-to-end ingestion run — assemble fetch → normalize → link → persist → report (T12).

``ingest(con, settings)`` is the public seam. It wires the stages, builds the typed
``IngestionReport`` from what actually landed, enforces the R9 **completeness invariant**, persists
the report, and returns it (plan.md §Ingestion report). It is the integration point for R1–R11.

Ordering and the invariant (the load-bearing details):
- ``retrieved_at`` is stamped at run **start**, timezone-aware UTC, at full microsecond resolution —
  ``test_persistence`` calls ``ingest`` 2–3× over one store and each appends an ``ingestion_report``
  row keyed by ``retrieved_at``; a coarse/second-truncated stamp would collide on that PK.
- The **source** production row count is captured at fetch, before normalization, so a drop anywhere
  downstream is caught. After persist, ``counts.production_records`` is read back from DuckDB and the
  invariant ``persisted == source`` is asserted — a mismatch raises (a silent drop, R9-forbidden).
- The report is built **after** persist (so counts reflect reality), then itself persisted, then
  returned.
"""

from __future__ import annotations

from datetime import datetime, timezone

import duckdb

from ncs.config import Settings
from ncs.contracts import (
    Dataset,
    IngestionReport,
    RecordCounts,
    SourceRef,
)
from ncs.fetch import fetch_dataset
from ncs.link import reconcile_npdids
from ncs.normalize import normalize_fields, normalize_production
from ncs.persist import (
    configure_session,
    count_distinct_production_fields,
    count_field_rows,
    count_production_rows,
    create_schema,
    persist_data,
    persist_report,
)


class CompletenessError(Exception):
    """The persisted production count differs from the source row count — a silent drop (R9).

    R9 forbids losing a record between source and store. If, after persist, the persisted
    ``monthly_production`` count does not equal the production row count captured at fetch, the run
    fails loudly with this error rather than returning an under-counting report.
    """


def ingest(con: duckdb.DuckDBPyConnection, settings: Settings) -> IngestionReport:
    """Run one ingestion: fetch → normalize → link → persist → report (R1–R11).

    Returns the typed ``IngestionReport`` and, as a side effect, has written it (and the data) to
    DuckDB. Raises if every source for a dataset fails (R3) or if the completeness invariant is
    violated (R9).
    """
    retrieved_at = datetime.now(timezone.utc)  # run-start stamp; full microsecond resolution (PK)

    # Pin the session timezone to UTC: DuckDB renders TIMESTAMPTZ on read in the session tz, so this
    # makes retrieved_at round-trip from the store with a zero offset (R9: UTC). Explicit here, not a
    # hidden side effect of create_schema.
    configure_session(con)

    # --- Fetch (with fallback) — capture the source production row count before normalization. ---
    production_raw, production_source = fetch_dataset(
        Dataset.production, settings.production_sources
    )
    field_raw, field_source = fetch_dataset(Dataset.field, settings.field_sources)
    source_production_count = len(production_raw)

    # --- Normalize → typed models. ---
    production = normalize_production(production_raw)
    fields = normalize_fields(field_raw)

    # --- Link (NPDID reconcile; nothing dropped, mismatches reported). ---
    unmatched_production_npdids, unmatched_field_npdids = reconcile_npdids(production, fields)

    # --- Persist the data (idempotent upsert, one committed transaction). ---
    create_schema(con)
    persist_data(con, production, fields)

    # --- Build the report from what actually landed, then enforce the completeness invariant. ---
    # Assumes the whole monthly_production table == this run's source key set. True for 001 (single
    # full-history load; idempotent re-runs keep table == run), so count(*) can stand in for "this
    # run's persisted rows". A 002+ incremental/partial load would break this — compare the run's own
    # key set then, not the whole-table count(*).
    persisted_production = count_production_rows(con)
    if persisted_production != source_production_count:
        raise CompletenessError(
            "completeness invariant violated (R9): source production rows "
            f"{source_production_count} != persisted {persisted_production} "
            "— a record was silently dropped"
        )

    report = _build_report(
        con=con,
        production_source=production_source,
        field_source=field_source,
        retrieved_at=retrieved_at,
        unmatched_production_npdids=unmatched_production_npdids,
        unmatched_field_npdids=unmatched_field_npdids,
    )

    # --- Persist the report (append one run-history row) and return it. ---
    persist_report(con, report)
    return report


def _build_report(
    *,
    con: duckdb.DuckDBPyConnection,
    production_source: SourceRef,
    field_source: SourceRef,
    retrieved_at: datetime,
    unmatched_production_npdids: list[int],
    unmatched_field_npdids: list[int],
) -> IngestionReport:
    """Assemble the typed ``IngestionReport`` from the persisted counts and the run's metadata (R9).

    Counts are read back from DuckDB so the report mirrors what landed (not an in-memory guess); the
    two winning ``SourceRef``s record which transport served each dataset (so an R3 fallback shows).
    """
    counts = RecordCounts(
        production_records=count_production_rows(con),
        distinct_production_fields=count_distinct_production_fields(con),
        fields=count_field_rows(con),
    )
    return IngestionReport(
        sources=[production_source, field_source],
        retrieved_at=retrieved_at,
        counts=counts,
        unmatched_production_npdids=unmatched_production_npdids,
        unmatched_field_npdids=unmatched_field_npdids,
    )
