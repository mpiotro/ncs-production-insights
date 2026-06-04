"""Unit tests for ``ncs.api.geojson`` (developer-owned, white-box) — 003-T7 / R5.

The WKT->GeoJSON conversion is two pure functions (no DB, no HTTP), so these tests call them directly
on frozen ``Field`` value-objects. Covers: a POLYGON field becomes a ``Polygon`` geometry feature; a
MULTIPOLYGON field a ``MultiPolygon``; a null-outline field a ``geometry: null`` feature (kept, not
dropped); identity-only properties (``{field_npdid, field_name}``); and the collection assembly
emitting one feature per field in the given order, mixing drawable + null geometries.
"""

from __future__ import annotations

from ncs.api.geojson import field_to_feature, fields_to_feature_collection
from ncs.api.responses import FieldFeature, FieldFeatureCollection
from ncs.contracts import Field

_POLYGON = "POLYGON ((2 60, 3 60, 3 61, 2 61, 2 60))"
_MULTIPOLYGON = (
    "MULTIPOLYGON (((5 65, 6 65, 6 66, 5 66, 5 65)), ((7 67, 8 67, 8 68, 7 68, 7 67)))"
)

_POLY_FIELD = Field(field_npdid=9001, field_name="ALPHA", geometry_wkt=_POLYGON)
_MULTI_FIELD = Field(field_npdid=9002, field_name="BRAVO", geometry_wkt=_MULTIPOLYGON)
_NULL_FIELD = Field(field_npdid=9004, field_name="DELTA", geometry_wkt=None)


def test_polygon_field_becomes_polygon_feature() -> None:
    """A POLYGON-WKT field converts to a feature whose geometry is a GeoJSON Polygon (R5)."""
    feature = field_to_feature(_POLY_FIELD)

    assert isinstance(feature, FieldFeature)
    assert feature.type == "Feature"
    assert feature.geometry is not None
    assert feature.geometry["type"] == "Polygon"
    assert feature.geometry["coordinates"]  # non-empty rings


def test_multipolygon_field_becomes_multipolygon_feature() -> None:
    """A MULTIPOLYGON-WKT field converts to a feature whose geometry is a GeoJSON MultiPolygon (R5)."""
    feature = field_to_feature(_MULTI_FIELD)

    assert feature.geometry is not None
    assert feature.geometry["type"] == "MultiPolygon"
    # Two squares -> two polygon members in the coordinates.
    assert len(feature.geometry["coordinates"]) == 2


def test_null_outline_field_becomes_null_geometry_feature() -> None:
    """A field with no WKT converts to a feature with ``geometry is None`` (kept, not dropped) (R5)."""
    feature = field_to_feature(_NULL_FIELD)

    assert feature.geometry is None
    assert feature.type == "Feature"


def test_feature_properties_are_identity_only() -> None:
    """A feature's properties carry exactly the NPDID + name 004 joins on (R5)."""
    feature = field_to_feature(_POLY_FIELD)

    assert feature.properties.field_npdid == 9001
    assert feature.properties.field_name == "ALPHA"
    # Identity-only: the FieldProperties model forbids extras, so dumping yields just the two keys.
    assert set(feature.properties.model_dump().keys()) == {"field_npdid", "field_name"}


def test_null_geometry_feature_still_carries_identity() -> None:
    """Even with null geometry the feature carries its identity properties (R5)."""
    feature = field_to_feature(_NULL_FIELD)

    assert feature.properties.field_npdid == 9004
    assert feature.properties.field_name == "DELTA"


def test_collection_has_one_feature_per_field_in_order() -> None:
    """The collection emits one feature per field, preserving the input order (R5)."""
    collection = fields_to_feature_collection([_POLY_FIELD, _MULTI_FIELD, _NULL_FIELD])

    assert isinstance(collection, FieldFeatureCollection)
    assert collection.type == "FeatureCollection"
    assert [f.properties.field_npdid for f in collection.features] == [9001, 9002, 9004]


def test_collection_mixes_drawable_and_null_geometry() -> None:
    """Drawable Polygon/MultiPolygon features coexist with a null-geometry one (R5)."""
    collection = fields_to_feature_collection([_POLY_FIELD, _MULTI_FIELD, _NULL_FIELD])
    geoms = [f.geometry for f in collection.features]

    assert geoms[0] is not None and geoms[0]["type"] == "Polygon"
    assert geoms[1] is not None and geoms[1]["type"] == "MultiPolygon"
    assert geoms[2] is None


def test_empty_field_list_yields_empty_collection() -> None:
    """An empty field list yields a valid, empty FeatureCollection (R5 boundary)."""
    collection = fields_to_feature_collection([])

    assert collection.type == "FeatureCollection"
    assert collection.features == []
