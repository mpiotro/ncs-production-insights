"""Acceptance suite: normalization & contract conformance — EARS 001-R4, R5, R6, R7 (task 001-T3).

Two complementary halves, both black-box against the *frozen* contract (`contracts.md`):

1. **Through-ingest** — run the public seam ``ingest(con, good_settings)`` against the shared
   canonical SODIR fixtures (``fixtures/sodir/``, see its README manifest), then read the DuckDB
   ``monthly_production`` / ``field`` tables back and prove every persisted row reconstructs into
   its typed model, the keys are unique, the SODIR-column→field mapping is right, absent cells are
   ``None`` (≠ ``0.0``), units stay SODIR-native, and outlines parse with shapely as
   polygon/multipolygon (or are ``None`` where SODIR publishes no outline).

2. **Direct model conformance** — the all-valid fixtures cannot exercise the contract's *rejection*
   guarantees (negative volume, out-of-range month, non-polygonal WKT, immutability/extra-forbid),
   so those are asserted by constructing the frozen ``MonthlyProduction`` / ``Field`` models
   directly from minimal valid baselines (built from the real fixture values). This is acceptance of
   the frozen contract's R4/R6/R7 guarantees; per the task's hard boundary the shared fixtures are
   NOT mutated to carry bad rows (other suites depend on their exact contents).

Like the rest of the suite these import ``ncs.ingest`` / ``ncs.contracts``, which do not exist yet,
so the module is **red at collection time** until the developer builds the seam (001-T7/T9). That is
the intended TDD starting state; the assertions are written to go green once the seam exists exactly
as the conftest constructs it and the contract is implemented as frozen in ``contracts.md``.
"""

from __future__ import annotations

import duckdb
import pytest
from pydantic import ValidationError
from shapely import wkt as shapely_wkt
from shapely.geometry.base import BaseGeometry

# Frozen contract types (contracts.md). Importing at module scope makes the whole suite go red for
# the right reason — these resolve only once the developer adds the package modules.
from ncs import ingest
from ncs.contracts import Field, MonthlyProduction

# --- Expected values pinned to the canonical fixture set (fixtures/sodir/README.md + the files) ---

EXPECTED_PRODUCTION_ROWS = 10
EXPECTED_FIELD_ROWS = 4

# Field NPDIDs and their geometry outcome (field_primary.json / field_fallback.csv).
NPDID_ALPHA = 1001  # POLYGON
NPDID_BETA = 1002  # MULTIPOLYGON
NPDID_GAMMA = 1003  # null outline (SODIR publishes none) + the absent/zero production cells
NPDID_DELTA = 1004  # POLYGON

# ALPHA 2022-01 (production_primary.csv row 4) — the SODIR-column→field mapping spot-check (R4).
# prfInformationCarrier=ALPHA, prfYear=2022, prfMonth=1,
# prfPrdOilNetMillSm3=1.180, prfPrdGasNetBillSm3=0.940, prfPrdNGLNetMillSm3=0.105,
# prfPrdCondensateNetMillSm3=0.0, prfPrdOeNetMillSm3=2.205, prfPrdProducedWaterInFieldMillSm3=0.500
ALPHA_JAN_2022 = {
    "field_npdid": NPDID_ALPHA,
    "field_name": "ALPHA",
    "year": 2022,
    "month": 1,
    "oil": 1.180,
    "gas": 0.940,  # billion Sm³ — stays native, NOT scaled to million
    "ngl": 0.105,
    "condensate": 0.0,  # a real zero cell on every ALPHA row (distinct from absent → null)
    "oil_equivalents": 2.205,
    "produced_water": 0.500,
}

# GAMMA descriptive attributes (field_primary.json / field_fallback.csv, NPDID 1003) — R5 mapping,
# including SODIR's misspelled source column ``fldCurrentActivitySatus`` and ``cmpLongName``.
GAMMA_FIELD = {
    "field_npdid": NPDID_GAMMA,
    "field_name": "GAMMA",
    "current_activity_status": "Shut down",  # fldCurrentActivitySatus (SODIR's typo)
    "hc_type": "OIL",  # fldHcType
    "main_area": "Barents sea",  # fldMainArea
    "operator": "Gamma Operator AS",  # cmpLongName
    "discovery_year": 1990,  # fldDiscoveryYear
    "geometry_wkt": None,  # no published outline (R7 null case)
}


# --- Helpers: read DuckDB rows as dicts whose keys are the table/model column names --------------


def _rows_as_dicts(
    con: duckdb.DuckDBPyConnection, table: str
) -> list[dict[str, object]]:
    """Return every row of ``table`` as a dict keyed by column name.

    Pulls keys from ``cursor.description`` so they line up 1:1 with the contract model fields (the
    seam guarantees the table columns equal the model fields). DuckDB yields SQL ``NULL`` as Python
    ``None``, so absent cells come back as ``None`` and feed straight into the Pydantic model.
    """
    cur = con.execute(f"SELECT * FROM {table}")
    columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _production_row(
    con: duckdb.DuckDBPyConnection, field_npdid: int, year: int, month: int
) -> dict[str, object]:
    """Return the single ``monthly_production`` row for a composite key, as a column-keyed dict."""
    cur = con.execute(
        "SELECT * FROM monthly_production "
        "WHERE field_npdid = ? AND year = ? AND month = ?",
        [field_npdid, year, month],
    )
    columns = [d[0] for d in cur.description]
    rows = cur.fetchall()
    assert len(rows) == 1, (
        f"expected exactly one production row for "
        f"(field_npdid={field_npdid}, year={year}, month={month}), got {len(rows)}"
    )
    return dict(zip(columns, rows[0]))


def _field_row(
    con: duckdb.DuckDBPyConnection, field_npdid: int
) -> dict[str, object]:
    """Return the single ``field`` row for a NPDID, as a column-keyed dict."""
    cur = con.execute("SELECT * FROM field WHERE field_npdid = ?", [field_npdid])
    columns = [d[0] for d in cur.description]
    rows = cur.fetchall()
    assert len(rows) == 1, (
        f"expected exactly one field row for field_npdid={field_npdid}, got {len(rows)}"
    )
    return dict(zip(columns, rows[0]))


# A minimal valid MonthlyProduction baseline (real ALPHA 2022-01 values) for the direct-construction
# conformance tests — only the field under test is then overridden to the invalid value.
def _valid_production_kwargs(**overrides: object) -> dict[str, object]:
    base = dict(ALPHA_JAN_2022)
    base.update(overrides)
    return base


# A minimal valid Field baseline (real ALPHA values, POLYGON outline) for the same purpose.
def _valid_field_kwargs(**overrides: object) -> dict[str, object]:
    base = {
        "field_npdid": NPDID_ALPHA,
        "field_name": "ALPHA",
        "current_activity_status": "Producing",
        "hc_type": "OIL",
        "main_area": "North sea",
        "operator": "Alpha Operator AS",
        "discovery_year": 1979,
        "geometry_wkt": "POLYGON ((2.0 60.0, 2.5 60.0, 2.5 60.5, 2.0 60.5, 2.0 60.0))",
    }
    base.update(overrides)
    return base


# =============================================================================== R4 (through-ingest)


def test_r4_every_production_row_reconstructs_into_model(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R4: every persisted production row validates against its ``MonthlyProduction`` model.

    Reconstructing ``MonthlyProduction(**row_dict)`` from each DuckDB row proves the persisted data
    *is* the normalized typed shape (column names and types line up with the contract). If any cell
    were the wrong type, an out-of-range month, or a negative volume, construction would raise.
    """
    ingest(con, good_settings)

    rows = _rows_as_dicts(con, "monthly_production")
    assert len(rows) == EXPECTED_PRODUCTION_ROWS

    models = [MonthlyProduction(**row) for row in rows]
    assert len(models) == EXPECTED_PRODUCTION_ROWS
    for model in models:
        assert isinstance(model, MonthlyProduction)


def test_r4_production_composite_key_is_unique(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R4: ``(field_npdid, year, month)`` is a unique key — no duplicate field-months in a run."""
    ingest(con, good_settings)

    (total, distinct_keys) = con.execute(
        "SELECT count(*), count(DISTINCT (field_npdid, year, month)) "
        "FROM monthly_production"
    ).fetchone()
    assert total == EXPECTED_PRODUCTION_ROWS
    assert total == distinct_keys, (
        "monthly_production has duplicate (field_npdid, year, month) keys: "
        f"{total} rows but only {distinct_keys} distinct composite keys"
    )


def test_r4_column_to_field_mapping_on_known_row(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R4: the SODIR ``prf*`` column → model-field mapping is correct on a known row.

    ALPHA 2022-01 (production_primary.csv) — assert the full mapped record, value by value, so a
    transposed or mislabeled column would fail. (gas=0.940 native billion Sm³ is also the R6
    no-conversion anchor; condensate=0.0 is a real zero, asserted again in R6.)
    """
    ingest(con, good_settings)

    row = _production_row(con, NPDID_ALPHA, 2022, 1)
    model = MonthlyProduction(**row)

    assert model.field_npdid == ALPHA_JAN_2022["field_npdid"]
    assert model.field_name == ALPHA_JAN_2022["field_name"]
    assert model.year == ALPHA_JAN_2022["year"]
    assert model.month == ALPHA_JAN_2022["month"]
    assert model.oil == pytest.approx(ALPHA_JAN_2022["oil"])
    assert model.gas == pytest.approx(ALPHA_JAN_2022["gas"])
    assert model.ngl == pytest.approx(ALPHA_JAN_2022["ngl"])
    assert model.condensate == pytest.approx(ALPHA_JAN_2022["condensate"])
    assert model.oil_equivalents == pytest.approx(ALPHA_JAN_2022["oil_equivalents"])
    assert model.produced_water == pytest.approx(ALPHA_JAN_2022["produced_water"])


# =============================================================================== R5 (through-ingest)


def test_r5_every_field_row_reconstructs_into_model(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R5: every persisted field row validates against its ``Field`` model."""
    ingest(con, good_settings)

    rows = _rows_as_dicts(con, "field")
    assert len(rows) == EXPECTED_FIELD_ROWS

    models = [Field(**row) for row in rows]
    assert len(models) == EXPECTED_FIELD_ROWS
    for model in models:
        assert isinstance(model, Field)


def test_r5_field_npdid_is_unique(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R5: ``field_npdid`` is unique across the ``field`` table (one record per field)."""
    ingest(con, good_settings)

    (total, distinct_keys) = con.execute(
        "SELECT count(*), count(DISTINCT field_npdid) FROM field"
    ).fetchone()
    assert total == EXPECTED_FIELD_ROWS
    assert total == distinct_keys, (
        f"field has duplicate field_npdid keys: {total} rows but {distinct_keys} distinct NPDIDs"
    )


def test_r5_descriptive_attribute_mapping_including_sodir_misspelling(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R5: identity + descriptive attributes map correctly, incl. SODIR's misspelled columns.

    GAMMA/1003 — assert the whole mapped record. The load-bearing pair is the SODIR-spelled source
    columns: ``fldCurrentActivitySatus`` → ``current_activity_status`` ("Shut down") and
    ``cmpLongName`` → ``operator`` ("Gamma Operator AS"). (GAMMA's null outline is asserted in R7.)
    """
    ingest(con, good_settings)

    row = _field_row(con, NPDID_GAMMA)
    model = Field(**row)

    assert model.field_npdid == GAMMA_FIELD["field_npdid"]
    assert model.field_name == GAMMA_FIELD["field_name"]
    assert model.current_activity_status == GAMMA_FIELD["current_activity_status"]
    assert model.hc_type == GAMMA_FIELD["hc_type"]
    assert model.main_area == GAMMA_FIELD["main_area"]
    assert model.operator == GAMMA_FIELD["operator"]
    assert model.discovery_year == GAMMA_FIELD["discovery_year"]
    assert model.geometry_wkt == GAMMA_FIELD["geometry_wkt"]


# =============================================================================== R6 (through-ingest)


def test_r6_absent_volume_is_null_not_zero(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R6 (the crux): an absent source cell becomes ``None``, while a real ``0`` stays ``0.0``.

    GAMMA 2022-06 (production_primary.csv) is the discriminating row: ``prfPrdOilNetMillSm3`` is the
    literal ``0.0`` (a real zero-production month → kept ``0.0``) while ``prfPrdNGLNetMillSm3`` and
    ``prfPrdCondensateNetMillSm3`` are **empty** cells (absent → ``None``, NOT coerced to ``0.0``).
    Both halves are asserted explicitly because conflating them is exactly the R6 failure mode.
    """
    ingest(con, good_settings)

    june = _production_row(con, NPDID_GAMMA, 2022, 6)

    # Real zero-production month: oil (and the other present streams) is the literal 0.0, NOT null.
    assert june["oil"] == 0.0
    assert june["oil"] is not None
    assert june["gas"] == 0.0
    assert june["oil_equivalents"] == 0.0
    assert june["produced_water"] == 0.0

    # Absent cells: normalized to NULL → Python None, and explicitly NOT the number 0.0.
    assert june["ngl"] is None, f"absent NGL must normalize to None, got {june['ngl']!r}"
    assert june["condensate"] is None, (
        f"absent condensate must normalize to None, got {june['condensate']!r}"
    )

    # Round-trip through the model keeps the same None-vs-0.0 distinction.
    model = MonthlyProduction(**june)
    assert model.oil == 0.0
    assert model.ngl is None
    assert model.condensate is None


def test_r6_absent_volume_is_null_on_second_gamma_row(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R6: the absent NGL/condensate cells stay ``None`` on a row whose other streams are nonzero.

    GAMMA 2022-07 has present, non-zero oil/gas/oe/water (0.012 / 0.030 / 0.045 / 0.005) but the same
    two empty cells — proving the absent→null rule is per-cell, not "the whole row is zero".
    """
    ingest(con, good_settings)

    july = _production_row(con, NPDID_GAMMA, 2022, 7)

    assert july["oil"] == pytest.approx(0.012)
    assert july["gas"] == pytest.approx(0.030)
    assert july["oil_equivalents"] == pytest.approx(0.045)
    assert july["produced_water"] == pytest.approx(0.005)

    assert july["ngl"] is None
    assert july["condensate"] is None


def test_r6_units_are_native_no_conversion(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R6: volumes are carried in their SODIR-native unit — no scaling applied.

    ALPHA 2022-01 stores ``gas == 0.940`` (billion Sm³, the raw cell) — *not* multiplied to million
    Sm³ (which would read ~940) — and ``oil == 1.180`` (million Sm³, the raw cell). Equality to the
    unchanged fixture values is the proof that gas stays billion-Sm³ and liquids stay million-Sm³.
    """
    ingest(con, good_settings)

    row = _production_row(con, NPDID_ALPHA, 2022, 1)

    # Gas: native billion Sm³, byte-for-byte the source cell — emphatically not the million-scaled ~940.
    assert row["gas"] == pytest.approx(0.940)
    assert row["gas"] < 1.0, (
        f"gas must stay native billion Sm³ (0.940), not scaled to million; got {row['gas']!r}"
    )
    # A liquid stream: native million Sm³, unchanged.
    assert row["oil"] == pytest.approx(1.180)


def test_r6_all_volumes_non_negative(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R6: every non-null volume across all six streams is ``>= 0`` after normalization."""
    ingest(con, good_settings)

    streams = ("oil", "gas", "ngl", "condensate", "oil_equivalents", "produced_water")
    for row in _rows_as_dicts(con, "monthly_production"):
        for stream in streams:
            value = row[stream]
            if value is not None:
                assert value >= 0, (
                    f"negative {stream}={value!r} for "
                    f"(field_npdid={row['field_npdid']}, year={row['year']}, month={row['month']})"
                )


# =============================================================================== R7 (through-ingest)


def test_r7_outlines_parse_as_polygon_or_multipolygon(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R7: every non-null ``geometry_wkt`` parses with shapely as polygon/multipolygon.

    Across the field set: 1001 (ALPHA) is a POLYGON and 1002 (BETA) is a MULTIPOLYGON, so the sweep
    sees both geom types; each parsed outline's ``geom_type`` must be in {Polygon, MultiPolygon}.
    """
    ingest(con, good_settings)

    rows = con.execute(
        "SELECT field_npdid, geometry_wkt FROM field WHERE geometry_wkt IS NOT NULL"
    ).fetchall()
    assert rows, "expected at least one field to carry a non-null outline (R7)"

    seen_types: set[str] = set()
    for field_npdid, wkt_text in rows:
        geom: BaseGeometry = shapely_wkt.loads(wkt_text)
        assert geom.geom_type in {"Polygon", "MultiPolygon"}, (
            f"field {field_npdid} outline is {geom.geom_type}, not Polygon/MultiPolygon"
        )
        seen_types.add(geom.geom_type)

    # The canonical sample carries one of each, so the suite proves both branches of R7.
    assert seen_types == {"Polygon", "MultiPolygon"}, (
        f"expected both Polygon and MultiPolygon in the fixture set, saw {seen_types}"
    )


def test_r7_specific_geometry_types_per_field(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R7: the per-field outline type is exactly as published (1001 Polygon, 1002 MultiPolygon)."""
    ingest(con, good_settings)

    alpha = _field_row(con, NPDID_ALPHA)
    beta = _field_row(con, NPDID_BETA)

    assert shapely_wkt.loads(alpha["geometry_wkt"]).geom_type == "Polygon"
    assert shapely_wkt.loads(beta["geometry_wkt"]).geom_type == "MultiPolygon"


def test_r7_null_outline_where_sodir_publishes_none(
    con: duckdb.DuckDBPyConnection, good_settings: object
) -> None:
    """001-R7: a field with no published outline carries ``geometry_wkt IS NULL`` (GAMMA/1003)."""
    ingest(con, good_settings)

    gamma = _field_row(con, NPDID_GAMMA)
    assert gamma["geometry_wkt"] is None, (
        f"GAMMA/1003 has no SODIR outline → geometry_wkt must be None, got {gamma['geometry_wkt']!r}"
    )


# ================================================================= Direct contract conformance =====
# The all-valid fixtures can't exercise the contract's *rejection* guarantees, so assert them by
# constructing the frozen models directly (acceptance of the frozen contract's R4/R6/R7 promises).
# Baselines come from real fixture values so each construction is minimal and only the field under
# test is invalid. Per the task's hard boundary the shared fixtures are NOT given bad rows.


def test_r6_contract_rejects_negative_volume() -> None:
    """001-R6: the contract rejects a negative stream volume (``Field(ge=0)``) at construction."""
    with pytest.raises(ValidationError):
        MonthlyProduction(**_valid_production_kwargs(oil=-1.0))


def test_r6_contract_defaults_absent_stream_to_none() -> None:
    """001-R6: an omitted stream defaults to ``None`` (absent), never ``0.0``.

    Build a record without ngl/condensate/produced_water and confirm those fields are ``None`` (the
    contract's ``= None`` default is the model-level expression of the absent→null rule).
    """
    model = MonthlyProduction(
        field_npdid=NPDID_GAMMA,
        field_name="GAMMA",
        year=2022,
        month=6,
        oil=0.0,
        gas=0.0,
        oil_equivalents=0.0,
        # ngl, condensate, produced_water omitted → must default to None
    )
    assert model.ngl is None
    assert model.condensate is None
    assert model.produced_water is None
    # A supplied real zero remains 0.0 — the default does not turn present zeros into None.
    assert model.oil == 0.0


def test_r4_contract_rejects_month_out_of_range() -> None:
    """001-R4: ``month`` outside 1–12 is rejected by the contract (key integrity)."""
    with pytest.raises(ValidationError):
        MonthlyProduction(**_valid_production_kwargs(month=13))
    with pytest.raises(ValidationError):
        MonthlyProduction(**_valid_production_kwargs(month=0))


def test_r7_contract_rejects_non_polygonal_wkt() -> None:
    """001-R7: a non-null ``geometry_wkt`` shapely can't read as polygon/multipolygon is rejected.

    A LINESTRING and a POINT are valid WKT but the wrong geometry class, so the contract's
    ``geometry_wkt`` validator must reject both.
    """
    with pytest.raises(ValidationError):
        Field(**_valid_field_kwargs(geometry_wkt="LINESTRING (2.0 60.0, 2.5 60.5)"))
    with pytest.raises(ValidationError):
        Field(**_valid_field_kwargs(geometry_wkt="POINT (2.0 60.0)"))


def test_r7_contract_accepts_null_outline() -> None:
    """001-R7: ``geometry_wkt=None`` is accepted (the no-published-outline case)."""
    model = Field(**_valid_field_kwargs(geometry_wkt=None))
    assert model.geometry_wkt is None


def test_r4_r5_models_are_frozen_and_forbid_extra() -> None:
    """001-R4/R5: the contract models are immutable (``frozen``) and reject unknown columns.

    One small check per behavior: an unknown attribute raises at construction (``extra="forbid"`` —
    a stray SODIR column can't silently sneak in), and assignment after construction raises
    (``frozen`` — records are read-only value objects).
    """
    # Unknown field is rejected (extra="forbid").
    with pytest.raises(ValidationError):
        MonthlyProduction(**_valid_production_kwargs(unexpected_column=1.0))
    with pytest.raises(ValidationError):
        Field(**_valid_field_kwargs(unexpected_column="x"))

    # Mutation after construction is rejected (frozen=True). Pydantic v2 raises ValidationError on
    # frozen-instance assignment.
    prod = MonthlyProduction(**_valid_production_kwargs())
    with pytest.raises(ValidationError):
        prod.oil = 2.0  # type: ignore[misc]

    fld = Field(**_valid_field_kwargs())
    with pytest.raises(ValidationError):
        fld.field_name = "RENAMED"  # type: ignore[misc]
