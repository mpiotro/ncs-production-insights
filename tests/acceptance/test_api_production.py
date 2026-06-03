"""Acceptance suite: per-field monthly production history — EARS 003-R3 (task 003-T3).

Black-box over HTTP through the seeded read-only store (``conftest_api.py``). ``GET
/fields/{npdid}/production`` must return a field's **full** ``MonthlyProduction`` history, **ordered
by (year, month)**, in native units, with **nulls preserved** (a JSON ``null`` stream is distinct
from a real ``0.0``).

* **003-R3** — "WHEN a client requests a field's monthly production, the system SHALL return that
  field's full ``MonthlyProduction`` history (all streams, native units, **nulls preserved**) ordered
  by (year, month)." Proven on the pinned ``PROD_FIELD`` (``CLEAN_POLYGON``):
  - the full history is returned (``count`` == seeded month count; first/last months as seeded);
  - the rows are **ordered by (year, month)** (asserted on the served sequence, not assumed);
  - a **known ``None`` stream cell stays JSON ``null``** and a **known real ``0.0`` cell stays ``0``**
    — the null-vs-zero crux (mirrors 001-R6), asserted on the *raw* JSON so no Pydantic coercion can
    hide a 0/None confusion;
  - and an unknown NPDID is a 404 (R6 reuse on this endpoint).

The probe cells are seeded on non-oe streams (so injecting a real 0.0 doesn't perturb the field's oe
forecast). Red until ``ncs.api`` exists and 003-T7/T8 implement the store read + route. Pins served
**values/order**, never the SQL.
"""

from __future__ import annotations

import pytest

from conftest_api import (
    PROD_FIELD_NPDID,
    PROD_FIRST_CELL,
    PROD_LAST_CELL,
    PROD_NULL_CELL,
    PROD_NULL_STREAM,
    PROD_POSITIVE_STREAM,
    PROD_ZERO_CELL,
    PROD_ZERO_STREAM,
    SEEDED_PRODUCTION_COUNTS,
    UNKNOWN_NPDID,
)

# The six native streams R3 says must all be present on each served row (001 MonthlyProduction).
R3_STREAMS: tuple[str, ...] = (
    "oil",
    "gas",
    "ngl",
    "condensate",
    "oil_equivalents",
    "produced_water",
)


def _production_rows(client) -> list[dict]:
    """GET the probe field's production and return the raw JSON ``production`` list (asserting 200)."""
    response = client.get(f"/fields/{PROD_FIELD_NPDID}/production")
    assert response.status_code == 200, response.text
    return response.json()["production"]


def _cell(rows: list[dict], year_month: tuple[int, int]) -> dict:
    """The single served row at ``(year, month)`` — asserts exactly one exists (no dup/missing)."""
    year, month = year_month
    matches = [r for r in rows if r["year"] == year and r["month"] == month]
    assert len(matches) == 1, f"expected exactly one row for {year}-{month:02d}, got {len(matches)}"
    return matches[0]


# ============================================================ R3 — shape & completeness ============


def test_r3_production_returns_200_and_history_envelope(client) -> None:
    """003-R3: ``GET /fields/{npdid}/production`` is 200 with a ``ProductionHistoryResponse`` envelope.

    The envelope (``field_npdid`` + ``count`` + ``production``) is the 003 history wrapper
    (contracts.md). Validating the body against it pins the shape; ``field_npdid`` echoes the path
    param.
    """
    from ncs.api.responses import ProductionHistoryResponse

    response = client.get(f"/fields/{PROD_FIELD_NPDID}/production")

    assert response.status_code == 200
    payload = ProductionHistoryResponse.model_validate(response.json())
    assert payload.field_npdid == PROD_FIELD_NPDID
    assert payload.count == SEEDED_PRODUCTION_COUNTS[PROD_FIELD_NPDID]
    assert len(payload.production) == SEEDED_PRODUCTION_COUNTS[PROD_FIELD_NPDID]


def test_r3_production_returns_full_history(client) -> None:
    """003-R3: the **full** history is returned — count matches the seeded month count, ends as seeded.

    "Return that field's full history": the served row count equals the months seeded for this field,
    and the first/last calendar months are exactly the anchored endpoints — so nothing is truncated.
    """
    rows = _production_rows(client)

    assert len(rows) == SEEDED_PRODUCTION_COUNTS[PROD_FIELD_NPDID]

    first, last = rows[0], rows[-1]
    assert (first["year"], first["month"]) == PROD_FIRST_CELL
    assert (last["year"], last["month"]) == PROD_LAST_CELL


def test_r3_each_row_carries_all_six_streams(client) -> None:
    """003-R3: every served row exposes all six native streams (present as keys, even when null).

    R3 says "all streams": each row carries oil/gas/ngl/condensate/oil_equivalents/produced_water as
    keys, so a stream that is absent for a month is a JSON ``null`` value — never a missing key.
    """
    rows = _production_rows(client)

    for row in rows:
        for stream in R3_STREAMS:
            assert stream in row, f"served production row is missing the {stream!r} stream key (R3)"


# ============================================================ R3 — ordering by (year, month) =======


def test_r3_production_is_ordered_by_year_then_month(client) -> None:
    """003-R3: the history is ordered by **(year, month)** ascending — asserted on the served sequence.

    The crux ordering guarantee: the served ``(year, month)`` pairs are strictly increasing in
    calendar order. Asserted directly on the response order (not re-sorted), so a store read that
    forgot ``ORDER BY year, month`` is caught.
    """
    rows = _production_rows(client)

    served = [(r["year"], r["month"]) for r in rows]
    assert served == sorted(served), "production must be ordered by (year, month) ascending (R3)"


# ============================================================ R3 — null preserved, distinct from 0 =


def test_r3_null_stream_serialises_as_json_null(client) -> None:
    """003-R3: a known absent stream cell serves as JSON ``null`` — never coerced to ``0.0``.

    The null half of the null-vs-zero crux: at PROD_NULL_CELL the ``gas`` stream was never set
    (``None`` = "SODIR published no value", 001-R6), so the raw JSON value must be ``null``. Asserted
    on raw JSON (``is None``) so a 0-vs-None confusion can't slip through Pydantic.
    """
    rows = _production_rows(client)
    cell = _cell(rows, PROD_NULL_CELL)

    assert cell[PROD_NULL_STREAM] is None, (
        f"{PROD_NULL_STREAM} at {PROD_NULL_CELL} must be JSON null (absent), got {cell[PROD_NULL_STREAM]!r}"
    )


def test_r3_real_zero_stream_serialises_as_zero(client) -> None:
    """003-R3: a known real ``0.0`` measured cell serves as ``0`` — distinct from ``null``.

    The zero half of the crux: at PROD_ZERO_CELL the ``oil`` stream is a genuine measured ``0.0``
    (a real zero-production month), so the served value is ``0.0`` and explicitly **not** ``None`` —
    proving the API distinguishes a real zero from an absent value (001-R6 carried to the API).
    """
    rows = _production_rows(client)
    cell = _cell(rows, PROD_ZERO_CELL)

    assert cell[PROD_ZERO_STREAM] is not None, (
        f"{PROD_ZERO_STREAM} at {PROD_ZERO_CELL} is a real measured 0.0 — must NOT serve as null (R3)"
    )
    assert cell[PROD_ZERO_STREAM] == 0.0, (
        f"{PROD_ZERO_STREAM} at {PROD_ZERO_CELL} must serve as 0.0, got {cell[PROD_ZERO_STREAM]!r} (R3)"
    )


def test_r3_null_and_zero_are_distinct_in_the_same_history(client) -> None:
    """003-R3: within one field's history a ``null`` cell and a ``0.0`` cell are genuinely different.

    The two crux cells side by side: the null-stream cell is ``None`` while the zero-stream cell is
    ``0.0`` — a single assertion that the API never collapses one into the other (the heart of R3).
    """
    rows = _production_rows(client)

    null_value = _cell(rows, PROD_NULL_CELL)[PROD_NULL_STREAM]
    zero_value = _cell(rows, PROD_ZERO_CELL)[PROD_ZERO_STREAM]

    assert null_value is None
    assert zero_value == 0.0
    assert null_value != zero_value  # null ≠ 0.0 (R3)


def test_r3_positive_stream_value_is_preserved(client) -> None:
    """003-R3: a populated stream cell serves its real positive value (native units, not zeroed/nulled).

    The oe stream is filled positive every month by the seed; at the first month it is > 0. Confirms a
    *present* value passes through intact — the counterpart to the null/zero checks (a sanity that the
    endpoint isn't blanking everything).
    """
    rows = _production_rows(client)
    cell = _cell(rows, PROD_FIRST_CELL)

    value = cell[PROD_POSITIVE_STREAM]
    assert value is not None and value > 0.0, (
        f"{PROD_POSITIVE_STREAM} at the first month must be a real positive value, got {value!r} (R3)"
    )


# ============================================================ R6 reuse on this endpoint ============


def test_r3_unknown_field_production_is_404(client) -> None:
    """003-R3/R6: requesting production for an unknown NPDID is a typed 404 (``field_not_found``).

    The production endpoint shares the unknown-field 404 (plan.md §Endpoints: 404 if the field is
    unknown), with the same typed ``field_not_found`` body — so 004 handles "no such field"
    identically across endpoints.
    """
    from ncs.api.responses import ErrorCode, ErrorResponse

    response = client.get(f"/fields/{UNKNOWN_NPDID}/production")

    assert response.status_code == 404
    error = ErrorResponse.model_validate(response.json())
    assert error.code == ErrorCode.field_not_found


@pytest.mark.parametrize(
    "year_month",
    [PROD_FIRST_CELL, PROD_NULL_CELL, PROD_ZERO_CELL, PROD_LAST_CELL],
)
def test_r3_probe_months_are_each_present_exactly_once(
    client, year_month: tuple[int, int]
) -> None:
    """003-R3: each pinned probe month appears exactly once in the served history (no gap/dup).

    Guards that the calendar the null/zero/positive assertions reference is actually in the response
    (and unique), so those crux checks can never silently pass on a missing row.
    """
    rows = _production_rows(client)
    _cell(rows, year_month)  # asserts exactly one match
