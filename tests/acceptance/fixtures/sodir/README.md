# Shared local SODIR fixtures — canonical sample for acceptance suites T2–T6

These four files are the **single canonical hermetic SODIR sample** for the entire 001 ingestion
acceptance suite. They are authored at **001-T2** (sourcing & fallback) but the contents are designed so
that **T3 (normalization/conformance), T4 (link reconcile), T5 (persistence/idempotency) and
T6 (report/completeness)** all assert against these same files. Keep them small and stable; if you change
a row, re-check every suite that depends on the edge case it carries (table below).

Everything is read **through the `settings` source seam** — `ingest(con, settings)` is pointed at these
local paths, so the acceptance tests run with **zero live network**. No file here is the real SODIR
download; they are hand-authored miniatures that use the **real SODIR column / attribute names**.

## Files

| File | Dataset | Transport class | Real SODIR analogue |
|------|---------|-----------------|---------------------|
| `production_primary.csv` | production | CSV | FactPages `field_production_monthly` CSV export |
| `production_fallback.csv` | production | CSV | the **same** `field_production_monthly` report re-served in an alternate FactPages machine format (kept CSV-class on purpose — see note) |
| `field_primary.json` | field | REST | FactMaps `DataService/Data` layer 7100 `field` feature payload |
| `field_fallback.csv` | field | CSV | `downloads/csv/fldArea.zip` (`fldArea` WKT) bulk fallback |

### Production CSV columns (both production files)
`prfInformationCarrier, prfYear, prfMonth, prfPrdOilNetMillSm3, prfPrdGasNetBillSm3,
prfPrdNGLNetMillSm3, prfPrdCondensateNetMillSm3, prfPrdOeNetMillSm3,
prfPrdProducedWaterInFieldMillSm3, prfNpdidInformationCarrier`

`production_fallback.csv` holds the **exact same rows** as `production_primary.csv`. The R3 production
fallback test proves *ordering* (primary path fails → fallback path is tried and wins), **not** a second
parser; the `Transport` enum is frozen to `{rest, csv}` and cannot express a third format, so the
production fallback stays CSV-class and is proven via the winning `SourceRef.url` pointing at the
*fallback* file (see T2 / `test_sourcing.py`).

### Field REST payload (`field_primary.json`)
ArcGIS-style `features: [{ "attributes": {...} }]`. Each `attributes` object carries the SODIR field
columns **and the outline geometry as a `geometry_wkt` string** rather than ArcGIS rings.

> **Documented hermetic assumption (flag for the developer's REST handler, T8):** the layer-7100 fixture
> carries geometry as a ready WKT string under the `geometry_wkt` attribute, *not* as ArcGIS
> `geometry.rings`. This keeps the fixture small and lets the REST handler read WKT directly (the same
> WKT the contract's R7 validator expects). If the real T8 REST handler instead converts ArcGIS rings →
> WKT against the live service, that is fine — but to satisfy these hermetic tests it must read the
> `geometry_wkt` attribute when present. SODIR's misspelled `fldCurrentActivitySatus` is kept verbatim
> (it maps to the contract's `current_activity_status`).

### Field CSV fallback (`field_fallback.csv`)
Columns: `fldNpdidField, fldName, fldCurrentActivitySatus, fldHcType, fldMainArea, cmpLongName,
fldDiscoveryYear, geometry_wkt`. Carries the **same four fields** (NPDIDs 1001–1004) as the REST primary
so the geometry-fallback R3 path yields an identical field set. GAMMA's geometry cell is **empty**
(the null-outline case, equivalent to the REST payload's `geometry_wkt: null`).

## The dataset at a glance

**Fields (4):** all in `field_primary.json` and `field_fallback.csv`.

| NPDID | fldName | activity status | geometry | serves |
|------:|---------|-----------------|----------|--------|
| 1001 | ALPHA | Producing | **POLYGON** | R7 polygon case; has production |
| 1002 | BETA  | Producing | **MULTIPOLYGON** | R7 multipolygon case; has production |
| 1003 | GAMMA | Shut down | **null** (no outline) | R7 null-geometry case; has production |
| 1004 | DELTA | Approved for production | POLYGON | **R8 unmatched field** — a field with **no production** |

**Production (10 field-month rows):** in both `production_*.csv`.

| NPDID (prf) | name | year-months | serves |
|------:|------|-------------|--------|
| 1001 | ALPHA | 2021-11, 2021-12, 2022-01, 2022-02 | R1 multi-year span (2021 + 2022); matches field 1001 |
| 1002 | BETA  | 2022-01, 2022-02, 2023-01 | R1 multi-year span (2022 + 2023); matches field 1002 |
| 1003 | GAMMA | 2022-06, 2022-07 | matches field 1003; carries the absent/zero edge cells (below) |
| 1009 | ORPHANPROD | 2023-03 | **R8 unmatched production** — production NPDID with **no matching field** |

**Distinct production NPDIDs:** 4 (1001, 1002, 1003, 1009).
**Distinct production NPDIDs that match a field:** 3 (1001, 1002, 1003).

## EARS edge cases baked in (which row / file carries each)

| EARS | Edge case | Where |
|------|-----------|-------|
| **R1** | production spans **many distinct years** | ALPHA spans 2021 & 2022; BETA spans 2022 & 2023 → distinct years = {2021, 2022, 2023} |
| **R1** | non-empty production set; `production_records` == source row count | 10 data rows in `production_primary.csv` / `production_fallback.csv` |
| **R2** | non-empty field set with geometry | 4 fields in `field_primary.json` / `field_fallback.csv` |
| **R3** | production fallback ordering | `production_fallback.csv` == primary data; fallback proven via winning source URL |
| **R3** | geometry fallback ordering (rest→csv transport flip) | `field_fallback.csv` reached when the REST primary source is bad |
| **R6** | **absent** volume cell → must normalize to **null** (not 0.0) | GAMMA 2022-06 **and** 2022-07: `prfPrdNGLNetMillSm3` and `prfPrdCondensateNetMillSm3` are **empty** |
| **R6** | literal **0.0** real-zero month → stays 0.0 (distinct from null) | GAMMA 2022-06: `oil=0.0, gas=0.0, oil_equivalents=0.0, produced_water=0.0`; also ALPHA `condensate=0.0` on every row |
| **R6** | non-negative volumes in native units (gas billion Sm³, rest million Sm³) | all rows (no negatives anywhere) |
| **R7** | geometry parses as **POLYGON** | ALPHA (1001) |
| **R7** | geometry parses as **MULTIPOLYGON** | BETA (1002) |
| **R7** | **null** geometry (SODIR publishes no outline) | GAMMA (1003): `null` in JSON, empty cell in CSV |
| **R8** | production NPDID with **no matching field** (`unmatched_production_npdids`) | ORPHANPROD (1009): in production, absent from fields → expect `[1009]` |
| **R8** | field NPDID with **no production** (`unmatched_field_npdids`) | DELTA (1004): a field, absent from production → expect `[1004]` |
| **R9** | distinct production fields count = 4; fields count = 4; production records = 10 | counts derived from the rows above |
| **R11** | idempotent re-run leaves counts unchanged | same files re-ingested → no new rows (keyed `(field_npdid, year, month)` / `field_npdid`) |

## Expected derived values (handy for assertions across T2–T6)

- `counts.production_records` = **10**
- `counts.distinct_production_fields` = **4** (1001, 1002, 1003, 1009)
- `counts.fields` = **4** (1001, 1002, 1003, 1004)
- `unmatched_production_npdids` = **[1009]** (ORPHANPROD)
- `unmatched_field_npdids` = **[1004]** (DELTA)
- distinct production years = **{2021, 2022, 2023}** (≥ 2 distinct → R1 "spanning many years")
- ALPHA 2022-01 oil = **1.180** (million Sm³), gas = **0.940** (billion Sm³)
- GAMMA 2022-06: `oil == 0.0` (real zero) AND `ngl is None`, `condensate is None` (absent → null)
