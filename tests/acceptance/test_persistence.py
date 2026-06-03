"""Acceptance suite: persistence & idempotent re-run — EARS 001-R10, 001-R11 (task 001-T5).

Black-box through the public seam ``ingest(con, settings)`` against the shared canonical SODIR
fixtures (``fixtures/sodir/``, see its README manifest) — no live network. Two requirements:

* **001-R10** — "WHEN normalization completes, the system SHALL persist the typed models to the
  single DuckDB store." Acceptance: *models are queryable from the DuckDB file after a run.* Proven
  two ways here — (a) the two data tables (``monthly_production``, ``field``) hold the expected rows
  queryable with plain SQL after a run via the ``con`` fixture, and (b) **durability across a
  reopen**: a self-managed DuckDB *file* is written, the connection **closed**, and a **fresh**
  connection to the same file still sees the rows — proving the data lives in the file, not in
  connection state.

* **001-R11** — "WHEN an ingestion run repeats over identical source data, the system SHALL upsert by
  key so the store holds no duplicate field-month or field records (idempotent)." Acceptance:
  *running twice over the same input leaves record counts unchanged (no duplicates).* Proven by
  running ``ingest`` two (and three) times over the same fixtures and asserting the counts, the key
  uniqueness, and the **exact key set** are stable, and that a known row is upserted in place (its
  value unchanged), not duplicated.

Scope boundary (task hard rule): R10/R11 here concern the two **data** tables only. The
``ingestion_report`` table is **append-one-row-per-run by design** (audit history, keyed by
``retrieved_at``) and is therefore *not* idempotent — it is **T6's** (R9). This suite never asserts
on, nor even counts, ``ingestion_report``.

Like the rest of the suite these import ``ncs.ingest``, which does not exist yet, so the module is
**red at collection time** until the developer builds the seam and the persist/upsert step
(001-T7/T11). That is the intended TDD starting state; the assertions are written to go green once
persistence is implemented as designed in plan.md §"Persistence & idempotency" — they pin
**outcomes** (no duplicate rows, durable across a reopen, stable key set), never the mechanism
(``CREATE TABLE IF NOT EXISTS`` / ``INSERT ... ON CONFLICT DO UPDATE``).
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

# Frozen contract types (contracts.md). Importing at module scope makes the whole suite go red for
# the right reason — this resolves only once the developer adds the package modules.
from ncs import ingest

# --- Expected derived values pinned to the canonical fixture set (fixtures/sodir/README.md) -------

EXPECTED_PRODUCTION_ROWS = 10
EXPECTED_FIELD_ROWS = 4

# Field NPDIDs (field_primary.json / field_fallback.csv) — the full, exact ``field`` key set.
EXPECTED_FIELD_NPDIDS = {1001, 1002, 1003, 1004}

# The full, exact ``monthly_production`` composite key set (production_primary.csv, value-checked):
# ALPHA/1001 spans 2021-11..2022-02; BETA/1002 spans 2022-01,02 + 2023-01; GAMMA/1003 2022-06,07;
# ORPHANPROD/1009 2023-03. Ten keys — the invariant the idempotency tests prove stays identical.
EXPECTED_PRODUCTION_KEYS = {
    (1001, 2021, 11),
    (1001, 2021, 12),
    (1001, 2022, 1),
    (1001, 2022, 2),
    (1002, 2022, 1),
    (1002, 2022, 2),
    (1002, 2023, 1),
    (1003, 2022, 6),
    (1003, 2022, 7),
    (1009, 2023, 3),
}

# A known row whose value must be upserted **in place** (unchanged) on a re-run, never duplicated.
# ALPHA 2022-01 (production_primary.csv row 4): the single fixture ``oil`` value for that key.
NPDID_ALPHA = 1001
ALPHA_JAN_YEAR = 2022
ALPHA_JAN_MONTH = 1
ALPHA_JAN_OIL = 1.180


# --- Small DuckDB read helpers (style shared with the sibling suites) -----------------------------


def _count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    """Row count of ``table``."""
    (n,) = con.execute(f"SELECT count(*) FROM {table}").fetchone()
    return n


def _production_keys(con: duckdb.DuckDBPyConnection) -> set[tuple[int, int, int]]:
    """The set of ``(field_npdid, year, month)`` composite keys persisted in ``monthly_production``."""
    return {
        (row[0], row[1], row[2])
        for row in con.execute(
            "SELECT field_npdid, year, month FROM monthly_production"
        ).fetchall()
    }


def _field_npdids(con: duckdb.DuckDBPyConnection) -> set[int]:
    """The set of ``field_npdid`` keys persisted in ``field``."""
    return {row[0] for row in con.execute("SELECT field_npdid FROM field").fetchall()}


# ============================================================ R10 — typed models persisted ========
# "Models are queryable from the DuckDB file after a run": the normalized models land as plain
# queryable rows in the two data tables.


def test_r10_data_models_are_persisted_and_queryable(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R10: after a run, both data tables hold the expected rows, queryable with plain SQL.

    The whole point of R10 — the normalized ``MonthlyProduction`` / ``Field`` models are persisted to
    the single DuckDB store and come back as ordinary rows: ``monthly_production`` has 10 rows and
    ``field`` has 4. (Full mapping/typing of those rows is T3's; this test is about *persistence*.)
    """
    ingest(con, good_settings)

    assert _count(con, "monthly_production") == EXPECTED_PRODUCTION_ROWS
    assert _count(con, "field") == EXPECTED_FIELD_ROWS


def test_r10_known_row_is_queryable_after_run(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R10: a known persisted record is retrievable by its key (a light spot-check).

    ALPHA 2022-01 exists as exactly one ``monthly_production`` row after the run — confirming the
    models really landed as queryable rows, not that the table merely has the right cardinality.
    (Value-by-value mapping is T3's; here we only assert the row is *present and singular*.)
    """
    ingest(con, good_settings)

    (n,) = con.execute(
        "SELECT count(*) FROM monthly_production "
        "WHERE field_npdid = ? AND year = ? AND month = ?",
        [NPDID_ALPHA, ALPHA_JAN_YEAR, ALPHA_JAN_MONTH],
    ).fetchone()
    assert n == 1, f"expected exactly one ALPHA 2022-01 row after a run, got {n}"


def test_r10_persisted_rows_survive_connection_reopen(
    tmp_path: Path, good_settings: object
) -> None:
    """001-R10 (durability — the strong evidence): the rows survive **closing and reopening** the file.

    This test owns its own DuckDB *file* so it controls open/close/reopen (the ``con`` fixture closes
    only at teardown, which can't show durability mid-test). Sequence: open a connection to
    ``store.duckdb``, ``ingest(con, good_settings)``, **close** it, then open a **fresh** connection
    to the *same* file and assert the 10 production / 4 field rows are still there. Reopening proves
    the data is in the file (persisted), not just in the original connection's state — exactly the
    R10 acceptance criterion "queryable from the DuckDB file after a run".

    ``import duckdb`` directly here is legitimately within ``tests/acceptance/`` (the file lifecycle
    *is* the thing under test); the conftest's ``con`` deliberately can't express the close/reopen.
    """
    db_file = tmp_path / "store.duckdb"

    # --- Run the ingest, then fully CLOSE the connection (flush to the file). ---
    write_con = duckdb.connect(str(db_file))
    try:
        ingest(write_con, good_settings)
    finally:
        write_con.close()

    # --- Open a brand-new connection to the SAME file: the rows must still be there. ---
    reopened = duckdb.connect(str(db_file))
    try:
        assert _count(reopened, "monthly_production") == EXPECTED_PRODUCTION_ROWS
        assert _count(reopened, "field") == EXPECTED_FIELD_ROWS

        # And the exact key sets persisted, not merely the counts — the data, not just the shape.
        assert _production_keys(reopened) == EXPECTED_PRODUCTION_KEYS
        assert _field_npdids(reopened) == EXPECTED_FIELD_NPDIDS
    finally:
        reopened.close()


# ============================================================ R11 — idempotent re-run (upsert) ====
# "Running twice over the same input leaves record counts unchanged (no duplicates)." A naive append
# would double the rows (or raise on the PK); upsert-by-key keeps the store stable.


def test_r11_second_run_leaves_data_counts_unchanged(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R11: ingesting the same fixtures **twice** leaves both data tables at their first counts.

    After two runs over identical source data, ``monthly_production`` still has exactly 10 rows and
    ``field`` still 4 — a naive append would double them (or raise on the primary key). Counts are
    asserted after run 1 as well, so a regression that breaks the *first* persist is distinguishable
    from one that breaks idempotency on the *second*.
    """
    ingest(con, good_settings)
    assert _count(con, "monthly_production") == EXPECTED_PRODUCTION_ROWS
    assert _count(con, "field") == EXPECTED_FIELD_ROWS

    ingest(con, good_settings)  # identical source data, same connection/store
    assert _count(con, "monthly_production") == EXPECTED_PRODUCTION_ROWS, (
        "a second ingest over identical data must not add monthly_production rows (R11 idempotency)"
    )
    assert _count(con, "field") == EXPECTED_FIELD_ROWS, (
        "a second ingest over identical data must not add field rows (R11 idempotency)"
    )


def test_r11_keys_stay_unique_after_second_run(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R11: the keys stay unique after a re-run — upsert by key, not duplicate insertion.

    After the second run: on ``monthly_production`` the composite key is still unique
    (``count(*) == count(DISTINCT (field_npdid, year, month))``), and on ``field`` ``field_npdid`` is
    still unique. Either count diverging would mean a duplicate field-month or field slipped in.
    """
    ingest(con, good_settings)
    ingest(con, good_settings)

    (prod_total, prod_distinct) = con.execute(
        "SELECT count(*), count(DISTINCT (field_npdid, year, month)) FROM monthly_production"
    ).fetchone()
    assert prod_total == prod_distinct, (
        "monthly_production has duplicate (field_npdid, year, month) keys after a re-run: "
        f"{prod_total} rows but {prod_distinct} distinct composite keys (R11 upsert-by-key)"
    )
    assert prod_total == EXPECTED_PRODUCTION_ROWS

    (field_total, field_distinct) = con.execute(
        "SELECT count(*), count(DISTINCT field_npdid) FROM field"
    ).fetchone()
    assert field_total == field_distinct, (
        f"field has duplicate field_npdid keys after a re-run: {field_total} rows but "
        f"{field_distinct} distinct NPDIDs (R11 upsert-by-key)"
    )
    assert field_total == EXPECTED_FIELD_ROWS


def test_r11_known_row_is_upserted_in_place_not_duplicated(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R11: a known row is **updated in place** on a re-run — one row, same value (not corrupt).

    Idempotency is upsert, not merely "no extra rows somewhere": after the second run there is still
    exactly **one** ALPHA 2022-01 row and its ``oil`` is still the single fixture value (1.180). This
    catches both a stray duplicate of that key *and* a re-run that mangles the value on update.
    """
    ingest(con, good_settings)
    ingest(con, good_settings)

    rows = con.execute(
        "SELECT oil FROM monthly_production "
        "WHERE field_npdid = ? AND year = ? AND month = ?",
        [NPDID_ALPHA, ALPHA_JAN_YEAR, ALPHA_JAN_MONTH],
    ).fetchall()

    assert len(rows) == 1, (
        f"ALPHA 2022-01 must be a single upserted row after a re-run, got {len(rows)} rows "
        "(a duplicate means append, not upsert — R11)"
    )
    assert rows[0][0] == pytest.approx(ALPHA_JAN_OIL), (
        f"ALPHA 2022-01 oil must stay its single fixture value {ALPHA_JAN_OIL} after upsert, "
        f"got {rows[0][0]!r}"
    )


def test_r11_key_set_is_identical_across_repeated_runs(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R11 (the strong invariant): the **exact set of keys** is unchanged across three runs.

    Counts staying equal is necessary but not sufficient — it would also hold if a run swapped one
    key for another. So capture the full composite key set after run 1, run **twice more** over the
    same data, and assert the persisted key set (and the ``field`` NPDID set) is byte-for-byte
    identical each time. It is the *identity* of the rows, not just their number, that is stable.
    """
    ingest(con, good_settings)
    keys_after_run_1 = _production_keys(con)
    fields_after_run_1 = _field_npdids(con)

    # Guard: run 1 already produced the canonical key set (so a fixture drift surfaces here).
    assert keys_after_run_1 == EXPECTED_PRODUCTION_KEYS
    assert fields_after_run_1 == EXPECTED_FIELD_NPDIDS

    ingest(con, good_settings)  # run 2
    assert _production_keys(con) == keys_after_run_1, (
        "the production key set changed after a second identical run (R11: keys must be stable)"
    )
    assert _field_npdids(con) == fields_after_run_1

    ingest(con, good_settings)  # run 3 — idempotency holds beyond the first repeat
    assert _production_keys(con) == keys_after_run_1, (
        "the production key set changed after a third identical run (R11: keys must be stable)"
    )
    assert _field_npdids(con) == fields_after_run_1
    # And the counts never crept up across the three runs.
    assert _count(con, "monthly_production") == EXPECTED_PRODUCTION_ROWS
    assert _count(con, "field") == EXPECTED_FIELD_ROWS
