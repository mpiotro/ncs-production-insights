"""Shared acceptance-suite fixtures for 001 ingestion (authored at task 001-T2).

Everything the whole acceptance suite (T2-T6) reuses lives here:

* ``SODIR_FIXTURES`` — path constant to the canonical local SODIR sample
  (``tests/acceptance/fixtures/sodir/``; see its ``README.md`` manifest).
* ``con`` — a tmp_path-backed DuckDB connection (a real file, **not** ``:memory:``,
  so the persistence / idempotency suite can reopen the same store).
* ``settings_factory`` / ``good_settings`` — build the internal ``Settings`` object that
  points ``ingest()``'s fetch at the local fixtures, with knobs to make a dataset's
  **primary** source bad so the R3 fallback path is exercised.

These tests are deliberately **red first** (TDD): ``ncs.ingest`` / ``ncs.config`` do not
exist yet, so importing them raises at collection time. That is the correct failure until
the developer implements the seam at 001-T7/T8.

Hermetic by construction (tasks.md §Resolved): the source seam reads local files only — no
live SODIR network call is ever made from the acceptance suite.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import duckdb
import pytest

# --- Path to the shared canonical SODIR fixture set -------------------------------------

SODIR_FIXTURES: Path = Path(__file__).parent / "fixtures" / "sodir"

# Individual fixture files (the canonical sample documented in fixtures/sodir/README.md).
PRODUCTION_PRIMARY: Path = SODIR_FIXTURES / "production_primary.csv"
PRODUCTION_FALLBACK: Path = SODIR_FIXTURES / "production_fallback.csv"
FIELD_PRIMARY_JSON: Path = SODIR_FIXTURES / "field_primary.json"
FIELD_FALLBACK_CSV: Path = SODIR_FIXTURES / "field_fallback.csv"

# A path that is guaranteed not to resolve — used to force a dataset's primary source to
# fail so the R3 fallback is exercised (connection/empty/malformed → next transport).
MISSING_PATH: str = str(SODIR_FIXTURES / "does_not_exist__force_fallback.csv")


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    """A DuckDB connection backed by a real file under pytest's tmp_path.

    A file (not ``:memory:``) on purpose: the persistence / idempotency suite (T5) needs to
    close and reopen the same store, and an in-memory database would vanish between
    connections. The DB path is owned by the test, never by ``Settings`` (the seam takes the
    connection as an argument: ``ingest(con, settings)``).
    """
    db_file = tmp_path / "ingest.duckdb"
    connection = duckdb.connect(str(db_file))
    try:
        yield connection
    finally:
        connection.close()


# --- Settings builder (the configuration seam ingest() reads) ---------------------------
#
# The internal config shape (implemented by the developer at 001-T8 to match this usage):
#
#     class Source(BaseModel):
#         transport: Transport      # Transport.rest | Transport.csv
#         location: str             # local fixture path here; a URL in production
#
#     class Settings(BaseModel):
#         production_sources: list[Source]   # ordered: primary first, then fallback(s)
#         field_sources:      list[Source]   # ordered: primary first, then fallback(s)
#
# `ingest()` tries each dataset's sources in order and uses the first that succeeds.


SettingsFactory = Callable[..., object]


@pytest.fixture
def settings_factory() -> SettingsFactory:
    """Return a builder for the internal ``Settings``, pointed at the local fixtures.

    Keyword knobs let a test break a dataset's **primary** source so the R3 fallback path
    runs, without rebuilding the whole object by hand:

    * ``break_production_primary=True`` — production primary points at a missing CSV path;
      the production fallback (``production_fallback.csv``) must then win.
    * ``break_field_primary=True`` — the field REST primary points at a missing path; the
      field CSV fallback (``field_fallback.csv``) must then win, flipping the winning
      transport ``rest -> csv`` (observable in the report's ``SourceRef.transport``).

    Built lazily inside the factory so import of ``ncs.config`` happens at call time — these
    tests still **collect** (and then fail for the right reason) before the seam exists.
    """

    def _build(
        *,
        break_production_primary: bool = False,
        break_field_primary: bool = False,
    ) -> object:
        from ncs.config import Settings, Source
        from ncs.contracts import Transport

        production_primary_loc = (
            MISSING_PATH if break_production_primary else str(PRODUCTION_PRIMARY)
        )
        field_primary_loc = MISSING_PATH if break_field_primary else str(FIELD_PRIMARY_JSON)

        return Settings(
            # Production: CSV primary, CSV-class fallback (same report, alternate format).
            production_sources=[
                Source(transport=Transport.csv, location=production_primary_loc),
                Source(transport=Transport.csv, location=str(PRODUCTION_FALLBACK)),
            ],
            # Field/geometry: REST primary (layer 7100), CSV fallback (fldArea WKT).
            field_sources=[
                Source(transport=Transport.rest, location=field_primary_loc),
                Source(transport=Transport.csv, location=str(FIELD_FALLBACK_CSV)),
            ],
        )

    return _build


@pytest.fixture
def good_settings(settings_factory: SettingsFactory) -> object:
    """``Settings`` with both datasets' primary sources valid (the happy path for R1/R2)."""
    return settings_factory()
