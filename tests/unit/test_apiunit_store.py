"""Unit tests for ``ncs.api.store`` (developer-owned, white-box) — 003-T7 / R2, R3, R4, R6.

White-box checks of the read-only reconstruction layer, driven against a **real** tmp DuckDB store
populated through the frozen 001/002 persist seams (so the columns the store SELECTs are byte-
identical to a real ingest/forecast). Covers:

* ``list_fields`` / ``get_field`` reconstruct the frozen ``Field`` in NPDID order, attributes intact;
* ``get_production`` orders ``(year, month)`` in SQL and **preserves null ≠ 0.0** end to end (R3);
* ``get_forecast`` reassembles the frozen ``FieldForecast`` (parent + 24 points) — equal to what 002
  persisted;
* the two distinct not-found paths: ``FieldNotFoundError`` (unknown NPDID, R6) vs
  ``ForecastNotAvailableError`` (field exists, no forecast row, R4) — including the order that
  unknown-field beats no-forecast on the forecast read.

The column tuples are asserted to equal the persist layer's, since the whole round-trip relies on it.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from ncs.api import store
from ncs.api.errors import FieldNotFoundError, ForecastNotAvailableError
from ncs.contracts import Field, MonthlyProduction
from ncs.forecast.contracts import FieldForecast, ForecastMethod, ForecastPoint, ForecastTarget
from ncs.forecast.persist import (
    create_forecast_schema,
    persist_forecast,
)
from ncs.persist import create_schema, persist_data

_POLYGON = "POLYGON ((2 60, 3 60, 3 61, 2 61, 2 60))"

# Two fields, one with descriptive nulls + null geometry, to prove null Field attributes round-trip.
_FIELD_A = Field(
    field_npdid=9001,
    field_name="ALPHA",
    current_activity_status="Producing",
    hc_type="OIL",
    main_area="North sea",
    operator="Operator A",
    discovery_year=1979,
    geometry_wkt=_POLYGON,
)
_FIELD_B = Field(
    field_npdid=9002,
    field_name="BRAVO",
    current_activity_status=None,
    hc_type=None,
    main_area=None,
    operator=None,
    discovery_year=None,
    geometry_wkt=None,
)

# A 3-month history on field A with the null-vs-zero crux: gas absent (None), oil a real 0.0.
_PRODUCTION_A = [
    MonthlyProduction(
        field_npdid=9001, field_name="ALPHA", year=2014, month=1,
        oil=5.0, gas=None, oil_equivalents=5.0,
    ),
    MonthlyProduction(
        field_npdid=9001, field_name="ALPHA", year=2014, month=2,
        oil=0.0, gas=None, oil_equivalents=4.0,
    ),
    MonthlyProduction(
        field_npdid=9001, field_name="ALPHA", year=2014, month=3,
        oil=3.0, gas=1.0, oil_equivalents=3.5,
    ),
]

def _forecast_points() -> list[ForecastPoint]:
    """24 distinct consecutive calendar months from 2020-01 (so the points PK never collides)."""
    points: list[ForecastPoint] = []
    for i in range(24):
        year, month = 2020 + (i // 12), (i % 12) + 1
        points.append(ForecastPoint(year=year, month=month, value=float(i)))
    return points


_FORECAST_A = FieldForecast(
    field_npdid=9001,
    target=ForecastTarget.oil_equivalents,
    points=_forecast_points(),
    method=ForecastMethod.arps_decline,
    backtest_mape=0.08,
    credible=True,
    history_months=72,
)


@pytest.fixture
def seeded(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    """A real tmp DuckDB store with two fields, field A's history, and field A's forecast.

    Written through the frozen seams (``create_schema`` + ``persist_data``; ``persist_forecast``), so
    the store layer reads exactly what 001/002 persist. Field B is left **without** a forecast row —
    the genuine ForecastNotAvailable signal. Yielded read-write here (the store funcs only SELECT).
    """
    con = duckdb.connect(str(tmp_path / "store.duckdb"))
    create_schema(con)
    persist_data(con, _PRODUCTION_A, [_FIELD_A, _FIELD_B])
    create_forecast_schema(con)
    persist_forecast(con, _FORECAST_A)
    try:
        yield con
    finally:
        con.close()


def test_column_tuples_match_the_persist_layer() -> None:
    """The store's column order is taken from the frozen models, equal to what persist writes (R2)."""
    import ncs.persist as persist_mod

    assert store._FIELD_COLUMNS == persist_mod._FIELD_COLUMNS
    assert store._PRODUCTION_COLUMNS == persist_mod._PRODUCTION_COLUMNS


def test_list_fields_returns_all_fields_ordered_by_npdid(seeded) -> None:
    """``list_fields`` reconstructs every ``Field`` in ascending NPDID order (R2)."""
    fields = store.list_fields(seeded)

    assert [f.field_npdid for f in fields] == [9001, 9002]
    assert all(isinstance(f, Field) for f in fields)
    assert fields[0].field_name == "ALPHA"


def test_get_field_reconstructs_the_frozen_field(seeded) -> None:
    """``get_field`` returns the frozen ``Field`` with every descriptive attribute intact (R2)."""
    field = store.get_field(seeded, 9001)

    assert field == _FIELD_A  # full value-object equality (all attrs + geometry_wkt)


def test_get_field_round_trips_null_attributes(seeded) -> None:
    """A field seeded with null descriptive attrs + null geometry reconstructs with those Nones (R2)."""
    field = store.get_field(seeded, 9002)

    assert field == _FIELD_B
    assert field.current_activity_status is None
    assert field.geometry_wkt is None


def test_get_field_unknown_npdid_raises_field_not_found(seeded) -> None:
    """An unknown NPDID raises ``FieldNotFoundError`` carrying that NPDID (R6)."""
    with pytest.raises(FieldNotFoundError) as exc_info:
        store.get_field(seeded, 999999)

    assert exc_info.value.npdid == 999999
    assert "999999" in exc_info.value.detail


def test_get_production_is_ordered_by_year_then_month(seeded) -> None:
    """``get_production`` returns the history ordered (year, month) ascending — done in SQL (R3)."""
    rows = store.get_production(seeded, 9001)

    served = [(r.year, r.month) for r in rows]
    assert served == sorted(served)
    assert len(rows) == len(_PRODUCTION_A)


def test_get_production_preserves_null_distinct_from_zero(seeded) -> None:
    """The null-vs-zero crux: an absent ``gas`` stays ``None``; a real ``oil = 0.0`` stays 0.0 (R3)."""
    rows = store.get_production(seeded, 9001)
    by_month = {(r.year, r.month): r for r in rows}

    # gas was never set on month 1 (None) — must reconstruct as None, never 0.0.
    assert by_month[(2014, 1)].gas is None
    # oil was a real measured 0.0 on month 2 — must reconstruct as 0.0, never None.
    assert by_month[(2014, 2)].oil == 0.0
    assert by_month[(2014, 2)].oil is not None
    # And the two are genuinely distinct in the same history.
    assert by_month[(2014, 1)].gas != by_month[(2014, 2)].oil


def test_get_production_known_field_without_rows_returns_empty(seeded) -> None:
    """A field that exists but has no production rows returns an empty list, not a 404 (R3/R6 boundary)."""
    rows = store.get_production(seeded, 9002)  # field B has no production seeded

    assert rows == []


def test_get_production_unknown_npdid_raises_field_not_found(seeded) -> None:
    """Production for an unknown NPDID raises ``FieldNotFoundError`` (R6 reuse on this endpoint)."""
    with pytest.raises(FieldNotFoundError):
        store.get_production(seeded, 999999)


def test_get_forecast_reconstructs_the_persisted_forecast(seeded) -> None:
    """``get_forecast`` reassembles the frozen ``FieldForecast`` (parent + 24 points) equal to seed (R4)."""
    forecast = store.get_forecast(seeded, 9001)

    assert forecast == _FORECAST_A
    assert len(forecast.points) == 24


def test_get_forecast_points_are_ordered_by_calendar(seeded) -> None:
    """The reconstructed forecast points come back in ascending (year, month) order (R4)."""
    forecast = store.get_forecast(seeded, 9001)

    calendar = [(p.year, p.month) for p in forecast.points]
    assert calendar == sorted(calendar)


def test_get_forecast_field_exists_without_forecast_raises_not_available(seeded) -> None:
    """A field that exists but has no ``field_forecast`` row raises ``ForecastNotAvailableError`` (R4)."""
    with pytest.raises(ForecastNotAvailableError) as exc_info:
        store.get_forecast(seeded, 9002)  # field B exists, no forecast row

    assert exc_info.value.npdid == 9002
    assert "9002" in exc_info.value.detail


def test_get_forecast_unknown_npdid_raises_field_not_found(seeded) -> None:
    """An unknown NPDID's forecast raises ``FieldNotFoundError`` — distinct from not-available (R6/R4)."""
    with pytest.raises(FieldNotFoundError):
        store.get_forecast(seeded, 999999)


def test_two_not_found_errors_carry_distinct_codes(seeded) -> None:
    """The two store exceptions carry distinct ``code`` values — the machine-readable distinctness (R4)."""
    from ncs.api.responses import ErrorCode

    assert FieldNotFoundError.code == ErrorCode.field_not_found
    assert ForecastNotAvailableError.code == ErrorCode.forecast_not_available
    assert FieldNotFoundError.code != ForecastNotAvailableError.code
