"""Unit tests for ``ncs.api.deps`` (developer-owned, white-box) — 003-T7 / R1.

White-box checks of the injected ``get_connection`` dependency: it yields a DuckDB connection opened
**read-only** against ``ApiSettings.db_path`` (resolved from the env), and **closes it** when the
generator is exhausted. Driven against a real seeded file with the DB path injected through the
process env (restored after), since that is the production resolution path. Read-only is proven both
by a successful SELECT and by a write attempt raising on the yielded connection.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pytest

from ncs.api.deps import get_connection
from ncs.persist import create_schema


@pytest.fixture
def db_with_env(tmp_path: Path):
    """Create a real store, point ``NCS_DB_PATH`` at it for the test, and restore the env after."""
    db_path = tmp_path / "deps.duckdb"
    con = duckdb.connect(str(db_path))
    create_schema(con)
    con.execute("INSERT INTO field (field_npdid, field_name) VALUES (9001, 'ALPHA')")
    con.close()

    previous = os.environ.get("NCS_DB_PATH")
    os.environ["NCS_DB_PATH"] = str(db_path)
    try:
        yield db_path
    finally:
        if previous is None:
            os.environ.pop("NCS_DB_PATH", None)
        else:
            os.environ["NCS_DB_PATH"] = previous


def test_get_connection_yields_a_usable_read_only_connection(db_with_env) -> None:
    """The dependency yields a connection that can SELECT the seeded store (R1)."""
    gen = get_connection()
    con = next(gen)
    try:
        (count,) = con.execute("SELECT count(*) FROM field").fetchone()
        assert count == 1
    finally:
        # Exhaust the generator so its ``finally`` closes the connection.
        with pytest.raises(StopIteration):
            next(gen)


def test_get_connection_is_read_only(db_with_env) -> None:
    """A write through the yielded connection raises — read-only is enforced at the engine level (R1)."""
    gen = get_connection()
    con = next(gen)
    try:
        with pytest.raises(duckdb.Error):
            con.execute("INSERT INTO field (field_npdid, field_name) VALUES (1, 'X')")
    finally:
        with pytest.raises(StopIteration):
            next(gen)


def test_get_connection_closes_the_connection_after_use(db_with_env) -> None:
    """Exhausting the generator closes the connection (no leaked handle) (R1)."""
    gen = get_connection()
    con = next(gen)
    with pytest.raises(StopIteration):
        next(gen)  # runs the finally -> con.close()

    # A closed DuckDB connection raises on further use.
    with pytest.raises(duckdb.Error):
        con.execute("SELECT 1")
