"""Acceptance suite: fields as a GeoJSON FeatureCollection — EARS 003-R5 (task 003-T5).

Black-box over HTTP through the seeded read-only store (``conftest_api.py``). ``GET /fields.geojson``
returns the fields as a GeoJSON ``FeatureCollection`` (RFC 7946): polygons / multipolygons converted
from the contract WKT via shapely, each feature carrying ``{field_npdid, field_name}``; a field with
no outline appears as a feature with ``geometry: null`` (kept, not dropped — coordinator decision).

* **003-R5** — "WHEN a client requests field geometry, the system SHALL return the fields as a GeoJSON
  FeatureCollection — polygons / multipolygons converted from the contract WKT via shapely, each
  feature carrying the field NPDID and name; a field with no outline carries null geometry." Proven:
  - 200 + a body whose ``type == "FeatureCollection"`` with a ``features`` array;
  - the **POLYGON** field appears as a feature whose ``geometry.type == "Polygon"`` with coordinates;
  - the **MULTIPOLYGON** field appears as a feature whose ``geometry.type == "MultiPolygon"`` with
    coordinates;
  - each real-geometry feature's ``properties`` is exactly ``{field_npdid, field_name}``;
  - the **null-outline** field appears as a feature with **``geometry: null``** (kept in the
    collection — the coordinator chose null-geometry over omission), still carrying its identity.

The collection reuses the same field set as ``/fields`` (one feature per field), so the map layer and
the list layer stay consistent. Red until ``ncs.api`` exists and 003-T7/T8 implement the geojson
conversion + route. Pins the RFC-7946 envelope and the per-field geometry/identity, never the shapely
call mechanics.
"""

from __future__ import annotations

from conftest_api import (
    MULTIPOLYGON_FEATURE_NPDID,
    NULL_GEOMETRY_FEATURE_NPDID,
    POLYGON_FEATURE_NPDID,
    SEEDED_FIELD_COUNT,
    SEEDED_FIELDS,
    SEEDED_NPDIDS,
)


def _feature_collection(client) -> dict:
    """GET ``/fields.geojson`` and return the parsed body (asserting 200)."""
    response = client.get("/fields.geojson")
    assert response.status_code == 200, response.text
    return response.json()


def _feature_for(collection: dict, npdid: int) -> dict:
    """The single feature for ``npdid`` — keyed off ``properties.field_npdid`` (exactly one)."""
    matches = [
        f for f in collection["features"] if f["properties"]["field_npdid"] == npdid
    ]
    assert len(matches) == 1, f"expected exactly one feature for npdid {npdid}, got {len(matches)}"
    return matches[0]


# ============================================================ R5 — the FeatureCollection envelope ==


def test_r5_geojson_returns_200_and_feature_collection(client) -> None:
    """003-R5: ``GET /fields.geojson`` is 200 and validates as a ``FieldFeatureCollection``.

    The RFC-7946 envelope (``type == "FeatureCollection"`` + ``features``) is modelled
    (``FieldFeatureCollection``, contracts.md) rather than a raw dict, so the body is contract-checked
    here — a malformed collection fails at the boundary, not in Leaflet.
    """
    from ncs.api.responses import FieldFeatureCollection

    response = client.get("/fields.geojson")

    assert response.status_code == 200
    collection = FieldFeatureCollection.model_validate(response.json())
    assert collection.type == "FeatureCollection"


def test_r5_collection_has_one_feature_per_field(client) -> None:
    """003-R5: the collection carries one feature per persisted field (incl. the null-outline one).

    Coordinator decision: a null-outline field is *kept* as a null-geometry feature, so the feature
    set is complete — one per field. The served feature NPDIDs equal the seeded field set, count and
    all (so 004 can enumerate every field on the map list).
    """
    collection = _feature_collection(client)

    assert len(collection["features"]) == SEEDED_FIELD_COUNT
    served_npdids = {f["properties"]["field_npdid"] for f in collection["features"]}
    assert served_npdids == set(SEEDED_NPDIDS)


def test_r5_every_feature_is_typed_feature_with_properties(client) -> None:
    """003-R5: every entry is a GeoJSON ``Feature`` carrying a ``geometry`` key and ``properties``.

    RFC 7946: each feature has ``type == "Feature"``, a ``geometry`` member (possibly ``null``), and
    ``properties``. Asserted across all features so the envelope is uniformly well-formed.
    """
    collection = _feature_collection(client)

    for feature in collection["features"]:
        assert feature["type"] == "Feature"
        assert "geometry" in feature           # present even when null (RFC 7946)
        assert "properties" in feature


# ============================================================ R5 — polygon & multipolygon features =


def test_r5_polygon_field_is_a_polygon_feature_with_coordinates(client) -> None:
    """003-R5: the POLYGON field is a feature whose ``geometry.type == "Polygon"`` with coordinates.

    shapely converts the field's POLYGON WKT to a GeoJSON ``Polygon`` geometry; the served feature
    carries ``geometry.type == "Polygon"`` and a non-empty ``coordinates`` array (the actual outline
    004 draws).
    """
    feature = _feature_for(_feature_collection(client), POLYGON_FEATURE_NPDID)

    geometry = feature["geometry"]
    assert geometry is not None, "the POLYGON field must have a non-null geometry (R5)"
    assert geometry["type"] == "Polygon"
    assert geometry["coordinates"], "the Polygon geometry must carry coordinates (R5)"


def test_r5_multipolygon_field_is_a_multipolygon_feature_with_coordinates(client) -> None:
    """003-R5: the MULTIPOLYGON field is a feature whose ``geometry.type == "MultiPolygon"`` + coords.

    shapely converts the field's MULTIPOLYGON WKT to a GeoJSON ``MultiPolygon``; the served feature
    carries ``geometry.type == "MultiPolygon"`` and a non-empty ``coordinates`` array (two rings, from
    the seeded two-square multipolygon).
    """
    feature = _feature_for(_feature_collection(client), MULTIPOLYGON_FEATURE_NPDID)

    geometry = feature["geometry"]
    assert geometry is not None, "the MULTIPOLYGON field must have a non-null geometry (R5)"
    assert geometry["type"] == "MultiPolygon"
    assert geometry["coordinates"], "the MultiPolygon geometry must carry coordinates (R5)"


def test_r5_real_geometry_feature_properties_are_npdid_and_name_only(client) -> None:
    """003-R5: a real-geometry feature's ``properties`` is exactly ``{field_npdid, field_name}``.

    R5 says each feature carries the field NPDID and name. ``FieldProperties`` is identity-only
    (contracts.md), so the served ``properties`` has exactly those two keys, with the seeded values —
    no extra columns leaked into the map layer.
    """
    feature = _feature_for(_feature_collection(client), POLYGON_FEATURE_NPDID)

    props = feature["properties"]
    assert set(props.keys()) == {"field_npdid", "field_name"}
    assert props["field_npdid"] == POLYGON_FEATURE_NPDID
    assert props["field_name"] == SEEDED_FIELDS[POLYGON_FEATURE_NPDID]["field_name"]


# ============================================================ R5 — null-outline field kept as null =


def test_r5_null_outline_field_is_a_feature_with_null_geometry(client) -> None:
    """003-R5: the null-outline field appears as a feature with ``geometry: null`` (kept, not dropped).

    Coordinator decision (plan §Resolved 5): a field with no WKT is emitted with ``geometry: null``
    rather than omitted, so the collection lists every field. The feature exists and its ``geometry``
    is exactly JSON ``null`` (RFC 7946 permits null geometry).
    """
    feature = _feature_for(_feature_collection(client), NULL_GEOMETRY_FEATURE_NPDID)

    assert "geometry" in feature, "the null-outline field must still appear as a feature (R5: kept)"
    assert feature["geometry"] is None, "a field with no outline must serve geometry: null (R5)"


def test_r5_null_geometry_feature_still_carries_identity(client) -> None:
    """003-R5: even with null geometry the feature carries ``{field_npdid, field_name}`` identity.

    The point of keeping the null-geometry feature is that 004 can still list the field; so its
    ``properties`` carry the same identity-only pair (NPDID + name) as a drawable feature.
    """
    feature = _feature_for(_feature_collection(client), NULL_GEOMETRY_FEATURE_NPDID)

    props = feature["properties"]
    assert set(props.keys()) == {"field_npdid", "field_name"}
    assert props["field_npdid"] == NULL_GEOMETRY_FEATURE_NPDID
    assert props["field_name"] == SEEDED_FIELDS[NULL_GEOMETRY_FEATURE_NPDID]["field_name"]


def test_r5_real_and_null_geometry_coexist_in_one_collection(client) -> None:
    """003-R5: drawable and null-geometry features coexist — the collection mixes both kinds.

    A single check that the collection simultaneously holds a non-null Polygon/MultiPolygon geometry
    *and* a null geometry — proving the null-outline handling doesn't drop the drawable ones, nor vice
    versa (the coordinator's "one feature per field, geometry or not").
    """
    collection = _feature_collection(client)

    polygon_geom = _feature_for(collection, POLYGON_FEATURE_NPDID)["geometry"]
    multipolygon_geom = _feature_for(collection, MULTIPOLYGON_FEATURE_NPDID)["geometry"]
    null_geom = _feature_for(collection, NULL_GEOMETRY_FEATURE_NPDID)["geometry"]

    assert polygon_geom is not None and polygon_geom["type"] == "Polygon"
    assert multipolygon_geom is not None and multipolygon_geom["type"] == "MultiPolygon"
    assert null_geom is None
