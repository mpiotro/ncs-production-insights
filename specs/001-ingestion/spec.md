# 001 ingestion — spec

## Purpose
Ingest SODIR open data — monthly production per field and field outlines — normalize it, persist it to
DuckDB, and **FREEZE the typed Pydantic v2 data contract** that 002 / 003 / 004 build on. Sequential;
blocks all downstream phases.

## Scope
- **In:** retrieve full-history monthly production per field and field-outline geometry from SODIR
  (REST primary, CSV fallback); normalize into typed models; persist to a single DuckDB file; emit an
  ingestion report; freeze the contract.
- **Coverage:** every field present in the SODIR monthly-production table — **full history, including
  shut-down fields**. Activity status is carried so 002 / 004 can filter; the forecasting ≥60-month gate
  is a 002 concern, not 001's.
- **Out:** forecasting (002); the HTTP API (003); frontend, map rendering and the **WKT→GeoJSON**
  conversion (003 / 004); wellbore / facility / discovery layers; economics / reserves; real-time data.

### Sources (grounded — SODIR, NLOD 2.0)
- **Monthly production:** FactPages `field_production_monthly` (CSV header verified; history 1979→present).
  Columns `prfInformationCarrier, prfYear, prfMonth, prfPrdOilNetMillSm3, prfPrdGasNetBillSm3,
  prfPrdNGLNetMillSm3, prfPrdCondensateNetMillSm3, prfPrdOeNetMillSm3, prfPrdProducedWaterInFieldMillSm3,
  prfNpdidInformationCarrier`.
- **Field outlines:** FactMaps REST `DataService/Data` layer **7100 `field`** (polygon) / CSV
  `downloads/csv/fldArea.zip` (WKT).
- **Link key:** production `prfNpdidInformationCarrier` = field `fldNpdidField`.

## Requirements (EARS)
- **001-R1** — WHEN an ingestion run executes, the system SHALL retrieve the full available monthly
  production history for every field from SODIR open data.
- **001-R2** — WHEN an ingestion run executes, the system SHALL retrieve the field-outline geometry for
  NCS fields from SODIR open data.
- **001-R3** — IF the primary SODIR source for a dataset is unavailable or errors, THEN the system SHALL
  obtain that dataset from an alternate published SODIR source or machine format before reporting failure.
- **001-R4** — WHEN a production record is ingested, the system SHALL normalize it into a typed
  `MonthlyProduction` model uniquely keyed by (field NPDID, year, month).
- **001-R5** — WHEN a field is ingested, the system SHALL normalize it into a typed `Field` model keyed by
  field NPDID, carrying its identity, descriptive attributes, and outline geometry.
- **001-R6** — WHEN a production record is normalized, the system SHALL store each stream volume as a
  non-negative number in its SODIR unit (oil, NGL, condensate, oil-equivalents and produced water in
  **million Sm³**; gas in **billion Sm³**), and SHALL normalize an absent volume to null.
- **001-R7** — WHEN a field outline is normalized, the system SHALL carry it as a WKT string that shapely
  parses as a polygon or multipolygon, or null where SODIR publishes no outline for that field.
- **001-R8** — The system SHALL link each `MonthlyProduction` record to a `Field` through the field NPDID
  (`prfNpdidInformationCarrier` = `fldNpdidField`).
- **001-R9** — WHEN an ingestion run completes, the system SHALL emit a typed ingestion report recording
  the source(s) used, the retrieval timestamp, and per-dataset record counts, and listing every NPDID
  present in one dataset but unmatched in the other; the persisted production-record count SHALL equal the
  source record count (no record is silently dropped).
- **001-R10** — WHEN normalization completes, the system SHALL persist the typed models to the single
  DuckDB store.
- **001-R11** — WHEN an ingestion run repeats over identical source data, the system SHALL upsert by key
  so the store holds no duplicate field-month or field records (idempotent).

## Data / interface contract (FROZEN — Pydantic v2)

### `MonthlyProduction` — one record per field-month · key `(field_npdid, year, month)`
| field | type | unit | nullable | SODIR source |
|-------|------|------|----------|--------------|
| `field_npdid` | int | — | no | `prfNpdidInformationCarrier` |
| `field_name` | str | — | no | `prfInformationCarrier` |
| `year` | int | — | no | `prfYear` |
| `month` | int (1–12) | — | no | `prfMonth` |
| `oil` | float ≥ 0 | million Sm³ | yes | `prfPrdOilNetMillSm3` |
| `gas` | float ≥ 0 | billion Sm³ | yes | `prfPrdGasNetBillSm3` |
| `ngl` | float ≥ 0 | million Sm³ | yes | `prfPrdNGLNetMillSm3` |
| `condensate` | float ≥ 0 | million Sm³ | yes | `prfPrdCondensateNetMillSm3` |
| `oil_equivalents` | float ≥ 0 | million Sm³ | yes | `prfPrdOeNetMillSm3` |
| `produced_water` | float ≥ 0 | million Sm³ | yes | `prfPrdProducedWaterInFieldMillSm3` |

### `Field` — one record per field · key `field_npdid`
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

### Link & `IngestionReport`
- **Link:** `MonthlyProduction.field_npdid` → `Field.field_npdid` (many-to-one). Unmatched NPDIDs in
  **either** direction are reported, never dropped (R8, R9).
- **`IngestionReport`** (typed run artifact): `sources` (dataset, url, transport rest|csv), `retrieved_at`
  (UTC), `counts` (production records, distinct production fields, fields), `unmatched_production_npdids`,
  `unmatched_field_npdids`.

## Acceptance criteria
- **R1 / R2** — a run yields a non-empty production set spanning many years and a non-empty field set;
  both originate from the SODIR sources above.
- **R3** — with the primary source forced to fail, the run still loads the dataset from the fallback.
- **R4 / R5** — every persisted record validates against its model; `(field_npdid, year, month)` and
  `field_npdid` are unique keys.
- **R6** — volumes are non-negative; units match the table; an absent cell becomes null (not 0).
- **R7** — every non-null `geometry_wkt` parses with shapely as polygon/multipolygon.
- **R8** — each production record's `field_npdid` either resolves to a `Field` or appears in the report.
- **R9** — report lists sources, timestamp, counts and both unmatched lists; persisted production count
  equals the source row count.
- **R10** — models are queryable from the DuckDB file after a run.
- **R11** — running twice over the same input leaves record counts unchanged (no duplicates).

## Open questions (non-blocking — defaults chosen, flag to change)
- **Gas unit** kept SODIR-native (billion Sm³) alongside million-Sm³ liquids, explicitly labeled. Unify
  all to million Sm³ instead? (Adds one normalization step.) — *default: keep native.*
- **Where the `IngestionReport` lives** — persisted as a DuckDB table vs returned/logged: a **plan.md**
  call for the architect.
- **Primary/secondary transport per dataset** (production is tabular → likely CSV-primary; geometry →
  REST-primary): a **plan.md** call; R3 only requires a working documented fallback.
