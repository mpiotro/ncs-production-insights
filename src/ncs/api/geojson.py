"""WKT -> GeoJSON conversion for the field map layer (task 003-T7; R5).

Two pure functions (no DB, no HTTP — unit-testable in isolation): one ``Field`` -> ``FieldFeature``,
and the collection assembly over a list of fields. The conversion is **shapely** (tech-standards):
``shapely.wkt.loads(field.geometry_wkt)`` -> ``shapely.geometry.mapping(geom)`` yields the GeoJSON
geometry dict (``{type, coordinates}``) placed in ``FieldFeature.geometry``.

* The geometry is always Polygon or MultiPolygon — 001's ``Field`` validator already guarantees that
  for any non-null WKT, so 003 does **not** re-validate the geometry class.
* ``properties`` carries identity only: ``{field_npdid, field_name}`` (R5).
* **Null outline (R5).** When ``field.geometry_wkt is None`` the feature is emitted with
  ``geometry: null`` (RFC 7946 permits it) rather than dropped — so the collection has one feature
  per field and 004 can list every field, geometry or not (coordinator decision).
"""

from __future__ import annotations

from typing import Any

from shapely import wkt as shapely_wkt
from shapely.geometry import mapping

from ncs.api.responses import FieldFeature, FieldFeatureCollection, FieldProperties
from ncs.contracts import Field


def _geometry_for(field: Field) -> dict[str, Any] | None:
    """The GeoJSON geometry dict for a field's WKT, or ``None`` when it has no outline (R5).

    A non-null ``geometry_wkt`` is parsed by shapely and mapped to its GeoJSON ``{type, coordinates}``
    form; ``None`` (SODIR published no outline) maps to JSON ``null`` — the null-geometry feature.
    """
    if field.geometry_wkt is None:
        return None
    geom = shapely_wkt.loads(field.geometry_wkt)
    return mapping(geom)


def field_to_feature(field: Field) -> FieldFeature:
    """Convert one ``Field`` to a GeoJSON ``FieldFeature`` (shapely WKT -> geometry, identity props) (R5).

    The feature's ``geometry`` is the shapely mapping of the field's Polygon/MultiPolygon outline (or
    ``null`` when absent); its ``properties`` carry exactly the NPDID + name 004 joins on.
    """
    return FieldFeature(
        geometry=_geometry_for(field),
        properties=FieldProperties(
            field_npdid=field.field_npdid,
            field_name=field.field_name,
        ),
    )


def fields_to_feature_collection(fields: list[Field]) -> FieldFeatureCollection:
    """Map a list of fields to a GeoJSON ``FieldFeatureCollection`` — one feature per field (R5).

    Reuses the same field set as ``/fields`` so the map layer and the list layer stay consistent;
    every field becomes a feature (drawable or null-geometry), in the order given.
    """
    return FieldFeatureCollection(features=[field_to_feature(field) for field in fields])
