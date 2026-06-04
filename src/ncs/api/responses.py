"""Response contract for the 003 API (task 003-T7) — the transport models FastAPI serialises.

These mirror ``specs/003-api/contracts.md`` exactly (field declarations copied verbatim). 003
defines **no new persisted entity** (principle 3): every model here is either a frozen 001/002 model
re-used verbatim as a nested type, or a thin **transport wrapper** — the list envelopes, the GeoJSON
Feature / FeatureCollection, and the typed error body. Setting these as ``response_model=`` on each
route is what makes FastAPI's **auto-generated OpenAPI** (R7) self-describing for 004.

Conventions (mirroring ``ncs.contracts`` / the 001/002 contracts):
- Pydantic v2. Unlike the frozen value-objects these are *response* models, so they are **not**
  ``frozen`` — but they keep ``ConfigDict(extra="forbid")`` so a malformed response shape is caught.
- The served 001/002 models (``Field``, ``MonthlyProduction``, ``FieldForecast``) are imported and
  re-used, never redefined (read-only, principle 3) — so OpenAPI shows the real frozen schema.
- GeoJSON follows RFC 7946: a ``Feature`` has ``type`` / ``geometry`` / ``properties``; a
  ``FeatureCollection`` has ``type`` + ``features``. ``geometry`` is the shapely-``mapping(...)`` dict
  typed loosely as a JSON object so any Polygon/MultiPolygon serialises without a bespoke schema.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from ncs.contracts import Field, MonthlyProduction
from ncs.forecast.contracts import FieldForecast  # noqa: F401 — re-exported for the forecast route

__all__ = [
    "FieldListResponse",
    "ProductionHistoryResponse",
    "FieldForecast",
    "FieldProperties",
    "FieldFeature",
    "FieldFeatureCollection",
    "ErrorCode",
    "ErrorResponse",
]


# ============================================================ List envelopes (R2, R3) =============


class FieldListResponse(BaseModel):
    """The field list (003-R2) — every persisted Field with its descriptive attributes."""

    model_config = ConfigDict(extra="forbid")

    count: int                       # len(fields); convenience for 004
    fields: list[Field]              # frozen 001 Field, served verbatim (incl. geometry_wkt)


class ProductionHistoryResponse(BaseModel):
    """A field's full monthly-production history (003-R3), ordered (year, month), nulls preserved."""

    model_config = ConfigDict(extra="forbid")

    field_npdid: int                 # the field this history is for (echoes the path param)
    count: int                       # number of months returned
    production: list[MonthlyProduction]   # frozen 001 MonthlyProduction, ordered (year, month)


# ============================================================ GeoJSON FeatureCollection (R5) ======


class FieldProperties(BaseModel):
    """A GeoJSON feature's properties for a field (003-R5) — identity only, for the map layer."""

    model_config = ConfigDict(extra="forbid")

    field_npdid: int                 # NPDID — the join key 004 uses to link map <-> charts
    field_name: str                  # human label for the feature


class FieldFeature(BaseModel):
    """One GeoJSON Feature: a field's outline (or null) + its identity (003-R5)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["Feature"] = "Feature"
    geometry: dict[str, Any] | None  # shapely mapping(...) of the Polygon/MultiPolygon; null if none
    properties: FieldProperties


class FieldFeatureCollection(BaseModel):
    """The fields as a GeoJSON FeatureCollection (003-R5) — the Leaflet map source for 004."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[FieldFeature]


# ============================================================ Error body (R6, R4) =================


class ErrorCode(str, Enum):
    """Machine-readable reason on an error response — lets 004 branch without parsing prose."""

    field_not_found = "field_not_found"                # unknown NPDID (003-R6)
    forecast_not_available = "forecast_not_available"  # field exists, < 60 months (003-R4 / 002-R5)


class ErrorResponse(BaseModel):
    """Typed error body returned with every 4xx (003-R6, and the R4 insufficient-history 404)."""

    model_config = ConfigDict(extra="forbid")

    code: ErrorCode                  # which condition (distinguishes the two 404s — R4 vs R6)
    detail: str                      # human-readable message (echoes the offending npdid)
