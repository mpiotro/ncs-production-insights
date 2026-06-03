# 003 api — response contract (Pydantic v2)

**This is the 003 seam.** 003 defines **no new persisted entity** (principle 3 / spec §Data contract):
it *serves the frozen 001/002 models as JSON*. The only new types are the thin **response envelopes**
and the **GeoJSON** Feature / FeatureCollection models — the wrappers FastAPI needs so the
**auto-generated OpenAPI** document (R7) is fully self-describing for 004. Signatures and field
declarations only; bodies/routes are the developer's, built to these types.

Conventions (mirroring `specs/001-ingestion/contracts.md` / `002-analytics/contracts.md`):
- Pydantic v2. These are **response** models, so — unlike the frozen value-objects — they are *not*
  `frozen`, but they keep `ConfigDict(extra="forbid")` so a malformed response shape is caught.
- The served 001/002 models (`Field`, `MonthlyProduction`, `FieldForecast`) are **re-used verbatim** as
  nested response types — never redefined here (they are read-only, principle 3). FastAPI serialises
  them from their own definitions, so OpenAPI shows the real frozen schema.
- GeoJSON follows RFC 7946: a `Feature` has `type`, `geometry`, `properties`; a `FeatureCollection` has
  `type` + `features`. Geometry is the shapely-`mapping(...)` dict (a `{type, coordinates}` GeoJSON
  geometry), typed loosely as a JSON object so any Polygon/MultiPolygon serialises without a bespoke
  coordinate schema.

---

## List envelopes (R2, R3) — small, explicit wrappers

A top-level JSON **array** is awkward to evolve and to document; each collection response is a thin
object envelope carrying a `count` plus the typed items. The item types are the **frozen models**,
re-used as-is.

```python
from pydantic import BaseModel, ConfigDict
from ncs.contracts import Field, MonthlyProduction

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
```

> The field **detail** endpoint (R2/R6) returns the frozen `Field` **directly** (no envelope) — a
> single resource needs no `count`. `MonthlyProduction.gas` stays billion-Sm³, the rest million-Sm³,
> exactly as 001 froze them; null streams serialise as JSON `null` (R3, distinct from `0.0`).

---

## Forecast response (R4) — served `FieldForecast`, insufficient-history is a distinct outcome

The forecast endpoint returns the frozen **`FieldForecast`** *directly* on success (the 24 points,
`method`, `backtest_mape`, `credible`, `history_months`). The R4 "insufficient history" case is **not**
an empty or fabricated forecast — it is a **distinct HTTP outcome** (404 + typed error, see below), so a
`FieldForecast` body always means a real forecast. No new wrapper type is needed for the success path.

```python
from ncs.forecast.contracts import FieldForecast   # served verbatim on success (003-R4)
```

> Why 404 (not 200-with-flag) for insufficient history: the resource "this field's forecast" does **not
> exist** (the field has < 60 months, 002-R5), which is exactly HTTP 404. The error body's `detail`
> distinguishes it from an unknown-NPDID 404 (R6) so 004 can tell "no such field" from "field exists,
> no forecast" — see `ErrorResponse.code`.

---

## GeoJSON FeatureCollection (R5) — WKT → GeoJSON via shapely

Fields as a GeoJSON FeatureCollection. Each feature's geometry is produced by **shapely** from the
field's `geometry_wkt` (`shapely.wkt.loads` → `shapely.geometry.mapping`), and its `properties` carry
the **npdid + name** (R5). A field whose `geometry_wkt` is `null` becomes a feature with **`geometry:
null`** (RFC 7946 allows null geometry) — kept in the collection so the property set is complete, rather
than silently omitted. (Omission is the documented alternative; default = null-geometry feature, see
plan §Resolved.)

```python
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict

class FieldProperties(BaseModel):
    """A GeoJSON feature's properties for a field (003-R5) — identity only, for the map layer."""
    model_config = ConfigDict(extra="forbid")
    field_npdid: int                 # NPDID — the join key 004 uses to link map ⇄ charts
    field_name: str                  # human label for the feature

class FieldFeature(BaseModel):
    """One GeoJSON Feature: a field's outline (or null) + its identity (003-R5)."""
    model_config = ConfigDict(extra="forbid")
    type: Literal["Feature"] = "Feature"
    geometry: dict[str, Any] | None  # shapely mapping(...) of the Polygon/MultiPolygon; null if no outline
    properties: FieldProperties

class FieldFeatureCollection(BaseModel):
    """The fields as a GeoJSON FeatureCollection (003-R5) — the Leaflet map source for 004."""
    model_config = ConfigDict(extra="forbid")
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[FieldFeature]
```

> `geometry` is typed as a free-form JSON object (`dict[str, Any]`) rather than a closed Polygon /
> MultiPolygon coordinate schema: the exact nesting differs by geometry type and is RFC-7946 standard,
> so a loose object keeps OpenAPI honest (it *is* arbitrary GeoJSON geometry) without hand-writing a
> coordinate grammar the constitution says we never hand-write. 004 hands it straight to Leaflet.

---

## Error body (R6) — one typed shape for every non-2xx

A single typed error model is the body of every 404 (and any future 4xx), so OpenAPI documents one
error schema and 004 parses one shape.

```python
from enum import Enum
from pydantic import BaseModel, ConfigDict

class ErrorCode(str, Enum):
    """Machine-readable reason on an error response — lets 004 branch without parsing prose."""
    field_not_found = "field_not_found"           # unknown NPDID (003-R6)
    forecast_not_available = "forecast_not_available"  # field exists, < 60 months (003-R4 / 002-R5)

class ErrorResponse(BaseModel):
    """Typed error body returned with every 4xx (003-R6, and the R4 insufficient-history 404)."""
    model_config = ConfigDict(extra="forbid")
    code: ErrorCode                  # which condition (distinguishes the two 404s — R4 vs R6)
    detail: str                      # human-readable message (echoes the offending npdid)
```

> `code` is what makes the **two 404s distinct** (principle: R4 demands the insufficient-history case be
> indicated *distinctly*). `field_not_found` ⇒ no such field (R6); `forecast_not_available` ⇒ the field
> exists but has no forecast (R4). FastAPI maps both to HTTP 404 with this body via an exception handler.

---

## Why these (and only these) types are the seam
- **No new persisted entity** (principle 3): every type here is either a frozen 001/002 model re-used
  verbatim, or a transport wrapper (envelope / GeoJSON / error). 003 reads the store and shapes JSON; it
  owns no data.
- **OpenAPI is the real consumable contract** (R7). Because the nested types are the *actual* frozen
  models, `/openapi.json` exposes their true schema (units in field descriptions, null vs 0.0, the
  24-point forecast) — 004 generates its client against truth, not a hand-maintained copy.
- **GeoJSON is contract-checked, not stringly-typed.** Modelling Feature / FeatureCollection (rather than
  returning a raw dict) means OpenAPI and the acceptance tests both assert the RFC-7946 envelope.
