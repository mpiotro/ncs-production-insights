"""Seed a self-contained DEMO DuckDB store (no network, no SODIR config) for ``start-local``.

Builds a small, **forecast-bearing** store through the FROZEN public seams (``ncs.persist`` +
``ncs.forecast``) from a **synthetic** field set — this is NOT real SODIR data. The real ingestion
path is ``python -m ncs.api.seed`` with ``NCS_INGEST_SETTINGS_JSON`` (see README "Running the app").
This script exists only so the whole app can be started locally with one command and show the full
dashboard (map + history + forecast + credibility) without any network access.

Synthetic fields (NPDIDs in a private 90000 block so they never collide with real SODIR ids):

* ``90001 DEMO ALPHA`` — 72-month smooth decline, POLYGON      -> credible forecast (map polygon)
* ``90002 DEMO BETA``  — 72-month smooth decline, MULTIPOLYGON -> credible forecast (map polygon)
* ``90003 DEMO GAMMA`` — 40-month history, POLYGON             -> NO forecast (insufficient history)
* ``90004 DEMO DELTA`` — 72-month smooth decline, no outline   -> forecast; selectable via the list

The forecasts are produced by the real 002 backtest over this synthetic decline (principle 6 still
holds — the backtest machinery is genuine; only the input series is illustrative).

Usage:  ``uv run python scripts/seed_demo.py [db_path]``   (default: ``ncs-local.duckdb``)
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

from ncs.contracts import Field, MonthlyProduction
from ncs.forecast.run import run_forecasts
from ncs.persist import configure_session, create_schema, persist_data

# Histories start here and march forward one calendar month per row.
_ANCHOR_YEAR, _ANCHOR_MONTH = 2018, 1


def _decline(
    npdid: int,
    name: str,
    months: int,
    *,
    qi: float = 120.0,
    di: float = 0.05,
    b: float = 0.6,
) -> list[MonthlyProduction]:
    """A smooth hyperbolic Arps decline oil-equivalents series (backtests credible at >= 60 months).

    ``q(t) = qi / (1 + b*di*t) ** (1/b)`` — a clean monotone decline the 002 forecaster fits closely,
    so a >= 60-month field lands a credible forecast and a < 60-month one is left unforecastable.
    """
    rows: list[MonthlyProduction] = []
    for t in range(months):
        total = (_ANCHOR_MONTH - 1) + t
        year = _ANCHOR_YEAR + total // 12
        month = total % 12 + 1
        q = qi / (1.0 + b * di * t) ** (1.0 / b)
        rows.append(
            MonthlyProduction(
                field_npdid=npdid,
                field_name=name,
                year=year,
                month=month,
                oil_equivalents=round(q, 4),
            )
        )
    return rows


# Real-ish NCS coordinates (lon 2-21, lat 60-72) so the map polygons land off the Norwegian coast.
_FIELDS: list[Field] = [
    Field(
        field_npdid=90001,
        field_name="DEMO ALPHA",
        current_activity_status="Producing",
        hc_type="OIL",
        main_area="North sea",
        operator="Demo Operator",
        discovery_year=1998,
        geometry_wkt="POLYGON ((2 60, 3 60, 3 61, 2 61, 2 60))",
    ),
    Field(
        field_npdid=90002,
        field_name="DEMO BETA",
        current_activity_status="Producing",
        hc_type="GAS",
        main_area="Norwegian sea",
        operator="Demo Operator",
        discovery_year=2003,
        geometry_wkt=(
            "MULTIPOLYGON (((5 65, 6 65, 6 66, 5 66, 5 65)), "
            "((7 67, 8 67, 8 68, 7 68, 7 67)))"
        ),
    ),
    Field(
        field_npdid=90003,
        field_name="DEMO GAMMA",
        current_activity_status="Producing",
        hc_type="OIL",
        main_area="Barents sea",
        operator="Demo Operator",
        discovery_year=2015,
        geometry_wkt="POLYGON ((20 71, 21 71, 21 72, 20 72, 20 71))",
    ),
    Field(
        field_npdid=90004,
        field_name="DEMO DELTA",
        current_activity_status="Producing",
        hc_type="OIL/GAS",
        main_area="North sea",
        operator="Demo Operator",
        discovery_year=2009,
        geometry_wkt=None,  # no outline -> not on the map; selectable via the field list (004-R1)
    ),
]

_PRODUCTION: list[MonthlyProduction] = (
    _decline(90001, "DEMO ALPHA", 72)
    + _decline(90002, "DEMO BETA", 72, qi=90.0, di=0.04, b=0.8)
    + _decline(90003, "DEMO GAMMA", 40)  # < 60 months -> no forecast (004-R4)
    + _decline(90004, "DEMO DELTA", 72, qi=150.0, di=0.07, b=0.5)
)


def main(argv: list[str]) -> int:
    """Build the demo store at ``argv[1]`` (default ``ncs-local.duckdb``), overwriting any existing file."""
    db_path = Path(argv[1]) if len(argv) > 1 else Path("ncs-local.duckdb")
    if db_path.exists():
        db_path.unlink()

    con = duckdb.connect(str(db_path))
    try:
        configure_session(con)
        create_schema(con)
        persist_data(con, _PRODUCTION, _FIELDS)
        run = run_forecasts(con)
    finally:
        con.close()

    print(
        f"Seeded DEMO store {db_path}: {len(_FIELDS)} fields, {len(_PRODUCTION)} production rows, "
        f"{len(run.forecasts)} forecasts ({len(run.insufficient_history_npdids)} insufficient-history)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
