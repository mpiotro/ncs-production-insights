"""DuckDB persistence + idempotent upsert (T11; R10, R11) and the report row (T12; R9).

A single embedded DuckDB store holds three tables (plan.md §Persistence):

- ``monthly_production`` — one row per ``MonthlyProduction``; PK ``(field_npdid, year, month)``.
- ``field``             — one row per ``Field``; PK ``field_npdid``.
- ``ingestion_report``  — one row **appended** per run (audit history), keyed by ``retrieved_at``.

The two data tables' columns equal their model's fields **exactly** — derived from the Pydantic
model field order — so a persisted row reconstructs into the frozen model under ``extra="forbid"``
(no stray columns like an ``ingested_at``); the acceptance suite does exactly that round-trip.

Idempotency (R11): the data tables upsert with ``INSERT ... ON CONFLICT (<pk>) DO UPDATE`` keyed on
each PK, so re-running over identical data updates in place — never a duplicate field-month or
field. The whole data persist runs in **one transaction that commits**, so a reopened connection
sees the rows (R10) and a mid-run failure leaves the store unchanged. The ``ingestion_report`` row
is *appended* (not upserted) — it is run-history, deliberately not idempotent (plan.md, T6 scope).
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import duckdb

from ncs.contracts import Field, IngestionReport, MonthlyProduction

# Column order for the two data tables, taken straight from the frozen models so the table columns
# equal the model fields exactly (the round-trip the acceptance tests rely on).
_PRODUCTION_COLUMNS: tuple[str, ...] = tuple(MonthlyProduction.model_fields)
_FIELD_COLUMNS: tuple[str, ...] = tuple(Field.model_fields)

# DDL — keys enforce R4/R5 uniqueness and anchor the R11 upsert (plan.md §Persistence schema).
_CREATE_FIELD = """
CREATE TABLE IF NOT EXISTS field (
    field_npdid             BIGINT PRIMARY KEY,
    field_name              VARCHAR NOT NULL,
    current_activity_status VARCHAR,
    hc_type                 VARCHAR,
    main_area               VARCHAR,
    operator                VARCHAR,
    discovery_year          INTEGER,
    geometry_wkt            VARCHAR
)
"""

_CREATE_MONTHLY_PRODUCTION = """
CREATE TABLE IF NOT EXISTS monthly_production (
    field_npdid     BIGINT  NOT NULL,
    field_name      VARCHAR NOT NULL,
    year            INTEGER NOT NULL,
    month           INTEGER NOT NULL,
    oil             DOUBLE,
    gas             DOUBLE,
    ngl             DOUBLE,
    condensate      DOUBLE,
    oil_equivalents DOUBLE,
    produced_water  DOUBLE,
    PRIMARY KEY (field_npdid, year, month)
)
"""

_CREATE_INGESTION_REPORT = """
CREATE TABLE IF NOT EXISTS ingestion_report (
    retrieved_at                TIMESTAMPTZ PRIMARY KEY,
    sources                     JSON     NOT NULL,
    production_records          BIGINT   NOT NULL,
    distinct_production_fields  BIGINT   NOT NULL,
    fields                      BIGINT   NOT NULL,
    unmatched_production_npdids BIGINT[] NOT NULL,
    unmatched_field_npdids      BIGINT[] NOT NULL
)
"""


def configure_session(con: duckdb.DuckDBPyConnection) -> None:
    """Pin the connection's session timezone to UTC (an explicit, connection-mutating step).

    Kept separate from ``create_schema`` (DDL only) because this reconfigures the caller's
    connection — a side effect ``ingest`` must opt into deliberately, not a hidden consequence of
    creating tables. ``ingestion_report.retrieved_at`` is a ``TIMESTAMPTZ`` carrying a true-UTC
    instant (R9); DuckDB renders a ``TIMESTAMPTZ`` on read in the session timezone, so without this
    the read-back ``datetime`` would carry a non-zero local offset even though the instant is
    correct. Pinning UTC makes it read back with a zero offset (R9: UTC).
    """
    con.execute("SET TimeZone='UTC'")


def create_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the three tables if they do not already exist (idempotent DDL — DDL only)."""
    con.execute(_CREATE_FIELD)
    con.execute(_CREATE_MONTHLY_PRODUCTION)
    con.execute(_CREATE_INGESTION_REPORT)


def _upsert_sql(table: str, columns: Sequence[str], pk_columns: Sequence[str]) -> str:
    """Build an ``INSERT ... ON CONFLICT (<pk>) DO UPDATE`` statement for ``table`` (R11).

    Inserts all ``columns`` positionally and, on a primary-key conflict, updates every non-key
    column to the incoming row's value (``excluded``) — the in-place upsert that makes a re-run
    idempotent. Both data tables have non-key columns; we assert that here rather than carry an
    untested ``DO NOTHING`` fallback for a hypothetical all-key table.
    """
    placeholders = ", ".join("?" for _ in columns)
    column_list = ", ".join(columns)
    non_key = [c for c in columns if c not in pk_columns]
    assert non_key, f"{table} has no non-key columns to upsert; ON CONFLICT DO UPDATE needs at least one"
    conflict_target = ", ".join(pk_columns)
    assignments = ", ".join(f"{c} = excluded.{c}" for c in non_key)
    return (
        f"INSERT INTO {table} ({column_list}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_target}) DO UPDATE SET {assignments}"
    )


_UPSERT_PRODUCTION = _upsert_sql(
    "monthly_production", _PRODUCTION_COLUMNS, ("field_npdid", "year", "month")
)
_UPSERT_FIELD = _upsert_sql("field", _FIELD_COLUMNS, ("field_npdid",))


def _model_row(model: MonthlyProduction | Field, columns: Sequence[str]) -> list[object]:
    """Extract a model's values in ``columns`` order — the positional row for the upsert."""
    return [getattr(model, column) for column in columns]


def persist_data(
    con: duckdb.DuckDBPyConnection,
    production: Sequence[MonthlyProduction],
    fields: Sequence[Field],
) -> None:
    """Upsert the production and field models into DuckDB in one committed transaction (R10, R11).

    Both tables are written inside a single ``BEGIN``/``COMMIT`` so a mid-run failure rolls back
    (the store is left unchanged) and a successful run is durable — a reopened connection sees the
    rows. ``executemany`` runs the per-table ``ON CONFLICT DO UPDATE`` over every model row, so a
    re-run upserts in place rather than duplicating.
    """
    production_rows = [_model_row(m, _PRODUCTION_COLUMNS) for m in production]
    field_rows = [_model_row(f, _FIELD_COLUMNS) for f in fields]

    con.execute("BEGIN TRANSACTION")
    try:
        if field_rows:
            con.executemany(_UPSERT_FIELD, field_rows)
        if production_rows:
            con.executemany(_UPSERT_PRODUCTION, production_rows)
    except Exception:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


def persist_report(con: duckdb.DuckDBPyConnection, report: IngestionReport) -> None:
    """Append the run's ``IngestionReport`` as one ``ingestion_report`` row (R9), and commit.

    Appended, **not** upserted — the table is run-history keyed by ``retrieved_at`` (one row per
    run). ``sources`` is serialized to JSON (the typed ``SourceRef`` shape is asserted on the
    returned report, so the persisted JSON is kept simple); the two unmatched lists land in native
    DuckDB ``BIGINT[]`` columns, which read back as Python lists.
    """
    sources_json = json.dumps(
        [
            {
                "dataset": source.dataset.value,
                "url": str(source.url),
                "transport": source.transport.value,
            }
            for source in report.sources
        ]
    )

    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(
            """
            INSERT INTO ingestion_report (
                retrieved_at, sources,
                production_records, distinct_production_fields, fields,
                unmatched_production_npdids, unmatched_field_npdids
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                report.retrieved_at,
                sources_json,
                report.counts.production_records,
                report.counts.distinct_production_fields,
                report.counts.fields,
                report.unmatched_production_npdids,
                report.unmatched_field_npdids,
            ],
        )
    except Exception:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


def count_production_rows(con: duckdb.DuckDBPyConnection) -> int:
    """Persisted ``monthly_production`` row count (the R9 completeness/count source of truth)."""
    (count,) = con.execute("SELECT count(*) FROM monthly_production").fetchone()
    return count


def count_distinct_production_fields(con: duckdb.DuckDBPyConnection) -> int:
    """Distinct ``field_npdid`` persisted in ``monthly_production`` (a RecordCounts value, R9)."""
    (count,) = con.execute(
        "SELECT count(DISTINCT field_npdid) FROM monthly_production"
    ).fetchone()
    return count


def count_field_rows(con: duckdb.DuckDBPyConnection) -> int:
    """Persisted ``field`` row count (a RecordCounts value, R9)."""
    (count,) = con.execute("SELECT count(*) FROM field").fetchone()
    return count
