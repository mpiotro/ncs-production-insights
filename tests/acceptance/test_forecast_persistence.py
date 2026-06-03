"""Acceptance suite: forecast persistence & idempotent re-run — EARS 002-R8 (task 002-T5).

Black-box through the integration seam ``run_forecasts(con)`` (plan.md §Component shape / §Input
source / §Persistence). The store is seeded **hermetically** with controlled synthetic
``MonthlyProduction`` rows via the ``seed_monthly_production`` fixture (frozen 001 persistence seam)
— no SODIR CSV, no network — and then forecast end-to-end.

* **002-R8** — "WHEN a forecasting run completes, the system SHALL persist each ``FieldForecast`` to
  the single DuckDB store, queryable by field NPDID." Acceptance, proven several ways:
  - ``run_forecasts(con)`` returns a typed ``ForecastRun`` listing one ``FieldForecast`` per
    >= 60-month field and the **< 60-month field's NPDID** in ``insufficient_history_npdids`` (the
    R5 outcome surfaced at the run level);
  - the ``field_forecast`` (+ ``field_forecast_point``) tables are populated and **queryable by
    ``field_npdid``** with plain SQL after the run;
  - a persisted row **reconstructs into the frozen ``FieldForecast``** (the round-trip 003 serves);
  - a **second** ``run_forecasts(con)`` over the same store leaves row counts unchanged (idempotent
    upsert, mirroring 001-R11).

Reuses the 001 ``con`` fixture (a tmp_path DuckDB **file**, so the store survives within the test).
Red at collection time until 002-T11/T12 implement persistence and ``run_forecasts``. Assertions pin
**outcomes** (rows queryable by NPDID, the run lists the right fields, counts stable on re-run),
never the DDL/upsert mechanism — except where the plan fixes the persisted table/column names that
003 will query, which the round-trip necessarily reads.
"""

from __future__ import annotations

import duckdb
import pytest

from forecast_histories import (
    all_rows,
    clean_decline,
    short_history,
    volatile,
)

from ncs.forecast import run_forecasts
from ncs.forecast.contracts import (
    FieldForecast,
    ForecastPoint,
    ForecastRun,
)

# Synthetic fields seeded into the store. Two are forecastable (>= 60 months); one is short (< 60).
CLEAN_NPDID = 8001       # clean decline, 72 months — forecastable, credible
VOLATILE_NPDID = 8002    # volatile, 72 months    — forecastable, low-confidence (still persisted)
SHORT_NPDID = 8003       # short history, 40 months — insufficient-history (no FieldForecast)

FORECASTABLE_NPDIDS = {CLEAN_NPDID, VOLATILE_NPDID}


def _seed_three_fields(con: duckdb.DuckDBPyConnection, seed) -> None:
    """Seed the store with the two forecastable fields and the one short field."""
    seed(
        con,
        all_rows(
            clean_decline(CLEAN_NPDID, 72),
            volatile(VOLATILE_NPDID, 72),
            short_history(SHORT_NPDID, 40),
        ),
    )


# --- Small DuckDB read helpers (style shared with the 001 persistence suite) ----------------------


def _count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    """Row count of ``table``."""
    (n,) = con.execute(f"SELECT count(*) FROM {table}").fetchone()
    return n


def _forecast_npdids(con: duckdb.DuckDBPyConnection) -> set[int]:
    """The set of ``field_npdid`` keys persisted in ``field_forecast``."""
    return {row[0] for row in con.execute("SELECT field_npdid FROM field_forecast").fetchall()}


def _load_field_forecast(con: duckdb.DuckDBPyConnection, npdid: int) -> FieldForecast:
    """Reconstruct a persisted ``FieldForecast`` from the store, queried by ``field_npdid`` (R8).

    Reads the scalar parent row from ``field_forecast`` and its 24 child points from
    ``field_forecast_point`` (ordered by calendar), and rebuilds the frozen model — the exact
    round-trip 003 performs to serve a precomputed forecast. The parent columns equal the scalar
    ``FieldForecast`` fields (minus ``points``), per plan.md §Persistence.
    """
    parent = con.execute(
        """
        SELECT target, method, backtest_mape, credible, history_months
        FROM field_forecast
        WHERE field_npdid = ?
        """,
        [npdid],
    ).fetchone()
    assert parent is not None, f"no field_forecast row for npdid {npdid} (R8: queryable by NPDID)"
    target, method, backtest_mape, credible, history_months = parent

    point_rows = con.execute(
        """
        SELECT year, month, value
        FROM field_forecast_point
        WHERE field_npdid = ?
        ORDER BY year, month
        """,
        [npdid],
    ).fetchall()
    points = [ForecastPoint(year=y, month=m, value=v) for (y, m, v) in point_rows]

    return FieldForecast(
        field_npdid=npdid,
        target=target,
        points=points,
        method=method,
        backtest_mape=backtest_mape,
        credible=credible,
        history_months=history_months,
    )


# ============================================================ R8 — the run returns a typed report ==


def test_r8_run_returns_a_forecast_run(con: duckdb.DuckDBPyConnection, seed_monthly_production) -> None:
    """002-R8/R5: ``run_forecasts`` returns a typed ``ForecastRun`` over the seeded store.

    The integration seam reads ``monthly_production``, forecasts each field, and returns the typed
    run summary (the 002 analogue of 001's ``IngestionReport``).
    """
    _seed_three_fields(con, seed_monthly_production)

    run = run_forecasts(con)

    assert isinstance(run, ForecastRun)


def test_r8_run_lists_a_forecast_per_forecastable_field(
    con: duckdb.DuckDBPyConnection, seed_monthly_production
) -> None:
    """002-R8/R1: the run's ``forecasts`` cover exactly the >= 60-month fields, each a ``FieldForecast``.

    The two 72-month fields are forecast; the 40-month field is not (it appears only in
    insufficient-history, asserted next). Every entry is a valid frozen ``FieldForecast``.
    """
    _seed_three_fields(con, seed_monthly_production)

    run = run_forecasts(con)

    assert all(isinstance(f, FieldForecast) for f in run.forecasts)
    assert {f.field_npdid for f in run.forecasts} == FORECASTABLE_NPDIDS


def test_r8_run_records_short_field_as_insufficient_history(
    con: duckdb.DuckDBPyConnection, seed_monthly_production
) -> None:
    """002-R5/R8: the < 60-month field is recorded in ``insufficient_history_npdids``, not forecast.

    The run-level half of R5 (the single-field raise is in ``test_eligibility.py``):
    ``run_forecasts`` catches the insufficient-history field and surfaces its NPDID — never silently
    dropping it, and never emitting a ``FieldForecast`` for it.
    """
    _seed_three_fields(con, seed_monthly_production)

    run = run_forecasts(con)

    assert SHORT_NPDID in run.insufficient_history_npdids
    assert SHORT_NPDID not in {f.field_npdid for f in run.forecasts}


# ============================================================ R8 — persisted & queryable by NPDID ==


def test_r8_forecasts_are_persisted_and_queryable_by_npdid(
    con: duckdb.DuckDBPyConnection, seed_monthly_production
) -> None:
    """002-R8: after the run, ``field_forecast`` holds a row per forecastable field, queryable by NPDID.

    The core R8 outcome — each ``FieldForecast`` is persisted to the single DuckDB store and
    retrievable by ``field_npdid`` with plain SQL. The short field has no parent row.
    """
    _seed_three_fields(con, seed_monthly_production)

    run_forecasts(con)

    assert _forecast_npdids(con) == FORECASTABLE_NPDIDS
    for npdid in FORECASTABLE_NPDIDS:
        (n,) = con.execute(
            "SELECT count(*) FROM field_forecast WHERE field_npdid = ?", [npdid]
        ).fetchone()
        assert n == 1, f"expected exactly one field_forecast row for {npdid}, got {n}"

    (short_rows,) = con.execute(
        "SELECT count(*) FROM field_forecast WHERE field_npdid = ?", [SHORT_NPDID]
    ).fetchone()
    assert short_rows == 0, "an insufficient-history field must not be persisted as a forecast (R5/R8)"


def test_r8_each_forecast_persists_its_24_points(
    con: duckdb.DuckDBPyConnection, seed_monthly_production
) -> None:
    """002-R8/R1: each persisted forecast stores exactly its 24 forward points, keyed by NPDID.

    The child ``field_forecast_point`` table carries 24 rows per forecastable field (the forward
    horizon), queryable by ``field_npdid`` — so 003 can read a field's series with a simple ordered
    SELECT. Total points = 24 x (number of forecastable fields).
    """
    _seed_three_fields(con, seed_monthly_production)

    run_forecasts(con)

    for npdid in FORECASTABLE_NPDIDS:
        (n,) = con.execute(
            "SELECT count(*) FROM field_forecast_point WHERE field_npdid = ?", [npdid]
        ).fetchone()
        assert n == 24, f"expected 24 forecast points for {npdid}, got {n}"

    assert _count(con, "field_forecast_point") == 24 * len(FORECASTABLE_NPDIDS)


def test_r8_persisted_row_reconstructs_into_fieldforecast(
    con: duckdb.DuckDBPyConnection, seed_monthly_production
) -> None:
    """002-R8/R7: a persisted forecast reconstructs into the frozen ``FieldForecast`` (the 003 round-trip).

    Reading the parent scalars + the 24 child points back from the store and rebuilding the frozen
    model proves the persisted columns equal the contract fields (no lossy storage) and that the
    stored values still satisfy every invariant (24 points, target fixed, credible-implies-gate,
    history_months >= 60). This is exactly what 003 does to serve a precomputed forecast.
    """
    _seed_three_fields(con, seed_monthly_production)

    run = run_forecasts(con)
    in_memory = {f.field_npdid: f for f in run.forecasts}

    for npdid in FORECASTABLE_NPDIDS:
        reconstructed = _load_field_forecast(con, npdid)  # validates against the frozen model

        assert reconstructed.field_npdid == npdid
        assert len(reconstructed.points) == 24
        assert reconstructed.history_months >= 60

        # The persisted artifact matches what the run returned in memory (no drift store<->return).
        assert reconstructed == in_memory[npdid], (
            f"the persisted forecast for {npdid} differs from the one run_forecasts returned (R8)"
        )


# ============================================================ R8 — idempotent re-run (upsert) ======


def test_r8_second_run_leaves_counts_unchanged(
    con: duckdb.DuckDBPyConnection, seed_monthly_production
) -> None:
    """002-R8: a second ``run_forecasts`` over the same store is idempotent — counts don't grow.

    Mirrors 001-R11: re-forecasting upserts in place (parent keyed by ``field_npdid``, points keyed
    by ``(field_npdid, year, month)``), so neither table gains rows. Counts are asserted after run 1
    too, so a regression that breaks the *first* persist is distinguishable from one that breaks
    idempotency on the *second*.
    """
    _seed_three_fields(con, seed_monthly_production)

    run_forecasts(con)
    forecasts_after_1 = _count(con, "field_forecast")
    points_after_1 = _count(con, "field_forecast_point")

    assert forecasts_after_1 == len(FORECASTABLE_NPDIDS)
    assert points_after_1 == 24 * len(FORECASTABLE_NPDIDS)

    run_forecasts(con)  # identical store, same connection

    assert _count(con, "field_forecast") == forecasts_after_1, (
        "a second forecasting run must not add field_forecast rows (R8 idempotent upsert)"
    )
    assert _count(con, "field_forecast_point") == points_after_1, (
        "a second forecasting run must not add field_forecast_point rows (R8 idempotent upsert)"
    )


def test_r8_second_run_keeps_keys_unique(
    con: duckdb.DuckDBPyConnection, seed_monthly_production
) -> None:
    """002-R8: after a re-run the forecast keys stay unique — upsert by key, not duplicate insertion.

    ``field_forecast.field_npdid`` stays unique and ``field_forecast_point``'s
    ``(field_npdid, year, month)`` stays unique after the second run — either count diverging would
    mean a duplicate forecast or point slipped in (append, not upsert).
    """
    _seed_three_fields(con, seed_monthly_production)

    run_forecasts(con)
    run_forecasts(con)

    (parent_total, parent_distinct) = con.execute(
        "SELECT count(*), count(DISTINCT field_npdid) FROM field_forecast"
    ).fetchone()
    assert parent_total == parent_distinct == len(FORECASTABLE_NPDIDS), (
        "field_forecast has duplicate field_npdid rows after a re-run (R8 upsert-by-key)"
    )

    (point_total, point_distinct) = con.execute(
        "SELECT count(*), count(DISTINCT (field_npdid, year, month)) FROM field_forecast_point"
    ).fetchone()
    assert point_total == point_distinct == 24 * len(FORECASTABLE_NPDIDS), (
        "field_forecast_point has duplicate (field_npdid, year, month) rows after a re-run (R8)"
    )


def test_r8_second_run_preserves_the_reconstructed_forecast(
    con: duckdb.DuckDBPyConnection, seed_monthly_production
) -> None:
    """002-R8: re-running over identical data leaves each persisted forecast identical (in place).

    Idempotency is upsert, not merely "no extra rows": the ``FieldForecast`` reconstructed from the
    store after the second run equals the one after the first — same points, same selection,
    same credibility. Catches a re-run that mangles a row on update as well as one that duplicates it.
    """
    _seed_three_fields(con, seed_monthly_production)

    run_forecasts(con)
    after_run_1 = {npdid: _load_field_forecast(con, npdid) for npdid in FORECASTABLE_NPDIDS}

    run_forecasts(con)
    for npdid in FORECASTABLE_NPDIDS:
        assert _load_field_forecast(con, npdid) == after_run_1[npdid], (
            f"the persisted forecast for {npdid} changed after a second identical run (R8)"
        )


def test_r8_volatile_low_confidence_forecast_is_still_persisted(
    con: duckdb.DuckDBPyConnection, seed_monthly_production
) -> None:
    """002-R8/R4: a low-confidence forecast is persisted too — flagged, not hidden from the store.

    The volatile field backtests >= 15% (low-confidence) yet is still written to ``field_forecast``
    with ``credible = False`` and queryable by NPDID — so 003 can serve it (and 004 badge it), never
    silently dropped at the persistence boundary.
    """
    _seed_three_fields(con, seed_monthly_production)

    run_forecasts(con)

    persisted = _load_field_forecast(con, VOLATILE_NPDID)
    assert persisted.credible is False
    assert persisted.backtest_mape >= 0.15
