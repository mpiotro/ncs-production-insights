"""The injected read-only DuckDB dependency — ``get_connection`` (task 003-T7; R1).

``get_connection`` is the **single seam** every route depends on (``Depends(get_connection)``) and
the one the acceptance suite overrides (``app.dependency_overrides[get_connection] = ...``) to point
the app at a hermetically seeded store. It yields a DuckDB connection opened **read-only**
(``duckdb.connect(path, read_only=True)``) against ``ApiSettings.db_path`` and **closes it after the
request** — so read-only is enforced at the engine level (R1: even a stray write SQL would raise),
not merely by convention.

The path is resolved from the environment via ``ApiSettings.from_env`` at request time, so the
running API never hard-codes a DB location (principle 7). There is no writable connection anywhere in
the API process — populating the store is the separate ``ncs.api.seed`` entrypoint (plan.md §Store
population), never an endpoint.
"""

from __future__ import annotations

from collections.abc import Iterator

import duckdb

from ncs.api.settings import ApiSettings


def get_connection() -> Iterator[duckdb.DuckDBPyConnection]:
    """Yield a read-only DuckDB connection on the configured store, closed after the request (R1).

    Opened ``read_only=True`` so the engine itself forbids any write — the structural R1 guarantee.
    The connection is closed in the ``finally`` so each request gets a fresh handle and nothing leaks.
    The acceptance suite overrides this dependency to target its seeded fixture file; production reads
    ``ApiSettings.from_env().db_path``.
    """
    settings = ApiSettings.from_env()
    con = duckdb.connect(settings.db_path, read_only=True)
    try:
        yield con
    finally:
        con.close()
