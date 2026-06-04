"""Fields-as-GeoJSON route (task 003-T8; R5).

``GET /fields.geojson`` returns the fields as a GeoJSON ``FieldFeatureCollection`` (RFC 7946): each
feature's geometry is shapely(WKT)->GeoJSON (Polygon/MultiPolygon), with identity-only properties
(``{field_npdid, field_name}``); a field with no outline is kept as a feature with ``geometry: null``
(coordinator decision). It reuses ``store.list_fields`` (the same field set as ``/fields``) so the map
and list layers stay consistent. GET only.
"""

from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends

from ncs.api import store
from ncs.api.deps import get_connection
from ncs.api.geojson import fields_to_feature_collection
from ncs.api.responses import FieldFeatureCollection

router = APIRouter(tags=["geojson"])


@router.get("/fields.geojson", response_model=FieldFeatureCollection)
def fields_geojson(
    con: duckdb.DuckDBPyConnection = Depends(get_connection),
) -> FieldFeatureCollection:
    """Return the fields as a GeoJSON FeatureCollection; null-outline fields kept as null geometry (003-R5)."""
    fields = store.list_fields(con)
    return fields_to_feature_collection(fields)
