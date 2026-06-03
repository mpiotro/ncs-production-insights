"""Unit tests for ``ncs.persist`` (developer-owned, white-box) — 001-T11 / R10, R11.

White-box checks of the DuckDB persistence layer: the data-table columns equal the model fields
exactly (the round-trip the acceptance suite depends on), the ``ON CONFLICT DO UPDATE`` upsert is
idempotent and updates in place, the data persist commits (durable across a reopen), and the report
row is *appended* (run-history, not upserted) with native array / JSON columns. Driven against a
real tmp DuckDB file so the actual SQL runs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pytest

from ncs.contracts import (
    Dataset,
    Field,
    IngestionReport,
    MonthlyProduction,
    RecordCounts,
    SourceRef,
    Transport,
)
from ncs.persist import (
    _FIELD_COLUMNS,
    _PRODUCTION_COLUMNS,
    configure_session,
    count_distinct_production_fields,
    count_field_rows,
    count_production_rows,
    create_schema,
    persist_data,
    persist_report,
)

_POLYGON = "POLYGON ((2.0 60.0, 2.5 60.0, 2.5 60.5, 2.0 60.5, 2.0 60.0))"


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    """A file-backed DuckDB connection (a real file so durability across a reopen is testable)."""
    connection = duckdb.connect(str(tmp_path / "unit.duckdb"))
    try:
        yield connection
    finally:
        connection.close()


def _prod(npdid: int, year: int, month: int, oil: float | None = 1.0) -> MonthlyProduction:
    return MonthlyProduction(
        field_npdid=npdid, field_name=f"F{npdid}", year=year, month=month, oil=oil
    )


def _field(npdid: int) -> Field:
    return Field(field_npdid=npdid, field_name=f"F{npdid}", geometry_wkt=_POLYGON)


# --- Columns equal the model fields exactly (the reconstruction round-trip) ----------------------


def test_table_columns_equal_model_fields_exactly(con: duckdb.DuckDBPyConnection) -> None:
    """Each data table's columns equal its model's fields exactly — no stray columns (R10).

    The acceptance suite reconstructs ``Model(**row)`` under ``extra="forbid"``; an extra column
    (e.g. an ``ingested_at``) would break that. Pin the column lists to the model field order.
    """
    create_schema(con)
    persist_data(con, [_prod(1001, 2022, 1)], [_field(1001)])

    prod_cols = [d[0] for d in con.execute("SELECT * FROM monthly_production").description]
    field_cols = [d[0] for d in con.execute("SELECT * FROM field").description]

    assert tuple(prod_cols) == _PRODUCTION_COLUMNS == tuple(MonthlyProduction.model_fields)
    assert tuple(field_cols) == _FIELD_COLUMNS == tuple(Field.model_fields)


# --- R11: idempotent upsert ----------------------------------------------------------------------


def test_rerun_over_identical_data_does_not_duplicate(con: duckdb.DuckDBPyConnection) -> None:
    """Persisting the same rows twice leaves counts unchanged — upsert, not append (R11)."""
    production = [_prod(1001, 2022, 1), _prod(1001, 2022, 2)]
    fields = [_field(1001)]

    create_schema(con)
    persist_data(con, production, fields)
    assert count_production_rows(con) == 2
    assert count_field_rows(con) == 1

    persist_data(con, production, fields)  # identical re-run
    assert count_production_rows(con) == 2  # no duplicates
    assert count_field_rows(con) == 1


def test_upsert_updates_value_in_place(con: duckdb.DuckDBPyConnection) -> None:
    """A changed value for an existing key updates in place (one row, new value), not a duplicate."""
    create_schema(con)
    persist_data(con, [_prod(1001, 2022, 1, oil=1.0)], [_field(1001)])
    persist_data(con, [_prod(1001, 2022, 1, oil=2.5)], [_field(1001)])  # same key, new oil

    rows = con.execute(
        "SELECT oil FROM monthly_production WHERE field_npdid = 1001 AND year = 2022 AND month = 1"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == pytest.approx(2.5)


def test_none_volume_persists_as_sql_null(con: duckdb.DuckDBPyConnection) -> None:
    """A None volume lands as SQL NULL and reads back as Python None (the absent→null contract)."""
    create_schema(con)
    persist_data(con, [_prod(1001, 2022, 1, oil=None)], [_field(1001)])

    (oil,) = con.execute(
        "SELECT oil FROM monthly_production WHERE field_npdid = 1001"
    ).fetchone()
    assert oil is None


# --- R10: durability across a reopen -------------------------------------------------------------


def test_data_survives_connection_reopen(tmp_path: Path) -> None:
    """The committed data persists in the file: a fresh connection still sees the rows (R10)."""
    db_file = tmp_path / "reopen.duckdb"
    write_con = duckdb.connect(str(db_file))
    try:
        create_schema(write_con)
        persist_data(write_con, [_prod(1001, 2022, 1)], [_field(1001)])
    finally:
        write_con.close()

    reopened = duckdb.connect(str(db_file))
    try:
        assert count_production_rows(reopened) == 1
        assert count_field_rows(reopened) == 1
    finally:
        reopened.close()


# --- Counts the report builder reads -------------------------------------------------------------


def test_count_helpers(con: duckdb.DuckDBPyConnection) -> None:
    """The count helpers report production rows, distinct production fields, and field rows."""
    create_schema(con)
    persist_data(
        con,
        [_prod(1001, 2022, 1), _prod(1001, 2022, 2), _prod(1009, 2023, 3)],
        [_field(1001), _field(1004)],
    )
    assert count_production_rows(con) == 3
    assert count_distinct_production_fields(con) == 2  # 1001, 1009
    assert count_field_rows(con) == 2


# --- R9 persistence shape: report appended, array/JSON columns -----------------------------------


def _report(retrieved_at: datetime) -> IngestionReport:
    return IngestionReport(
        sources=[
            SourceRef(dataset=Dataset.production, url="file:///tmp/p.csv", transport=Transport.csv),
            SourceRef(dataset=Dataset.field, url="file:///tmp/f.json", transport=Transport.rest),
        ],
        retrieved_at=retrieved_at,
        counts=RecordCounts(production_records=10, distinct_production_fields=4, fields=4),
        unmatched_production_npdids=[1009],
        unmatched_field_npdids=[1004],
    )


def test_report_row_is_appended_with_array_columns(con: duckdb.DuckDBPyConnection) -> None:
    """Each run appends one ingestion_report row; unmatched lists read back as Python lists (R9)."""
    create_schema(con)
    persist_report(con, _report(datetime.now(timezone.utc)))

    (n,) = con.execute("SELECT count(*) FROM ingestion_report").fetchone()
    assert n == 1

    unmatched_production, unmatched_field = con.execute(
        "SELECT unmatched_production_npdids, unmatched_field_npdids FROM ingestion_report"
    ).fetchone()
    assert isinstance(unmatched_production, list)
    assert unmatched_production == [1009]
    assert unmatched_field == [1004]


def test_persist_data_rolls_back_on_failure(con: duckdb.DuckDBPyConnection) -> None:
    """A mid-persist failure rolls back the transaction, leaving the store unchanged (R10/R11).

    The whole data persist runs in one transaction. Seed a committed row, then attempt a persist
    that fails partway (a field whose ``field_npdid`` is the wrong type for the BIGINT column raises
    inside the transaction): the store must be left exactly as before — the partial work rolled back
    and a subsequent persist still works (the connection is not stuck in an aborted transaction).
    """
    create_schema(con)
    persist_data(con, [_prod(1001, 2022, 1)], [_field(1001)])
    assert count_production_rows(con) == 1

    class _BadField:
        # Quacks like a Field for _model_row(getattr) but field_npdid can't bind to BIGINT.
        field_npdid = "not-an-int"
        field_name = "BAD"
        current_activity_status = None
        hc_type = None
        main_area = None
        operator = None
        discovery_year = None
        geometry_wkt = None

    with pytest.raises(Exception):
        persist_data(con, [_prod(1002, 2022, 1)], [_BadField()])  # type: ignore[list-item]

    # Rolled back: the failed run added nothing, and the connection is usable again.
    assert count_production_rows(con) == 1
    assert count_field_rows(con) == 1
    persist_data(con, [_prod(1003, 2022, 1)], [_field(1003)])
    assert count_production_rows(con) == 2


# --- R9: session timezone is configured explicitly, not as a create_schema side effect -----------


def test_configure_session_makes_timestamptz_read_back_as_utc(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """After configure_session, a persisted TIMESTAMPTZ reads back with a zero offset (R9: UTC).

    DuckDB renders a TIMESTAMPTZ on read in the session timezone; pinning UTC is what makes
    ``retrieved_at`` round-trip with a zero offset regardless of the host's local zone. This locks
    in the behavior at the persist seam (the seam 003 reuses).
    """
    create_schema(con)
    configure_session(con)
    persist_report(con, _report(datetime.now(timezone.utc)))

    (retrieved_at,) = con.execute(
        "SELECT retrieved_at FROM ingestion_report"
    ).fetchone()
    assert retrieved_at.tzinfo is not None
    assert retrieved_at.utcoffset().total_seconds() == 0


def test_create_schema_does_not_change_session_timezone(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """create_schema is DDL-only: it must not reconfigure the caller's session timezone (S1).

    The tz pin moved to the explicit configure_session step; creating tables must leave the
    connection's TimeZone setting exactly as it was.
    """
    (before,) = con.execute("SELECT current_setting('TimeZone')").fetchone()
    create_schema(con)
    (after,) = con.execute("SELECT current_setting('TimeZone')").fetchone()
    assert after == before


def test_two_reports_append_distinct_rows(con: duckdb.DuckDBPyConnection) -> None:
    """The report table is run-history: two runs with distinct timestamps append two rows (R9).

    Uses microsecond-resolution UTC stamps (as the pipeline does) so the TIMESTAMPTZ PK does not
    collide between back-to-back runs.
    """
    create_schema(con)
    first = datetime.now(timezone.utc)
    persist_report(con, _report(first))
    second = first.replace(microsecond=(first.microsecond + 1) % 1_000_000)
    persist_report(con, _report(second))

    (n,) = con.execute("SELECT count(*) FROM ingestion_report").fetchone()
    assert n == 2
