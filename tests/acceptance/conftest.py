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

002 addendum (additive — 001's fixtures above are untouched)
------------------------------------------------------------
The 002 forecasting persistence suite (``test_forecast_persistence.py``, R8) reuses the same
``con`` fixture and adds one fixture, ``seed_monthly_production`` — a helper that writes a list of
synthetic ``MonthlyProduction`` rows into the store's ``monthly_production`` table via the **frozen
001** persistence seam (``ncs.persist.create_schema`` + ``persist_data``). That is the hermetic way
to populate the store with controlled series (no SODIR CSV, no network) before driving
``run_forecasts(con)`` — matching plan.md §Input source ("seed the store (insert ``MonthlyProduction``
rows ...), then forecast"). ``ncs.persist`` is imported lazily inside the fixture so this addendum
does not change the collection behaviour of the 001 suites.

003 addendum (additive — 001/002 fixtures above are untouched)
--------------------------------------------------------------
The 003 API acceptance suites need a *seeded store + ``TestClient``* seam, which lives in a separate
module ``conftest_api.py`` (the seeded-field constants, the ``seeded_db`` / ``client`` fixtures). It
is registered as a pytest plugin via the ``pytest_plugins`` line at the bottom of this file so those
fixtures are visible to the API suites **without** editing any 001/002 fixture above. Keeping the
003 machinery in its own module (rather than inlined here) means a failure to import ``ncs.api`` /
``fastapi`` only affects the API suites that request its fixtures, not the 001/002 collection.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
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


# ============================================================ 002 addendum (additive) =============
# Seeding helper for the 002 forecasting persistence suite (R8). Writes synthetic
# ``MonthlyProduction`` rows into ``monthly_production`` via the frozen 001 persistence seam, so the
# store is populated hermetically (no SODIR CSV / network) before ``run_forecasts(con)`` reads it.

SeedMonthlyProduction = Callable[[duckdb.DuckDBPyConnection, Sequence[object]], None]


@pytest.fixture
def seed_monthly_production() -> SeedMonthlyProduction:
    """Return a helper that writes ``MonthlyProduction`` rows into the store (frozen 001 seam).

    Usage in the 002 persistence suite::

        seed_monthly_production(con, all_rows(clean_decline(1), short_history(2)))
        run = run_forecasts(con)

    It calls the **frozen 001** ``ncs.persist.create_schema`` (creates ``monthly_production`` etc.)
    then ``persist_data(con, rows, fields=[])`` to upsert the production rows — exactly how 001 lands
    those models, so the table 002 reads from is byte-identical to a real ingest's. No ``Field`` rows
    are needed: the forecaster keys on ``field_npdid`` from ``monthly_production`` alone (plan.md
    §Input source; ``field_name`` is off the forecast contract). ``ncs.persist`` is imported lazily so
    this fixture does not alter the 001 suites' collection behaviour.
    """

    def _seed(con: duckdb.DuckDBPyConnection, rows: Sequence[object]) -> None:
        from ncs.persist import create_schema, persist_data

        create_schema(con)
        persist_data(con, list(rows), [])

    return _seed


# ============================================================ 003 addendum (additive) =============
# Register the 003 API acceptance fixtures (seeded store + TestClient seam) as a pytest plugin. The
# fixtures themselves live in ``conftest_api.py`` so a missing ``ncs.api`` / ``fastapi`` import (the
# intended TDD red until 003-T1/T7..T9) only fails the API suites, never 001/002 collection. This is
# the single additive line wiring the 003 fixtures in — no 001/002 fixture above is altered.
pytest_plugins = ["conftest_api"]
