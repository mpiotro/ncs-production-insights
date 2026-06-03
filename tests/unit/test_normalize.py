"""Unit tests for ``ncs.normalize`` (developer-owned, white-box) — 001-T9 / R4, R5, R6, R7.

The crux under test is the **absent→null rule (R6)**: an empty/whitespace/missing volume cell must
become ``None``, while a literal ``0`` / ``0.0`` (a real zero-production month) must stay ``0.0``.
These are unit-level checks on the coercion helpers and the row mappers — complementing the
black-box acceptance suite, which proves the same behavior through ``ingest`` end-to-end.
"""

from __future__ import annotations

import pytest

from ncs.contracts import Field, MonthlyProduction
from ncs.normalize import (
    _is_absent,
    _to_float_or_none,
    _to_int,
    _to_int_or_none,
    normalize_fields,
    normalize_production,
)


# --- The absent→None vs 0.0 distinction (R6 crux) -----------------------------------------------


@pytest.mark.parametrize("absent_value", [None, "", "   ", "\t", "\n"])
def test_empty_or_whitespace_cell_is_absent(absent_value: object) -> None:
    """An empty / whitespace / missing cell is treated as absent (→ None)."""
    assert _is_absent(absent_value) is True


@pytest.mark.parametrize("present_value", [0, 0.0, "0", "0.0", "1.5", -1, "x"])
def test_literal_zero_and_other_values_are_present(present_value: object) -> None:
    """A literal zero (and any other concrete value) is *present*, never treated as absent."""
    assert _is_absent(present_value) is False


@pytest.mark.parametrize("absent_value", [None, "", "  "])
def test_absent_volume_coerces_to_none(absent_value: object) -> None:
    """An absent volume cell coerces to ``None`` (the R6 'no value published' case)."""
    assert _to_float_or_none(absent_value) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0, 0.0), (0.0, 0.0), ("0", 0.0), ("0.0", 0.0), ("1.180", 1.180), (" 2.5 ", 2.5)],
)
def test_present_volume_coerces_to_float_keeping_real_zero(raw: object, expected: float) -> None:
    """A present volume parses to ``float``; a real zero stays ``0.0`` (distinct from absent None)."""
    result = _to_float_or_none(raw)
    assert result == pytest.approx(expected)
    assert result is not None  # a real 0.0 is a value, not None


def test_real_zero_and_absent_are_not_conflated() -> None:
    """The load-bearing R6 contrast in one assertion: 0.0 is a value, '' is None — never the same."""
    assert _to_float_or_none(0.0) == 0.0
    assert _to_float_or_none("") is None
    assert _to_float_or_none(0.0) != _to_float_or_none("")


def test_bool_volume_is_rejected_not_treated_as_zero_or_one() -> None:
    """A bool is not a valid numeric volume (guard against int-subclass coercion to 0/1)."""
    with pytest.raises(ValueError):
        _to_float_or_none(True)


def test_non_numeric_present_volume_raises() -> None:
    """A present but non-numeric cell raises (surfaced, never silently dropped)."""
    with pytest.raises(ValueError):
        _to_float_or_none("not-a-number")


# --- Integer coercion (npdid / year / month, and optional discovery_year) ------------------------


@pytest.mark.parametrize(("raw", "expected"), [(1001, 1001), ("1001", 1001), (1001.0, 1001), (" 7 ", 7)])
def test_to_int_coerces_required_identifier(raw: object, expected: int) -> None:
    """Required int columns parse from int / float / string forms."""
    assert _to_int(raw) == expected


def test_to_int_on_absent_required_column_raises() -> None:
    """A truly absent required int column raises (non-nullable in the contract)."""
    with pytest.raises(ValueError):
        _to_int("")


def test_to_int_or_none_passes_absent_through() -> None:
    """An absent optional int (discovery_year) becomes ``None``; a present one parses."""
    assert _to_int_or_none("") is None
    assert _to_int_or_none("1990") == 1990


# --- Production row mapping (SODIR prf* columns → MonthlyProduction) ------------------------------


def _alpha_jan_raw() -> dict[str, object]:
    """ALPHA 2022-01 raw production columns (mirrors production_primary.csv row 4)."""
    return {
        "prfInformationCarrier": "ALPHA",
        "prfYear": "2022",
        "prfMonth": "1",
        "prfPrdOilNetMillSm3": "1.180",
        "prfPrdGasNetBillSm3": "0.940",
        "prfPrdNGLNetMillSm3": "0.105",
        "prfPrdCondensateNetMillSm3": "0.0",
        "prfPrdOeNetMillSm3": "2.205",
        "prfPrdProducedWaterInFieldMillSm3": "0.500",
        "prfNpdidInformationCarrier": "1001",
    }


def test_normalize_production_maps_columns_and_keeps_native_units() -> None:
    """prf* columns map to model fields; gas stays native billion Sm³ (no conversion, R6)."""
    (model,) = normalize_production([_alpha_jan_raw()])

    assert isinstance(model, MonthlyProduction)
    assert model.field_npdid == 1001
    assert model.field_name == "ALPHA"
    assert model.year == 2022
    assert model.month == 1
    assert model.oil == pytest.approx(1.180)
    assert model.gas == pytest.approx(0.940)  # native billion Sm³, not scaled to ~940
    assert model.condensate == 0.0  # a present real zero


def test_normalize_production_empty_stream_cells_become_none() -> None:
    """GAMMA-style row: empty ngl/condensate cells → None, present zeros stay 0.0 (R6)."""
    raw = {
        "prfInformationCarrier": "GAMMA",
        "prfYear": "2022",
        "prfMonth": "6",
        "prfPrdOilNetMillSm3": "0.0",
        "prfPrdGasNetBillSm3": "0.0",
        "prfPrdNGLNetMillSm3": "",  # absent
        "prfPrdCondensateNetMillSm3": "",  # absent
        "prfPrdOeNetMillSm3": "0.0",
        "prfPrdProducedWaterInFieldMillSm3": "0.0",
        "prfNpdidInformationCarrier": "1003",
    }
    (model,) = normalize_production([raw])

    assert model.oil == 0.0
    assert model.oil_equivalents == 0.0
    assert model.ngl is None
    assert model.condensate is None


def test_normalize_production_rejects_out_of_range_month() -> None:
    """The contract's month range (1–12) is enforced through normalization (R4)."""
    raw = _alpha_jan_raw()
    raw["prfMonth"] = "13"
    with pytest.raises(Exception):  # pydantic ValidationError
        normalize_production([raw])


# --- Field row mapping (SODIR fld* / cmpLongName columns → Field), incl. the misspelling ----------


def _gamma_field_raw() -> dict[str, object]:
    """GAMMA raw field columns with SODIR's misspelled status column and a null outline."""
    return {
        "fldNpdidField": 1003,
        "fldName": "GAMMA",
        "fldCurrentActivitySatus": "Shut down",  # SODIR's spelling
        "fldHcType": "OIL",
        "fldMainArea": "Barents sea",
        "cmpLongName": "Gamma Operator AS",
        "fldDiscoveryYear": 1990,
        "geometry_wkt": None,
    }


def test_normalize_fields_maps_misspelled_status_and_operator() -> None:
    """fldCurrentActivitySatus → current_activity_status and cmpLongName → operator (R5)."""
    (model,) = normalize_fields([_gamma_field_raw()])

    assert isinstance(model, Field)
    assert model.field_npdid == 1003
    assert model.current_activity_status == "Shut down"
    assert model.operator == "Gamma Operator AS"
    assert model.discovery_year == 1990
    assert model.geometry_wkt is None  # null outline carried through (R7 null case)


def test_normalize_fields_empty_geometry_cell_becomes_none() -> None:
    """A CSV empty geometry cell normalizes to None (equivalent to the REST null outline, R7)."""
    raw = _gamma_field_raw()
    raw["geometry_wkt"] = ""  # CSV empty cell form
    (model,) = normalize_fields([raw])
    assert model.geometry_wkt is None


def test_normalize_fields_carries_wkt_string() -> None:
    """A present WKT outline is carried as the raw string (the contract validates it, R7)."""
    raw = _gamma_field_raw()
    raw["geometry_wkt"] = "POLYGON ((2.0 60.0, 2.5 60.0, 2.5 60.5, 2.0 60.5, 2.0 60.0))"
    (model,) = normalize_fields([raw])
    assert model.geometry_wkt.startswith("POLYGON")
