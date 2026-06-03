"""Normalization — raw column dicts → frozen typed models (T9; R4, R5, R6, R7).

The fetch layer hands every transport the same shape (a list of raw column dicts keyed by SODIR
``prf*`` / ``fld*`` names). This module maps those keys to the contract's model fields and performs
the two coercions the contract can't: numeric parsing and **the absent→null rule (R6)**.

The R6 crux (plan.md §Normalization): an empty / whitespace / missing volume cell becomes ``None``
("SODIR published no value"); a literal ``0`` / ``0.0`` (a real zero-production month) stays
``0.0``. The two are never conflated. Units are carried **native** — no conversion (gas billion
Sm³, the liquids million Sm³). Geometry is carried as the WKT string (or ``None``); the contract's
``field_validator`` does the R7 shapely polygon/multipolygon check at model construction.
"""

from __future__ import annotations

from collections.abc import Mapping

from ncs.contracts import Field, MonthlyProduction

# --- SODIR column → model field maps (the single place each source column name lives) ------------

# Production: prf* columns → MonthlyProduction fields (contracts.md, fixtures README).
_PRODUCTION_STREAM_COLUMNS = {
    "oil": "prfPrdOilNetMillSm3",
    "gas": "prfPrdGasNetBillSm3",
    "ngl": "prfPrdNGLNetMillSm3",
    "condensate": "prfPrdCondensateNetMillSm3",
    "oil_equivalents": "prfPrdOeNetMillSm3",
    "produced_water": "prfPrdProducedWaterInFieldMillSm3",
}

# Field: fld* / cmpLongName columns → Field fields. Includes SODIR's misspelled
# ``fldCurrentActivitySatus`` (kept verbatim, the one place that spelling lives) and ``cmpLongName``.
_FIELD_TEXT_COLUMNS = {
    "current_activity_status": "fldCurrentActivitySatus",
    "hc_type": "fldHcType",
    "main_area": "fldMainArea",
    "operator": "cmpLongName",
}


def _is_absent(value: object) -> bool:
    """True when a raw cell carries **no value** → maps to ``None`` (R6).

    Absent means: the key was missing, the value is JSON ``null`` (Python ``None``), or — the CSV
    case — a string that is empty or whitespace-only. A literal ``0`` / ``"0"`` / ``"0.0"`` is
    **present** (a real value), so this returns ``False`` for it: that is the whole point of R6.
    """
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _to_float_or_none(value: object) -> float | None:
    """Coerce a raw volume cell to ``float``, or ``None`` when the cell is absent (R6).

    Absent (empty/whitespace/missing) → ``None``; otherwise parse to ``float`` (SODIR decimals use
    ``.``; surrounding whitespace is trimmed). A real ``0`` / ``0.0`` parses to ``0.0`` and is kept
    — distinct from the ``None`` an absent cell produces. A non-numeric present value raises
    ``ValueError`` (surfaced, never silently dropped).
    """
    if _is_absent(value):
        return None
    if isinstance(value, bool):  # guard: bool is an int subclass; treat as malformed, not 0/1
        raise ValueError(f"expected a numeric volume, got bool {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value).strip())


def _to_int(value: object) -> int:
    """Coerce a required identifier/date cell (npdid, year, month) to ``int``.

    Trims whitespace and tolerates an integral float string (``"2022"`` / ``2022.0``). A truly
    absent required cell raises — these columns are non-nullable in the contract, so a missing one
    is an error to surface, not a silent skip.
    """
    if _is_absent(value):
        raise ValueError("required integer column is absent")
    if isinstance(value, bool):
        raise ValueError(f"expected an integer, got bool {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return int(float(str(value).strip()))


def _to_int_or_none(value: object) -> int | None:
    """Coerce an optional integer cell (``discovery_year``) to ``int``, or ``None`` when absent."""
    if _is_absent(value):
        return None
    return _to_int(value)


def _to_str(value: object) -> str:
    """Coerce a required text cell (a name) to a trimmed ``str``; absent raises (non-nullable)."""
    if _is_absent(value):
        raise ValueError("required text column is absent")
    return str(value).strip()


def _to_str_or_none(value: object) -> str | None:
    """Coerce an optional text cell to a trimmed ``str``, or ``None`` when the cell is absent."""
    if _is_absent(value):
        return None
    return str(value).strip()


def normalize_production(raw_rows: list[Mapping[str, object]]) -> list[MonthlyProduction]:
    """Map raw production column dicts → ``MonthlyProduction`` models (R4, R6).

    Per row: identity/date columns → ``int``, each of the six stream volumes → ``float`` or ``None``
    via the absent→null rule. The model construction then enforces ``month`` in 1–12 and every
    non-null volume ``>= 0`` (R4/R6); a violation raises at construction and is surfaced.
    """
    models: list[MonthlyProduction] = []
    for row in raw_rows:
        kwargs: dict[str, object] = {
            "field_npdid": _to_int(row.get("prfNpdidInformationCarrier")),
            "field_name": _to_str(row.get("prfInformationCarrier")),
            "year": _to_int(row.get("prfYear")),
            "month": _to_int(row.get("prfMonth")),
        }
        for field_name, column in _PRODUCTION_STREAM_COLUMNS.items():
            kwargs[field_name] = _to_float_or_none(row.get(column))
        models.append(MonthlyProduction(**kwargs))
    return models


def normalize_fields(raw_rows: list[Mapping[str, object]]) -> list[Field]:
    """Map raw field column dicts → ``Field`` models (R5, R7).

    Identity columns → ``int`` / ``str``; descriptive attributes → ``str | None`` (incl. the
    SODIR-spelled ``fldCurrentActivitySatus`` → ``current_activity_status`` and ``cmpLongName`` →
    ``operator``); ``discovery_year`` → ``int | None``. ``geometry_wkt`` is carried as the raw WKT
    string (or ``None`` where SODIR publishes none); the contract validator runs the R7 shapely
    polygon/multipolygon check at construction.
    """
    models: list[Field] = []
    for row in raw_rows:
        kwargs: dict[str, object] = {
            "field_npdid": _to_int(row.get("fldNpdidField")),
            "field_name": _to_str(row.get("fldName")),
            "discovery_year": _to_int_or_none(row.get("fldDiscoveryYear")),
            "geometry_wkt": _to_str_or_none(row.get("geometry_wkt")),
        }
        for field_name, column in _FIELD_TEXT_COLUMNS.items():
            kwargs[field_name] = _to_str_or_none(row.get(column))
        models.append(Field(**kwargs))
    return models
