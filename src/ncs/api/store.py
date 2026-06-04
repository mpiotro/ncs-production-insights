"""Read-only store queries reconstructing the frozen models (task 003-T7; R2, R3, R4, R6).

The **read** side of the round-trip 001/002 persist: the data tables' columns equal their frozen
model's fields exactly (``persist.py`` derives the DDL from ``Model.model_fields``), so a ``SELECT``
of those columns reconstructs the model under ``extra="forbid"`` — no stray columns. **Every query
here is ``SELECT``-only** (R1); the connection is opened ``read_only=True`` upstream (``deps``), so
this layer cannot mutate the store even by accident.

The two not-found paths (the distinct 404s) are decided **against the ``field`` table**:

* :class:`FieldNotFoundError` — no ``field`` row for the NPDID (``get_field`` / ``get_production`` /
  ``get_forecast``), R6;
* :class:`ForecastNotAvailableError` — the field exists but has no ``field_forecast`` row
  (insufficient history), R4 / 002-R5 — cleanly separable from "no such field".

No 002 import is needed for the insufficient-history decision: the *absence* of a ``field_forecast``
row **is** the signal (002 only persists forecasts for ≥ 60-month fields), so this stays a plain
table read decoupled from 002's run internals.
"""

from __future__ import annotations

import duckdb

from ncs.api.errors import FieldNotFoundError, ForecastNotAvailableError
from ncs.contracts import Field, MonthlyProduction
from ncs.forecast.contracts import FieldForecast, ForecastPoint

# Column tuples taken from the frozen models, exactly as ``persist.py`` derives the table columns —
# so ``SELECT <these> FROM <table>`` returns rows that map 1:1 onto the model fields.
_FIELD_COLUMNS: tuple[str, ...] = tuple(Field.model_fields)
_PRODUCTION_COLUMNS: tuple[str, ...] = tuple(MonthlyProduction.model_fields)

_FIELD_COLUMN_LIST = ", ".join(_FIELD_COLUMNS)
_PRODUCTION_COLUMN_LIST = ", ".join(_PRODUCTION_COLUMNS)

# Forecast parent columns (sans the PK, which we already know) — order matches the reconstruction.
_FORECAST_COLUMNS: tuple[str, ...] = (
    "target",
    "method",
    "backtest_mape",
    "credible",
    "history_months",
)


def _field_exists(con: duckdb.DuckDBPyConnection, npdid: int) -> bool:
    """True iff a ``field`` row exists for ``npdid`` — the existence check both 404s branch on."""
    row = con.execute(
        "SELECT 1 FROM field WHERE field_npdid = ? LIMIT 1", [npdid]
    ).fetchone()
    return row is not None


def list_fields(con: duckdb.DuckDBPyConnection) -> list[Field]:
    """Every persisted ``Field``, ordered by ``field_npdid`` (R2; coordinator decision on order).

    ``SELECT <Field columns> FROM field ORDER BY field_npdid`` → ``Field(**row)`` per row. The
    deterministic NPDID order is the one ``/fields`` (and ``/fields.geojson``) serve, so 004 and the
    acceptance suite get a stable sequence. ``geometry_wkt`` rides along (re-used by the geojson layer).
    """
    rows = con.execute(
        f"SELECT {_FIELD_COLUMN_LIST} FROM field ORDER BY field_npdid"
    ).fetchall()
    return [Field(**dict(zip(_FIELD_COLUMNS, row))) for row in rows]


def get_field(con: duckdb.DuckDBPyConnection, npdid: int) -> Field:
    """One field by NPDID; raise :class:`FieldNotFoundError` if absent (R2 detail, R6).

    A single-row ``SELECT`` reconstructed into the frozen ``Field``. The missing case is the
    unknown-field 404 — raised here so the route stays thin and the handler builds the typed body.
    """
    row = con.execute(
        f"SELECT {_FIELD_COLUMN_LIST} FROM field WHERE field_npdid = ?", [npdid]
    ).fetchone()
    if row is None:
        raise FieldNotFoundError(npdid)
    return Field(**dict(zip(_FIELD_COLUMNS, row)))


def get_production(
    con: duckdb.DuckDBPyConnection, npdid: int
) -> list[MonthlyProduction]:
    """A field's full monthly history, ordered ``(year, month)``; raise if the field is unknown (R3, R6).

    ``ORDER BY year, month`` is done **in SQL** (R3). A DuckDB ``NULL`` stream reads back as Python
    ``None`` and stays ``None`` through Pydantic — **null ≠ 0.0 is preserved end to end** (the crux of
    R3, mirroring 001-R6). Existence is checked against the ``field`` table first, so a known field
    with zero production rows returns an empty history while an *unknown* NPDID is a typed 404 (R6).
    """
    if not _field_exists(con, npdid):
        raise FieldNotFoundError(npdid)
    rows = con.execute(
        f"SELECT {_PRODUCTION_COLUMN_LIST} FROM monthly_production "
        "WHERE field_npdid = ? ORDER BY year, month",
        [npdid],
    ).fetchall()
    return [MonthlyProduction(**dict(zip(_PRODUCTION_COLUMNS, row))) for row in rows]


def get_forecast(con: duckdb.DuckDBPyConnection, npdid: int) -> FieldForecast:
    """The field's persisted ``FieldForecast`` (parent + 24 points); raise the right 404 otherwise (R4).

    Three outcomes, kept distinct:

    * field unknown → :class:`FieldNotFoundError` (R6);
    * field exists but no ``field_forecast`` row (insufficient history) →
      :class:`ForecastNotAvailableError` (R4 / 002-R5) — the *distinct* signal, never an empty forecast;
    * otherwise read the parent row + the 24 points (``ORDER BY year, month``) and assemble the frozen
      ``FieldForecast``. Its ``model_validator`` re-asserts the 24-point and ``credible ⟹ mape < 0.15``
      invariants on reconstruction, so a corrupt store row fails loudly rather than serving a bad forecast.
    """
    if not _field_exists(con, npdid):
        raise FieldNotFoundError(npdid)

    parent = con.execute(
        f"SELECT {', '.join(_FORECAST_COLUMNS)} FROM field_forecast WHERE field_npdid = ?",
        [npdid],
    ).fetchone()
    if parent is None:
        raise ForecastNotAvailableError(npdid)

    point_rows = con.execute(
        "SELECT year, month, value FROM field_forecast_point "
        "WHERE field_npdid = ? ORDER BY year, month",
        [npdid],
    ).fetchall()

    parent_values = dict(zip(_FORECAST_COLUMNS, parent))
    return FieldForecast(
        field_npdid=npdid,
        points=[ForecastPoint(year=y, month=m, value=v) for (y, m, v) in point_rows],
        **parent_values,
    )
