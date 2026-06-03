# 001 ingestion — frozen contract (Pydantic v2)

**This is the seam.** These model signatures are what gets tagged `001-contract-frozen` and consumed
read-only by 002 / 003 / 004. They mirror the spec's contract tables exactly (spec §"Data / interface
contract"). Signatures and field declarations only — **no method bodies, no fetch/parse logic** (that is
the developer's job, built to these types).

Conventions used below:
- Pydantic v2, `model_config = ConfigDict(frozen=True, extra="forbid")` on every model — records are
  immutable value objects and reject unknown SODIR columns silently sneaking in.
- Numeric stream volumes are `Annotated[float, Field(ge=0)] | None` — **non-negative or null** (R6).
  `None` means "SODIR published no value" and is distinct from `0.0` (a real zero-production month).
- `int` NPDIDs throughout (SODIR NPDIDs are stable integer identifiers).
- Units live in field descriptions (and here in the tables); they are **not** converted — values are
  carried in their native SODIR unit (R6).

---

## `MonthlyProduction`
One record per field-month. **Key:** `(field_npdid, year, month)` (R4).
Composite uniqueness is enforced at persistence (DuckDB primary key, see plan.md §Persistence), and a
`model_validator` asserts `1 <= month <= 12`.

```python
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator

NonNegVolume = Annotated[float, Field(ge=0)]  # native SODIR unit; None ⇒ absent (R6)

class MonthlyProduction(BaseModel):
    """A single field-month production row, normalized from SODIR field_production_monthly (R4, R6)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    field_npdid: int                              # prfNpdidInformationCarrier — link key (R8)
    field_name: str                               # prfInformationCarrier
    year: int                                     # prfYear
    month: Annotated[int, Field(ge=1, le=12)]     # prfMonth (1–12)

    oil: NonNegVolume | None = None               # prfPrdOilNetMillSm3            · million Sm³
    gas: NonNegVolume | None = None               # prfPrdGasNetBillSm3            · billion Sm³
    ngl: NonNegVolume | None = None               # prfPrdNGLNetMillSm3           · million Sm³
    condensate: NonNegVolume | None = None        # prfPrdCondensateNetMillSm3     · million Sm³
    oil_equivalents: NonNegVolume | None = None   # prfPrdOeNetMillSm3            · million Sm³
    produced_water: NonNegVolume | None = None    # prfPrdProducedWaterInFieldMillSm3 · million Sm³
```

| field | type | unit | nullable | SODIR source |
|-------|------|------|----------|--------------|
| `field_npdid` | int | — | no | `prfNpdidInformationCarrier` |
| `field_name` | str | — | no | `prfInformationCarrier` |
| `year` | int | — | no | `prfYear` |
| `month` | int (1–12) | — | no | `prfMonth` |
| `oil` | float ≥ 0 | million Sm³ | yes | `prfPrdOilNetMillSm3` |
| `gas` | float ≥ 0 | **billion Sm³** | yes | `prfPrdGasNetBillSm3` |
| `ngl` | float ≥ 0 | million Sm³ | yes | `prfPrdNGLNetMillSm3` |
| `condensate` | float ≥ 0 | million Sm³ | yes | `prfPrdCondensateNetMillSm3` |
| `oil_equivalents` | float ≥ 0 | million Sm³ | yes | `prfPrdOeNetMillSm3` |
| `produced_water` | float ≥ 0 | million Sm³ | yes | `prfPrdProducedWaterInFieldMillSm3` |

> **Gas unit (resolved open question):** kept SODIR-native **billion Sm³**, the other five streams in
> million Sm³, each labeled per field. See plan.md §Resolved open questions.

---

## `Field`
One record per field. **Key:** `field_npdid` (R5). Carries identity, descriptive attributes, and the
outline geometry as WKT (R5, R7).

```python
from pydantic import BaseModel, ConfigDict, field_validator

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
        """Reject non-null WKT that shapely can't read as Polygon/MultiPolygon (R7). Body in src/."""
        ...
```

| field | type | nullable | SODIR source |
|-------|------|----------|--------------|
| `field_npdid` | int | no | `fldNpdidField` |
| `field_name` | str | no | `fldName` |
| `current_activity_status` | str | yes | `fldCurrentActivitySatus` |
| `hc_type` | str | yes | `fldHcType` |
| `main_area` | str | yes | `fldMainArea` |
| `operator` | str | yes | `cmpLongName` |
| `discovery_year` | int | yes | `fldDiscoveryYear` |
| `geometry_wkt` | str (WKT polygon/multipolygon) | yes | layer 7100 `SHAPE` / `fldArea` WKT |

> `geometry_wkt` stays **WKT** in the 001 contract. The WKT→GeoJSON conversion is **003's** job, not 001's
> (spec §Scope/Out). The validator above only asserts shapely *parses* it as polygon/multipolygon.

---

## `IngestionReport` and its parts
Typed run artifact emitted when a run completes (R9). It records the source(s) used, the retrieval
timestamp, per-dataset counts, and the two unmatched-NPDID lists. **Completeness invariant (R9):**
`counts.production_records` equals the source production row count — surfaced here so a silent drop is
visible. The report is both **returned** by the run and **persisted** to DuckDB (see plan.md §Resolved
open questions).

```python
from datetime import datetime
from enum import Enum
from pydantic import AnyUrl, BaseModel, ConfigDict, Field

class Dataset(str, Enum):
    production = "production"   # SODIR field_production_monthly
    field = "field"             # SODIR field outlines (layer 7100 / fldArea)

class Transport(str, Enum):
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
    production_records: Annotated[int, Field(ge=0)]          # rows persisted; MUST equal source count (R9)
    distinct_production_fields: Annotated[int, Field(ge=0)]  # distinct field_npdid in production
    fields: Annotated[int, Field(ge=0)]                      # Field records persisted

class IngestionReport(BaseModel):
    """Typed summary of one ingestion run (R9)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    sources: list[SourceRef]                       # one entry per dataset actually retrieved
    retrieved_at: datetime                         # UTC, timezone-aware
    counts: RecordCounts

    unmatched_production_npdids: list[int]         # in production, absent from fields (R8, R9)
    unmatched_field_npdids: list[int]              # in fields, absent from production (R8, R9)
```

**`IngestionReport` field map (matches spec):**

| field | type | meaning |
|-------|------|---------|
| `sources` | list[SourceRef] | `(dataset, url, transport rest\|csv)` per dataset retrieved |
| `retrieved_at` | datetime (UTC) | when the run pulled data |
| `counts` | RecordCounts | production records · distinct production fields · fields |
| `unmatched_production_npdids` | list[int] | production NPDIDs with no matching `Field` |
| `unmatched_field_npdids` | list[int] | field NPDIDs absent from production |

---

## Contract notes for downstream phases
- **Link (R8):** `MonthlyProduction.field_npdid` → `Field.field_npdid`, many-to-one. Either-direction
  mismatches are *reported* (`IngestionReport.unmatched_*`), **never dropped**.
- **Nullability discipline:** absent volume ⇒ `None`, never `0.0` (R6). 002's forecaster must treat
  `None` as "no observation," not zero production.
- **Immutability:** all models are `frozen`; treat instances as read-only value objects.
- **No conversions baked in:** units are native SODIR; geometry is WKT. Any unit unification or
  WKT→GeoJSON is a downstream decision, out of scope for 001.
