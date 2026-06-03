"""Frozen typed contract for 001 ingestion (task 001-T7).

These model signatures are the seam tagged ``001-contract-frozen`` and consumed read-only by
002 / 003 / 004. They mirror ``specs/001-ingestion/contracts.md`` exactly — field declarations
copied verbatim from the frozen contract; the only code added here is the body of the
``Field.geometry_wkt`` validator (R7), which the contract deliberately left to ``src/``.

Conventions (contracts.md):
- Pydantic v2, ``ConfigDict(frozen=True, extra="forbid")`` on every model — records are immutable
  value objects and reject unknown SODIR columns (R4/R5).
- Numeric stream volumes are ``Annotated[float, Field(ge=0)] | None`` — non-negative or null (R6).
  ``None`` means "SODIR published no value" and is distinct from ``0.0`` (a real zero month).
- ``int`` NPDIDs throughout; units are carried native (not converted) and live in field docs.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import AnyUrl, BaseModel, ConfigDict, field_validator
from pydantic import Field as PydanticField  # aliased so the model named ``Field`` can't shadow it
from shapely import wkt as shapely_wkt
from shapely.errors import ShapelyError

# native SODIR unit; ``None`` ⇒ absent (R6). Non-negative enforced by ``ge=0``.
NonNegVolume = Annotated[float, PydanticField(ge=0)]

# The shapely geometry classes a SODIR field outline is allowed to be (R7).
_POLYGONAL_GEOM_TYPES = frozenset({"Polygon", "MultiPolygon"})


class MonthlyProduction(BaseModel):
    """A single field-month production row, normalized from SODIR field_production_monthly (R4, R6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_npdid: int                              # prfNpdidInformationCarrier — link key (R8)
    field_name: str                               # prfInformationCarrier
    year: int                                     # prfYear
    month: Annotated[int, PydanticField(ge=1, le=12)]  # prfMonth (1–12)

    oil: NonNegVolume | None = None               # prfPrdOilNetMillSm3            · million Sm³
    gas: NonNegVolume | None = None               # prfPrdGasNetBillSm3            · billion Sm³
    ngl: NonNegVolume | None = None               # prfPrdNGLNetMillSm3           · million Sm³
    condensate: NonNegVolume | None = None        # prfPrdCondensateNetMillSm3     · million Sm³
    oil_equivalents: NonNegVolume | None = None   # prfPrdOeNetMillSm3            · million Sm³
    produced_water: NonNegVolume | None = None    # prfPrdProducedWaterInFieldMillSm3 · million Sm³


class Field(BaseModel):
    """A single NCS field: identity, descriptive attributes, outline geometry as WKT (R5, R7)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_npdid: int                              # fldNpdidField — link key (R8)
    field_name: str                               # fldName

    current_activity_status: str | None = None    # fldCurrentActivitySatus  (SODIR's spelling)
    hc_type: str | None = None                    # fldHcType
    main_area: str | None = None                  # fldMainArea
    operator: str | None = None                   # cmpLongName
    discovery_year: int | None = None             # fldDiscoveryYear

    geometry_wkt: str | None = None               # layer 7100 SHAPE / fldArea WKT — POLYGON|MULTIPOLYGON (R7)

    @field_validator("geometry_wkt")
    @classmethod
    def _wkt_is_polygonal(cls, v: str | None) -> str | None:
        """Reject non-null WKT that shapely can't read as Polygon/MultiPolygon (R7).

        ``None`` (SODIR publishes no outline) passes untouched. A non-null value must parse with
        shapely and be a Polygon or MultiPolygon — a syntactically invalid WKT (shapely raises) or
        a valid-but-wrong geometry class (e.g. ``POINT``/``LINESTRING``) is rejected, surfacing a
        bad outline at construction rather than letting it reach the store.
        """
        if v is None:
            return v
        try:
            geom = shapely_wkt.loads(v)
        except (ShapelyError, ValueError, TypeError) as exc:
            raise ValueError(f"geometry_wkt is not valid WKT shapely can read: {v!r}") from exc
        if geom.geom_type not in _POLYGONAL_GEOM_TYPES:
            raise ValueError(
                f"geometry_wkt must be Polygon or MultiPolygon, got {geom.geom_type}: {v!r}"
            )
        return v


class Dataset(str, Enum):
    """Which SODIR dataset a run pulled (R9)."""

    production = "production"   # SODIR field_production_monthly
    field = "field"             # SODIR field outlines (layer 7100 / fldArea)


class Transport(str, Enum):
    """The transport a dataset was retrieved over — records whether the R3 fallback was used."""

    rest = "rest"
    csv = "csv"


class SourceRef(BaseModel):
    """Which dataset was pulled, from where, over which transport — one per dataset (R9)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: Dataset
    url: AnyUrl
    transport: Transport       # rest | csv — records whether the fallback (R3) was used


class RecordCounts(BaseModel):
    """Per-dataset record counts for the run (R9)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    production_records: Annotated[int, PydanticField(ge=0)]          # rows persisted; == source count (R9)
    distinct_production_fields: Annotated[int, PydanticField(ge=0)]  # distinct field_npdid in production
    fields: Annotated[int, PydanticField(ge=0)]                      # Field records persisted


class IngestionReport(BaseModel):
    """Typed summary of one ingestion run (R9)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sources: list[SourceRef]                       # one entry per dataset actually retrieved
    retrieved_at: datetime                         # UTC, timezone-aware
    counts: RecordCounts

    unmatched_production_npdids: list[int]         # in production, absent from fields (R8, R9)
    unmatched_field_npdids: list[int]              # in fields, absent from production (R8, R9)
