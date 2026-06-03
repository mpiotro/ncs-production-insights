# 001 ingestion — plan

Design for the ingestion layer that retrieves SODIR open data, normalizes it into the **frozen** typed
contract (`contracts.md`), persists it to a single DuckDB file, and emits a typed ingestion report.
Every element below cites the EARS ID(s) it serves (principle 8). **Design only** — no implementation
code, no tests; the typed seams are in `contracts.md`.

## Component shape (the seams)
A small pipeline, each stage a pure-ish function the developer fills in and the test-author targets:

```
fetch (per dataset, with fallback)  →  normalize (→ typed models)  →  link (NPDID reconcile)
        R1 R2 R3                           R4 R5 R6 R7                       R8
                                                    ↓
                            persist (DuckDB upsert)  →  report (typed, persisted + returned)
                                    R10 R11                       R9
```

Public interface the run exposes (signatures only — bodies are the developer's):

```python
def ingest(con: duckdb.DuckDBPyConnection, settings: Settings) -> IngestionReport: ...
```

- `settings` carries source URLs, transport order, timeouts, retries, and the DuckDB path — all from
  **environment / config, never hard-coded secrets** (principle 7; there are no secrets here, SODIR is
  open, but URLs/ports stay configurable per tech-standards).
- The function returns the `IngestionReport` **and** has written it to DuckDB (see §Persistence).

---

## Sourcing & fallback (R1, R2, R3)

Two datasets, each with a **primary** transport and a **documented fallback**; R3 only requires *a*
working fallback, so we pick the primary that is most natural for each dataset.

| Dataset | Primary | Fallback | Why this order |
|---------|---------|----------|----------------|
| **Monthly production** (R1) | **CSV** — FactPages `field_production_monthly` | **Same `field_production_monthly` report in an alternate FactPages machine format** (e.g. XML / Excel via the ReportServer `rs:Format` parameter) | Production is bulk tabular full-history (1979→present); the CSV is a single stable columnar download. FactMaps `DataService` carries spatial map layers only (no production time-series), so the documented fallback is the **same FactPages report re-served in another machine format** — a format-variant of one service, still a published SODIR source (R3). |
| **Field outlines** (R2) | **REST** — FactMaps `DataService/Data` layer **7100 `field`** | CSV `downloads/csv/fldArea.zip` (WKT) | Geometry is authoritative on the FactMaps map service (layer 7100); the CSV `fldArea` WKT is the documented bulk fallback. |

**Fallback mechanism (R3).** A single `fetch(dataset)` per dataset tries transports **in order** and
returns the first success plus the `SourceRef` (`dataset, url, transport`) that won — so the report
records which transport actually served (R9). For production the two transports are two machine formats
of the *same* FactPages `field_production_monthly` report (CSV ⇄ alternate format); for geometry they are
two *distinct* SODIR services (FactMaps REST layer 7100 ⇄ CSV `fldArea` WKT). A transport "fails" on:
connection/timeout error, non-2xx status, or an empty/malformed payload (zero usable rows). The next
transport is attempted before any failure is reported; only if **all** transports fail does the run
raise. This is the seam the R3 acceptance test drives by forcing the primary to fail.

- **Every transport normalizes to the same in-memory shape** (a list of raw column dicts) *before*
  normalization, so the normalizer is transport-agnostic and the R3 path exercises identical downstream
  code. Whatever the format — CSV rows, an alternate FactPages export, or REST JSON features — each is
  mapped to the same SODIR column names (the `prf*` / `fld*` keys in the spec) at the edge of `fetch`.

**Library choices (feature-specific — belong here, not the constitution):**
- **HTTP:** `httpx` (sync `Client`) — modern, typed, timeouts + retries/transport config first-class.
- **CSV / tabular wrangling:** load via **DuckDB's own `read_csv_auto`** where practical (DuckDB is
  already the store and reads remote/zip CSV efficiently), with **`polars`** available for the light
  reshaping/validation pass before Pydantic. Rationale: keeps the bulk path columnar and fast; avoids a
  heavyweight pandas dependency.
- **Geometry:** **`shapely`** (tech-standards) for the R7 WKT validity check (parses as
  Polygon/MultiPolygon). No GeoJSON here — that is 003.
- **CSV unzip:** stdlib `zipfile` for the `fldArea.zip` fallback.

---

## Normalization (R4, R6, R7)

Raw column dicts → typed models (`contracts.md`). The contract types do most of the enforcement; the
normalizer's job is **coercion and the absent→null rule**.

- **Production → `MonthlyProduction` (R4, R6).** Map SODIR `prf*` columns to model fields.
  - **Type coercion:** `field_npdid, year, month` → `int`; the six stream volumes → `float`. SODIR
    decimals use `.`; trim whitespace.
  - **Absent → null (R6).** An empty/whitespace/missing cell becomes **`None`**, *not* `0.0`. A literal
    `0` (real zero-production month) stays `0.0`. This distinction is the crux of R6 and is unit-tested
    by the developer and acceptance-tested by the test-author.
  - **Non-negativity & month range (R6, R4).** Enforced by the contract (`Field(ge=0)`, `1<=month<=12`);
    a negative or out-of-range value raises at model construction — surfaced, never silently clamped.
  - **Units (R6).** Carried **native**: gas in billion Sm³; oil/NGL/condensate/oil-equivalents/produced
    water in million Sm³. **No conversion.** (See §Resolved open questions for the gas-unit decision.)
- **Field → `Field` (R5, R7).** Map `fld*` / `cmpLongName` columns; descriptive attributes → `str|None`;
  `field_npdid` → `int`, `discovery_year` → `int|None`.
  - **WKT validation (R7).** `geometry_wkt` is carried as the SODIR WKT string; the contract's
    `field_validator` rejects any non-null WKT that **shapely** cannot read as Polygon/MultiPolygon.
    Where SODIR publishes **no** outline, `geometry_wkt` is `None`. WKT stays WKT (003 converts).
  - **Note on SODIR spelling:** the source column is `fldCurrentActivitySatus` (SODIR's typo) → mapped to
    our clean `current_activity_status`. The mapping table is the single place that spelling lives.

---

## Link (R8)

After both datasets normalize, reconcile by **NPDID** (`MonthlyProduction.field_npdid` =
`Field.field_npdid`), many-to-one:

- Build the set of production NPDIDs and the set of field NPDIDs.
- `unmatched_production_npdids` = production NPDIDs with **no** matching `Field`.
- `unmatched_field_npdids` = field NPDIDs **absent** from production.
- **Nothing is dropped** — unmatched records are still persisted and counted; the mismatch is *reported*
  (R8, R9). This keeps full history (incl. shut-down/old fields) and lets 002/004 filter later.

---

## Persistence & idempotency (R10, R11)

Single embedded **DuckDB** file (tech-standards), path from config (`*.duckdb`, gitignored;
per-worktree file per CONTRIBUTING). Three tables mirror the three contract models.

**Schema (keys enforce R4/R5 uniqueness):**

```sql
CREATE TABLE IF NOT EXISTS field (
    field_npdid            BIGINT PRIMARY KEY,         -- R5 key
    field_name             VARCHAR NOT NULL,
    current_activity_status VARCHAR,
    hc_type                VARCHAR,
    main_area              VARCHAR,
    operator               VARCHAR,
    discovery_year         INTEGER,
    geometry_wkt           VARCHAR                      -- WKT; null where no outline (R7)
);

CREATE TABLE IF NOT EXISTS monthly_production (
    field_npdid     BIGINT  NOT NULL,                  -- → field.field_npdid (R8), not FK-enforced*
    field_name      VARCHAR NOT NULL,
    year            INTEGER NOT NULL,
    month           INTEGER NOT NULL,                  -- 1–12
    oil             DOUBLE,  gas             DOUBLE,    -- null = absent (R6), distinct from 0.0
    ngl             DOUBLE,  condensate      DOUBLE,
    oil_equivalents DOUBLE,  produced_water  DOUBLE,
    PRIMARY KEY (field_npdid, year, month)             -- R4 composite key ⇒ idempotency anchor (R11)
);

-- ingestion_report: see §Ingestion report for its schema
```

\* **No DB-level foreign key** from production→field: R8 *requires* keeping unmatched production rows and
reporting them, so a hard FK would wrongly reject them. The link is reconciled in code (§Link), not by
the engine.

**Upsert / idempotency (R10, R11).** Persist with DuckDB's
`INSERT ... ON CONFLICT (<pk>) DO UPDATE SET ...` (upsert) keyed on each table's primary key
(`(field_npdid, year, month)` for production, `field_npdid` for field). Re-running over identical source
data therefore **updates in place** — no duplicate field-month or field rows — making the run idempotent
(R11). The whole persist step runs in **one transaction** so a mid-run failure leaves the store
unchanged. Models are plain queryable rows afterward (R10).

---

## Ingestion report (R9)

`IngestionReport` (typed, `contracts.md`) is built **after** persist so its counts reflect what actually
landed, and the **completeness invariant** can be checked:

- **`sources`** — one `SourceRef` per dataset retrieved, recording the winning `transport` (so a fallback
  via R3 is visible).
- **`retrieved_at`** — UTC, timezone-aware, captured at run start.
- **`counts`** — `production_records` (rows persisted), `distinct_production_fields` (distinct
  `field_npdid` in production), `fields` (Field rows persisted).
- **Completeness (R9):** assert `counts.production_records == <source production row count>`; if they
  differ, the run fails loudly — a record was silently dropped, which R9 forbids. The source count is
  captured at fetch time, before any normalization, so drops anywhere in the pipeline are caught.
- **Reconciliation (R8/R9):** `unmatched_production_npdids` and `unmatched_field_npdids` from §Link.

**Where it lives (resolved):** **both** returned by `ingest(...)` *and* persisted to a DuckDB
`ingestion_report` table — one row per run, keyed by `retrieved_at`, with the two unmatched lists stored
as DuckDB native `BIGINT[]` columns (or JSON) and `sources` as JSON. Rationale below.

```sql
CREATE TABLE IF NOT EXISTS ingestion_report (
    retrieved_at                TIMESTAMPTZ PRIMARY KEY,   -- one row per run
    sources                     JSON     NOT NULL,         -- list[SourceRef]
    production_records          BIGINT   NOT NULL,
    distinct_production_fields  BIGINT   NOT NULL,
    fields                      BIGINT   NOT NULL,
    unmatched_production_npdids BIGINT[] NOT NULL,
    unmatched_field_npdids      BIGINT[] NOT NULL
);
```

---

## Resolved open questions (spec §"Open questions" — one-line rationale each)

1. **Gas unit → keep SODIR-native (billion Sm³).** Carry gas in billion Sm³ alongside the five
   million-Sm³ streams, each unit explicitly labeled in the contract. *Rationale:* zero lossy conversion
   in 001, the contract stays a faithful mirror of the source; any unit unification is a presentation
   concern 003/004 can apply over a frozen, well-labeled contract.
2. **Where the `IngestionReport` lives → persisted to DuckDB *and* returned.** *Rationale:* returning it
   gives the run/tests a direct typed handle (R9 acceptance), while persisting it gives an auditable
   run-history table and lets downstream phases read provenance/completeness from the same single store —
   at trivial cost (one row per run).
3. **Primary/secondary transport → production CSV-primary, geometry REST-primary** (table in §Sourcing).
   *Rationale:* production is bulk full-history tabular (CSV is the natural, robust bulk path), with its
   fallback the same FactPages report in an alternate machine format; geometry is authoritative on the
   FactMaps REST map service (layer 7100), with the CSV `fldArea` WKT as its R3 fallback.

---

## Traceability (principle 8)

| EARS | Where designed |
|------|----------------|
| R1 | §Sourcing — production fetch (CSV primary / alternate FactPages format fallback) |
| R2 | §Sourcing — field-outline fetch (REST 7100 primary / CSV fallback) |
| R3 | §Sourcing — ordered `fetch` with all-transports-before-failure (production: format-variant of one FactPages report; geometry: two distinct services) |
| R4 | `contracts.md` `MonthlyProduction` + PK `(field_npdid, year, month)`; §Normalization |
| R5 | `contracts.md` `Field` + PK `field_npdid`; §Normalization |
| R6 | §Normalization — native units, non-negative, absent→null; contract `ge=0` + `None` |
| R7 | `contracts.md` `Field.geometry_wkt` validator; §Normalization (shapely) |
| R8 | §Link — NPDID reconcile, unmatched reported not dropped |
| R9 | §Ingestion report — sources, UTC ts, counts, completeness invariant, unmatched lists |
| R10 | §Persistence — DuckDB tables, queryable after run |
| R11 | §Persistence — `ON CONFLICT DO UPDATE` upsert on each PK ⇒ idempotent |

---

## New open questions for the coordinator (decide before tagging `001-plan`)
1. **DuckDB primary-key enforcement.** DuckDB enforces `PRIMARY KEY` uniqueness but historically *not*
   FKs; the design relies on PK upsert (`ON CONFLICT`) for R11. Confirm the target DuckDB version
   supports `INSERT ... ON CONFLICT DO UPDATE` on these keys (it does in current releases) — pin the
   version in `uv.lock` during build-out.
2. **`ingestion_report` retention.** Keep **all** run rows (full audit history) or keep only the latest?
   Plan assumes keep-all (cheap, auditable). Flag if you want last-run-only.
3. **`field_name` carried on `MonthlyProduction`.** The spec's contract table includes it (from
   `prfInformationCarrier`), so it stays — but it is denormalized (also on `Field`). Confirm we keep it
   for fidelity to the source row rather than normalizing it away.
4. **No `Settings` model in the frozen contract.** Run configuration (URLs, transport order, timeouts,
   DB path) is an *internal* config object, intentionally **not** part of the frozen seam consumed by
   002/003/004. Confirm that boundary — the frozen contract is exactly the three data models in
   `contracts.md`.
