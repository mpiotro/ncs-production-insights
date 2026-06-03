"""Unit tests for ``ncs.contracts`` (developer-owned, white-box) — 001-T7 / R4, R6, R7.

Focuses on the bodies the developer added: the ``Field.geometry_wkt`` polygon/multipolygon
validator (R7), and the model-level guarantees the normalizer relies on (absent stream defaults to
None, non-negative volumes, month range, frozen/extra-forbid). The acceptance suite asserts the same
guarantees black-box; these pin them directly on the models so a regression localizes here.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ncs.contracts import (
    Dataset,
    Field,
    IngestionReport,
    MonthlyProduction,
    RecordCounts,
    SourceRef,
    Transport,
)

_POLYGON = "POLYGON ((2.0 60.0, 2.5 60.0, 2.5 60.5, 2.0 60.5, 2.0 60.0))"
_MULTIPOLYGON = (
    "MULTIPOLYGON (((6.0 65.0, 6.4 65.0, 6.4 65.4, 6.0 65.4, 6.0 65.0)), "
    "((7.0 66.0, 7.2 66.0, 7.2 66.2, 7.0 66.2, 7.0 66.0)))"
)


def _field(**overrides: object) -> dict[str, object]:
    base = {"field_npdid": 1001, "field_name": "ALPHA", "geometry_wkt": _POLYGON}
    base.update(overrides)
    return base


# --- R7: the geometry_wkt validator body --------------------------------------------------------


def test_polygon_wkt_is_accepted() -> None:
    """A POLYGON outline parses and is accepted (R7)."""
    assert Field(**_field(geometry_wkt=_POLYGON)).geometry_wkt == _POLYGON


def test_multipolygon_wkt_is_accepted() -> None:
    """A MULTIPOLYGON outline parses and is accepted (R7)."""
    assert Field(**_field(geometry_wkt=_MULTIPOLYGON)).geometry_wkt == _MULTIPOLYGON


def test_null_outline_is_accepted() -> None:
    """A null outline (SODIR publishes none) is accepted unchanged (R7 null case)."""
    assert Field(**_field(geometry_wkt=None)).geometry_wkt is None


@pytest.mark.parametrize(
    "wrong_geom",
    [
        "POINT (2.0 60.0)",
        "LINESTRING (2.0 60.0, 2.5 60.5)",
    ],
)
def test_valid_wkt_of_wrong_geometry_class_is_rejected(wrong_geom: str) -> None:
    """Valid WKT that is not a polygon/multipolygon (POINT, LINESTRING) is rejected (R7)."""
    with pytest.raises(ValidationError):
        Field(**_field(geometry_wkt=wrong_geom))


@pytest.mark.parametrize("bad_wkt", ["NOT WKT AT ALL", "POLYGON ((bad))", "()"])
def test_syntactically_invalid_wkt_is_rejected(bad_wkt: str) -> None:
    """A non-null string shapely cannot parse as WKT is rejected (R7)."""
    with pytest.raises(ValidationError):
        Field(**_field(geometry_wkt=bad_wkt))


# --- R6 / R4: model-level guarantees the normalizer leans on ------------------------------------


def test_omitted_streams_default_to_none() -> None:
    """Omitted stream volumes default to None (absent), not 0.0 — the model-level R6 expression."""
    model = MonthlyProduction(field_npdid=1003, field_name="GAMMA", year=2022, month=6, oil=0.0)
    assert model.oil == 0.0
    assert model.ngl is None
    assert model.condensate is None
    assert model.produced_water is None


def test_negative_volume_is_rejected() -> None:
    """A negative stream volume is rejected by the contract (ge=0, R6)."""
    with pytest.raises(ValidationError):
        MonthlyProduction(field_npdid=1, field_name="X", year=2022, month=1, oil=-0.001)


@pytest.mark.parametrize("bad_month", [0, 13, -1, 99])
def test_month_out_of_range_is_rejected(bad_month: int) -> None:
    """A month outside 1–12 is rejected (R4 key integrity)."""
    with pytest.raises(ValidationError):
        MonthlyProduction(field_npdid=1, field_name="X", year=2022, month=bad_month)


def test_models_are_frozen_and_forbid_extra() -> None:
    """The data models reject unknown columns and are immutable after construction (R4/R5)."""
    with pytest.raises(ValidationError):
        Field(**_field(stray_column="x"))
    fld = Field(**_field())
    with pytest.raises(ValidationError):
        fld.field_name = "RENAMED"  # type: ignore[misc]


# --- SourceRef / report parts hold together (used by the report builder) -------------------------


def test_sourceref_accepts_file_url() -> None:
    """SourceRef.url accepts a file:// URL (the local-source case the fetch layer builds)."""
    ref = SourceRef(
        dataset=Dataset.production,
        url="file:///tmp/production_fallback.csv",
        transport=Transport.csv,
    )
    assert ref.transport == Transport.csv
    assert "production_fallback.csv" in str(ref.url)


def test_ingestion_report_round_trips_its_parts() -> None:
    """An IngestionReport carries its typed parts (the shape the builder emits, R9)."""
    report = IngestionReport(
        sources=[
            SourceRef(dataset=Dataset.production, url="file:///tmp/p.csv", transport=Transport.csv),
        ],
        retrieved_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        counts=RecordCounts(production_records=10, distinct_production_fields=4, fields=4),
        unmatched_production_npdids=[1009],
        unmatched_field_npdids=[1004],
    )
    assert report.counts.production_records == 10
    assert report.unmatched_production_npdids == [1009]
