"""Shared seeded-store + ``TestClient`` fixtures for the 003 API acceptance suites (tasks 003-T2..T6).

This is the **003 acceptance seam** the five API suites (``test_api_fields`` / ``test_api_production``
/ ``test_api_forecast`` / ``test_api_geojson`` / ``test_api_meta``) drive the read-only FastAPI app
through. It is **additive** — the 001 ``conftest.py`` (and its 002 addendum) are untouched; these
fixtures live in a separate module and are surfaced to pytest via a single ``pytest_plugins`` line in
the package ``conftest.py`` (003 addendum). Nothing here changes the collection behaviour of the
001/002 suites.

What it builds (tasks.md §Resolved, plan.md §Store population — "seed hermetically, no network")
-----------------------------------------------------------------------------------------------
A temp DuckDB **file** is populated entirely through the **frozen** persistence seams:

* the 001 ``ncs.persist.create_schema`` + ``persist_data`` lands ``Field`` + ``MonthlyProduction``
  rows (the exact way a real ingest writes them, so 003 reads byte-identical tables);
* the 002 ``ncs.forecast.run_forecasts`` computes + persists ``field_forecast`` (+ points) for the
  >= 60-month fields only — so the *absence* of a forecast row is the genuine R4 insufficient-history
  signal, not a hand-faked gap.

No SODIR CSV, no live network — the production series come from the 002 ``forecast_histories``
builders (``clean_decline`` for a credible forecast). The exact seeded values are **pinned as module
constants** so the suites assert concretely.

The controlled field set (every suite reads these four — see the ``SEEDED_*`` constants)
----------------------------------------------------------------------------------------
* ``CLEAN_POLYGON`` — a 72-month clean-decline field with a **POLYGON** outline → gets a credible
  ``FieldForecast`` (R4 happy path; R5 polygon feature). It also carries the R3 **probe cells**: a
  known JSON-``null`` stream cell and a known real ``0.0`` cell at pinned ``(year, month)`` (see
  ``PROD_*`` constants) — the null-vs-zero crux. Those cells touch only *non-oe* streams, which the
  forecaster ignores, so the forecast stays credible.
* ``CLEAN_MULTIPOLYGON`` — a second 72-month clean-decline field with a **MULTIPOLYGON** outline →
  also forecastable (R5 multipolygon feature).
* ``SHORT_WITH_OUTLINE`` — a 40-month (< 60) field **with** an outline → **no** forecast row
  (R4 forecast-not-available, distinct from field-not-found).
* ``NULL_GEOMETRY`` — a 72-month field with **no** outline (``geometry_wkt=None``) → forecastable,
  but appears in GeoJSON as a feature with ``geometry: null`` (R5 null-geometry kept, not dropped).
  Long history on purpose so "no geometry" is the *only* thing that distinguishes its GeoJSON
  feature — it is still a normal field everywhere else.

The seam the developer builds to (T1 scaffolds ``ncs.api`` + adds ``fastapi``; T7–T9 implement it)
-------------------------------------------------------------------------------------------------
* ``from ncs.api import create_app`` — the FastAPI app **factory**.
* ``from ncs.api.deps import get_connection`` — the injected read-only-DuckDB dependency; the
  ``client`` fixture **overrides** it (``app.dependency_overrides[get_connection] = ...``) to point
  the app at the seeded file opened ``read_only=True``.
* ``from ncs.api.responses import FieldListResponse, ProductionHistoryResponse,
  FieldFeatureCollection, ErrorResponse, ErrorCode`` — the response models (suites may assert these
  or assert on ``response.json()`` directly).

These imports do **not** resolve yet (``ncs.api`` + ``fastapi`` are not built/installed until 003-T1
and implemented at 003-T7..T9), so every API suite is **red at collection time** — the correct TDD
failure until the developer fills the seam exactly as pinned here.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

from ncs.contracts import Field, MonthlyProduction

# The 002 history builders, reused for the production series (see module docstring). Imported by bare
# module name because ``tests/acceptance`` is on ``sys.path`` for the suite (rootdir layout), exactly
# how the 002 suites import it. ``add_months`` lets us name the probe-cell calendar the same way the
# builder lays its months out.
from forecast_histories import ANCHOR_MONTH, ANCHOR_YEAR, add_months, clean_decline

# ============================================================ The pinned seeded field set ==========
# Four fields, each with a distinct purpose (see the module docstring). NPDIDs are in the 9000 block
# so they never collide with the 001 (real SODIR) or 002 (8000-block) fixtures, even if a future run
# shared a store. ``/fields`` is ordered by ``field_npdid`` (coordinator decision), so the suites can
# assert that order against ``SEEDED_NPDIDS_SORTED``.

CLEAN_POLYGON_NPDID = 9001        # 72 months + POLYGON     → credible forecast, polygon feature
CLEAN_MULTIPOLYGON_NPDID = 9002   # 72 months + MULTIPOLYGON → forecastable, multipolygon feature
SHORT_WITH_OUTLINE_NPDID = 9003   # 40 months + POLYGON      → NO forecast (R4 not-available)
NULL_GEOMETRY_NPDID = 9004        # 72 months + null outline → forecastable, geometry: null feature

# An NPDID guaranteed absent from the store — drives the R6 / unknown-field 404 paths.
UNKNOWN_NPDID = 999999

# Months of observed history per field (drives the >= 60 forecastable split, R4).
FORECASTABLE_MONTHS = 72
SHORT_MONTHS = 40  # < 60 → insufficient history (no forecast)

# Human-readable names pinned per field so the suites assert the served ``field_name`` concretely.
CLEAN_POLYGON_NAME = "ALPHA POLY"
CLEAN_MULTIPOLYGON_NAME = "BRAVO MULTI"
SHORT_WITH_OUTLINE_NAME = "CHARLIE SHORT"
NULL_GEOMETRY_NAME = "DELTA NOGEO"

# Descriptive attributes pinned per field (R2: every Field attribute served must match what we seed).
# One field carries explicit None attributes so the suite proves null descriptive fields survive too.
SEEDED_FIELDS: dict[int, dict[str, object]] = {
    CLEAN_POLYGON_NPDID: {
        "field_name": CLEAN_POLYGON_NAME,
        "current_activity_status": "Producing",
        "hc_type": "OIL",
        "main_area": "North sea",
        "operator": "Operator A",
        "discovery_year": 1979,
        # A simple unit square POLYGON — valid WKT shapely reads as a Polygon (001 Field validator).
        "geometry_wkt": "POLYGON ((2 60, 3 60, 3 61, 2 61, 2 60))",
    },
    CLEAN_MULTIPOLYGON_NPDID: {
        "field_name": CLEAN_MULTIPOLYGON_NAME,
        "current_activity_status": "Producing",
        "hc_type": "GAS",
        "main_area": "Norwegian sea",
        "operator": "Operator B",
        "discovery_year": 1984,
        # Two disjoint squares → a MULTIPOLYGON (001 Field validator accepts Polygon|MultiPolygon).
        "geometry_wkt": (
            "MULTIPOLYGON (((5 65, 6 65, 6 66, 5 66, 5 65)), "
            "((7 67, 8 67, 8 68, 7 68, 7 67)))"
        ),
    },
    SHORT_WITH_OUTLINE_NPDID: {
        "field_name": SHORT_WITH_OUTLINE_NAME,
        "current_activity_status": "Approved for production",
        "hc_type": "OIL/GAS",
        "main_area": "Barents sea",
        "operator": "Operator C",
        "discovery_year": 2011,
        "geometry_wkt": "POLYGON ((20 71, 21 71, 21 72, 20 72, 20 71))",
    },
    NULL_GEOMETRY_NPDID: {
        # A field SODIR published with descriptive attrs but NO outline → geometry_wkt is None.
        # Descriptive attrs deliberately left None too, to prove null Field attributes round-trip.
        "field_name": NULL_GEOMETRY_NAME,
        "current_activity_status": None,
        "hc_type": None,
        "main_area": None,
        "operator": None,
        "discovery_year": None,
        "geometry_wkt": None,
    },
}

# Convenience views the suites assert against.
SEEDED_NPDIDS: frozenset[int] = frozenset(SEEDED_FIELDS)
SEEDED_NPDIDS_SORTED: tuple[int, ...] = tuple(sorted(SEEDED_FIELDS))  # /fields order (by npdid)
SEEDED_FIELD_COUNT: int = len(SEEDED_FIELDS)

# The fields that get a persisted forecast (>= 60 observed months) vs the one that does not (< 60).
FORECASTABLE_NPDIDS: frozenset[int] = frozenset(
    {CLEAN_POLYGON_NPDID, CLEAN_MULTIPOLYGON_NPDID, NULL_GEOMETRY_NPDID}
)
NON_FORECASTABLE_NPDID: int = SHORT_WITH_OUTLINE_NPDID  # exists, < 60 months → forecast_not_available

# Fields whose GeoJSON feature carries a real (non-null) geometry, by expected GeoJSON geometry type.
POLYGON_FEATURE_NPDID: int = CLEAN_POLYGON_NPDID
MULTIPOLYGON_FEATURE_NPDID: int = CLEAN_MULTIPOLYGON_NPDID
NULL_GEOMETRY_FEATURE_NPDID: int = NULL_GEOMETRY_NPDID


# ============================================================ Production series for each field ======
# Reuse the frozen-contract ``forecast_histories.clean_decline`` builder: it yields a smooth oe
# decline that backtests **credible** at >= 60 months (R4 happy path), with every *non-oe* stream
# defaulting to ``None`` (001-R6: "SODIR published no value", distinct from 0.0). We re-key its
# NPDID/name to each seeded field. The short field uses the same builder truncated to 40 months
# (still a clean decline, but the forecaster refuses it → no forecast row, the R4 not-available
# signal).
#
# The R3 null-vs-zero crux (the production suite asserts these on CLEAN_POLYGON):
#   * PROD_NULL_STREAM at PROD_NULL_CELL stays JSON ``null`` end-to-end (never coerced to 0.0);
#   * PROD_ZERO_STREAM at PROD_ZERO_CELL is a *real measured* 0.0 (a genuine zero month).
# Both touch only non-oe streams, so injecting them does NOT change CLEAN_POLYGON's oe series — its
# forecast stays credible. The probe months are interior to the 72-month history.

PROD_FIELD_NPDID: int = CLEAN_POLYGON_NPDID            # the field the R3 suite probes
PROD_NULL_STREAM: str = "gas"                          # left None by clean_decline → must stay null
PROD_ZERO_STREAM: str = "oil"                          # we set a real 0.0 here at PROD_ZERO_CELL
PROD_POSITIVE_STREAM: str = "oil_equivalents"          # clean_decline fills this positive every month

# Calendar of the probe cells (same month arithmetic as the builder). Interior months of the history.
PROD_NULL_CELL: tuple[int, int] = add_months((ANCHOR_YEAR, ANCHOR_MONTH), 10)   # a known null-gas month
PROD_ZERO_CELL: tuple[int, int] = add_months((ANCHOR_YEAR, ANCHOR_MONTH), 15)   # the real 0.0-oil month
PROD_FIRST_CELL: tuple[int, int] = (ANCHOR_YEAR, ANCHOR_MONTH)                   # first month (positive oe)
PROD_LAST_CELL: tuple[int, int] = add_months(
    (ANCHOR_YEAR, ANCHOR_MONTH), FORECASTABLE_MONTHS - 1
)  # last month — the ordering endpoint


def _with_probe_cells(rows: list[MonthlyProduction]) -> list[MonthlyProduction]:
    """Inject the R3 probe cells into a clean-decline history (a real 0.0 on ``oil`` at PROD_ZERO_CELL).

    ``clean_decline`` already leaves every non-oe stream ``None`` (so PROD_NULL_CELL.gas is null
    without help). Here we set a genuine measured ``oil = 0.0`` at PROD_ZERO_CELL — a real zero-
    production observation that must serve as JSON ``0`` (≠ null). Only the ``oil`` field of that one
    month changes; ``oil_equivalents`` (and every other month) is untouched, so the oe series — and
    thus the forecast — is unchanged.
    """
    out: list[MonthlyProduction] = []
    for row in rows:
        if (row.year, row.month) == PROD_ZERO_CELL:
            out.append(row.model_copy(update={PROD_ZERO_STREAM: 0.0}))
        else:
            out.append(row)
    return out


def _production_for(npdid: int) -> list[MonthlyProduction]:
    """The ``MonthlyProduction`` history for one seeded field (clean decline, correct length/name).

    The series carries this field's ``field_name`` so ``/fields/{npdid}/production`` (R3) serves rows
    whose ``field_name`` matches the ``field`` table. The short field gets 40 months (< 60); the
    others get 72 — that split is exactly what makes only the long fields forecastable (R4). The
    PROD field additionally gets the R3 probe cells injected (a real 0.0; the null cell is inherent).
    """
    name = str(SEEDED_FIELDS[npdid]["field_name"])
    months = SHORT_MONTHS if npdid == SHORT_WITH_OUTLINE_NPDID else FORECASTABLE_MONTHS
    rows = clean_decline(npdid, months, field_name=name)
    if npdid == PROD_FIELD_NPDID:
        rows = _with_probe_cells(rows)
    return rows


def _field_for(npdid: int) -> Field:
    """Build the frozen ``Field`` for one seeded NPDID from its pinned attribute dict (R2/R5)."""
    return Field(field_npdid=npdid, **SEEDED_FIELDS[npdid])  # type: ignore[arg-type]


def _all_production_rows() -> list[MonthlyProduction]:
    """Every seeded field's production rows, concatenated (the ``monthly_production`` seed)."""
    rows: list[MonthlyProduction] = []
    for npdid in SEEDED_NPDIDS_SORTED:
        rows.extend(_production_for(npdid))
    return rows


def _all_field_rows() -> list[Field]:
    """Every seeded ``Field`` row (the ``field`` table seed), in npdid order."""
    return [_field_for(npdid) for npdid in SEEDED_NPDIDS_SORTED]


# Per-field production-row counts, pinned so the production suite (R3) can assert ``count`` exactly.
SEEDED_PRODUCTION_COUNTS: dict[int, int] = {
    npdid: (SHORT_MONTHS if npdid == SHORT_WITH_OUTLINE_NPDID else FORECASTABLE_MONTHS)
    for npdid in SEEDED_NPDIDS_SORTED
}


# ============================================================ The seeded store (built once) ========


@pytest.fixture(scope="session")
def seeded_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the hermetic seeded DuckDB **file** once per session; return its path.

    Populated entirely through the **frozen** seams (plan.md §Store population — "seed through the very
    functions that persist", guaranteeing 003 reads exactly what 001/002 write):

    1. ``create_schema(con)`` + ``persist_data(con, production_rows, field_rows)`` (001) — lands the
       four ``Field`` rows and their ``MonthlyProduction`` histories;
    2. ``run_forecasts(con)`` (002) — computes + persists a ``FieldForecast`` (+ 24 points) for the
       three >= 60-month fields; the 40-month field is left **without** a forecast row (R4).

    A real file (not ``:memory:``) so the app can reopen it **read-only** on a fresh connection (the
    R1 structural guarantee). Built once and shared read-only across every API suite — none of the
    GET-only suites mutate it. ``ncs.persist`` / ``ncs.forecast`` are imported lazily inside the
    fixture so this module still *collects* (then the API suites fail on the ``ncs.api`` import, the
    intended red) before the developer wires things up.
    """
    from ncs.forecast import run_forecasts
    from ncs.persist import create_schema, persist_data

    db_path = tmp_path_factory.mktemp("ncs_api_store") / "ncs-003-acceptance.duckdb"

    con = duckdb.connect(str(db_path))
    try:
        create_schema(con)
        persist_data(con, _all_production_rows(), _all_field_rows())
        run_forecasts(con)  # forecasts the >= 60-month fields; persists field_forecast(+points)
    finally:
        con.close()

    return db_path


@pytest.fixture(scope="session")
def seeded_forecasts(seeded_db: Path) -> dict[int, object]:
    """The persisted ``FieldForecast`` per forecastable NPDID, read back once (the R4 oracle).

    The forecast suite asserts the API serves *exactly* the stored forecast; this reads the same rows
    the app will, via the 002 store tables, so the suite compares the HTTP body against the real
    persisted artifact rather than recomputing it. Reading happens lazily (after ``seeded_db`` built),
    so the 002 store layout — not this module — owns the schema.
    """
    from ncs.forecast.contracts import FieldForecast, ForecastPoint

    forecasts: dict[int, object] = {}
    con = duckdb.connect(str(seeded_db), read_only=True)
    try:
        for npdid in sorted(FORECASTABLE_NPDIDS):
            parent = con.execute(
                """
                SELECT target, method, backtest_mape, credible, history_months
                FROM field_forecast WHERE field_npdid = ?
                """,
                [npdid],
            ).fetchone()
            assert parent is not None, (
                f"seed invariant: expected a persisted forecast for {npdid} "
                "(>= 60 months) — the seed builds it via run_forecasts"
            )
            target, method, backtest_mape, credible, history_months = parent
            point_rows = con.execute(
                """
                SELECT year, month, value FROM field_forecast_point
                WHERE field_npdid = ? ORDER BY year, month
                """,
                [npdid],
            ).fetchall()
            forecasts[npdid] = FieldForecast(
                field_npdid=npdid,
                target=target,
                points=[ForecastPoint(year=y, month=m, value=v) for (y, m, v) in point_rows],
                method=method,
                backtest_mape=backtest_mape,
                credible=credible,
                history_months=history_months,
            )
    finally:
        con.close()
    return forecasts


# ============================================================ The TestClient over the seeded store =


@pytest.fixture
def client(seeded_db: Path) -> Iterator["object"]:
    """A FastAPI ``TestClient`` over ``create_app()`` with ``get_connection`` overridden (R1, the seam).

    The single seam every API suite drives:

    * ``create_app()`` builds the app (no module-level global app — plan.md §"app *factory*");
    * ``app.dependency_overrides[get_connection]`` is set to a generator that yields a **read-only**
      DuckDB connection on the seeded file (``duckdb.connect(path, read_only=True)``) and closes it
      after the request — so the suite hits the *real* app over the *seeded* store with **no live
      network and no writable connection** (R1 read-only is structural).
    * wrapped in ``TestClient`` (FastAPI's ``TestClient`` runs on ``httpx`` — already a project dep,
      so no new test dependency, per plan.md §"Libraries to add").

    Imports are inside the fixture so the *fixtures module* collects cleanly; an API suite that
    requests ``client`` is the thing that fails on the missing ``ncs.api`` import — the intended TDD
    red until 003-T7..T9.
    """
    from fastapi.testclient import TestClient

    from ncs.api import create_app
    from ncs.api.deps import get_connection

    def _read_only_connection() -> Iterator[duckdb.DuckDBPyConnection]:
        con = duckdb.connect(str(seeded_db), read_only=True)
        try:
            yield con
        finally:
            con.close()

    app = create_app()
    app.dependency_overrides[get_connection] = _read_only_connection
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
