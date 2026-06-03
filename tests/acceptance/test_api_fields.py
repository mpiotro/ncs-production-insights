"""Acceptance suite: field list & detail, unknown NPDID -> 404 — EARS 003-R2, 003-R6 (task 003-T2).

Black-box over HTTP through the FastAPI app (``create_app()`` + ``TestClient``) with the
``get_connection`` dependency overridden to a **hermetically seeded**, read-only DuckDB store (see
``conftest_api.py``). The store holds the four pinned ``SEEDED_FIELDS``; this suite asserts the list
and detail endpoints serve every persisted field with its descriptive attributes, and that an unknown
NPDID is a typed 404.

* **003-R2** — "WHEN a client requests the field list, the system SHALL return every persisted field
  with its identity and descriptive attributes (npdid, name, current activity status, hc_type,
  main_area, operator, discovery_year)." Proven by ``GET /fields`` (every seeded field + attrs, count
  matches) and ``GET /fields/{npdid}`` (the frozen ``Field``, attributes equal to what was seeded —
  including a field whose descriptive attributes are ``None``).
* **003-R6** — "IF a client requests a field NPDID not present in the store, THEN the system SHALL
  respond HTTP 404 with a typed error body." Proven by ``GET /fields/{UNKNOWN_NPDID}`` -> 404 +
  ``ErrorResponse`` whose ``code == "field_not_found"`` — the unknown-field 404 that T4 contrasts with
  the *forecast-not-available* 404.

Red until the developer scaffolds ``ncs.api`` (+ ``fastapi``, 003-T1) and implements the response /
store layers + routes (003-T7/T8): the ``client`` fixture imports ``ncs.api``, which does not exist
yet — the correct TDD failure. Assertions pin the served **values** (the contract bar), never the SQL
or router mechanism.
"""

from __future__ import annotations

import pytest

from conftest_api import (
    NULL_GEOMETRY_NPDID,
    SEEDED_FIELD_COUNT,
    SEEDED_FIELDS,
    SEEDED_NPDIDS_SORTED,
    UNKNOWN_NPDID,
)

# The descriptive attributes R2 names explicitly (npdid + these). Asserted field-by-field so a missing
# or renamed attribute on the served Field fails loudly.
R2_DESCRIPTIVE_ATTRS: tuple[str, ...] = (
    "field_name",
    "current_activity_status",
    "hc_type",
    "main_area",
    "operator",
    "discovery_year",
)


# ============================================================ R2 — the field list =================


def test_r2_list_fields_returns_200_and_field_list_response(client) -> None:
    """003-R2: ``GET /fields`` returns 200 with a ``FieldListResponse``-shaped body (count + fields).

    The envelope (``count`` + ``fields``) is the 003 list wrapper (contracts.md §List envelopes); the
    body validates against ``FieldListResponse`` so a malformed shape fails here, not silently in 004.
    """
    from ncs.api.responses import FieldListResponse

    response = client.get("/fields")

    assert response.status_code == 200
    payload = FieldListResponse.model_validate(response.json())  # shape is the contract envelope
    assert payload.count == SEEDED_FIELD_COUNT
    assert len(payload.fields) == SEEDED_FIELD_COUNT


def test_r2_list_fields_includes_every_seeded_field(client) -> None:
    """003-R2: the list contains exactly the persisted fields — every seeded NPDID, no more, no fewer.

    "Return every persisted field": the served NPDID set equals the seeded set, and the count echoes
    it. Catches both a dropped field and a stray one.
    """
    response = client.get("/fields")
    assert response.status_code == 200
    body = response.json()

    served_npdids = {f["field_npdid"] for f in body["fields"]}
    assert served_npdids == set(SEEDED_NPDIDS_SORTED)
    assert body["count"] == SEEDED_FIELD_COUNT


def test_r2_list_fields_is_ordered_by_npdid(client) -> None:
    """003-R2 (coordinator decision): ``/fields`` is ordered by ``field_npdid`` (stable, deterministic).

    The plan fixes the list order to ``field_npdid`` ascending so 004 (and these tests) get a
    deterministic sequence; assert the served order equals the sorted seeded NPDIDs.
    """
    response = client.get("/fields")
    assert response.status_code == 200

    served_order = [f["field_npdid"] for f in response.json()["fields"]]
    assert served_order == list(SEEDED_NPDIDS_SORTED)


def test_r2_list_fields_carries_descriptive_attributes(client) -> None:
    """003-R2: each listed field carries its identity **and** descriptive attributes, as persisted.

    R2 names the attribute set explicitly (name, current_activity_status, hc_type, main_area,
    operator, discovery_year). For every seeded field we assert each attribute on the served row
    equals what we seeded — so a field served with the right NPDID but blank/garbled attributes fails.
    """
    response = client.get("/fields")
    assert response.status_code == 200

    served = {f["field_npdid"]: f for f in response.json()["fields"]}
    for npdid in SEEDED_NPDIDS_SORTED:
        row = served[npdid]
        expected = SEEDED_FIELDS[npdid]
        for attr in R2_DESCRIPTIVE_ATTRS:
            assert row[attr] == expected[attr], (
                f"field {npdid} served {attr}={row[attr]!r}, seeded {expected[attr]!r} (R2)"
            )


# ============================================================ R2 — the field detail ===============


@pytest.mark.parametrize("npdid", SEEDED_NPDIDS_SORTED)
def test_r2_get_field_returns_the_seeded_field(client, npdid: int) -> None:
    """003-R2: ``GET /fields/{npdid}`` returns 200 with the frozen ``Field``, attributes as seeded.

    The detail endpoint returns the bare frozen ``Field`` (no envelope — a single resource needs no
    ``count``, contracts.md). Parametrized over every seeded field, including ``NULL_GEOMETRY`` whose
    descriptive attributes are ``None`` — proving null Field attributes survive the round-trip as JSON
    ``null`` (not dropped, not coerced).
    """
    from ncs.contracts import Field

    response = client.get(f"/fields/{npdid}")

    assert response.status_code == 200
    body = response.json()
    field = Field.model_validate(body)  # validates against the frozen 001 contract

    assert field.field_npdid == npdid
    expected = SEEDED_FIELDS[npdid]
    for attr in R2_DESCRIPTIVE_ATTRS:
        assert getattr(field, attr) == expected[attr], (
            f"detail for {npdid} served {attr}={getattr(field, attr)!r}, seeded {expected[attr]!r}"
        )


def test_r2_get_field_with_null_attributes_serialises_them_as_null(client) -> None:
    """003-R2: the null-attribute field serves its ``None`` descriptive fields as JSON ``null``.

    A focused check on ``NULL_GEOMETRY`` (seeded with every descriptive attr ``None``): the raw JSON
    carries ``null`` for those keys — not ``""`` or a missing key — so 004 can tell "SODIR published
    no value" from an empty string.
    """
    response = client.get(f"/fields/{NULL_GEOMETRY_NPDID}")
    assert response.status_code == 200
    body = response.json()

    for attr in ("current_activity_status", "hc_type", "main_area", "operator", "discovery_year"):
        assert attr in body, f"detail must still carry the {attr} key even when null (R2)"
        assert body[attr] is None, f"{attr} must serialise as JSON null, got {body[attr]!r} (R2)"


# ============================================================ R6 — unknown NPDID -> typed 404 ======


def test_r6_unknown_field_returns_404(client) -> None:
    """003-R6: an NPDID absent from the store yields HTTP 404 (not 200-with-empty, not 500)."""
    response = client.get(f"/fields/{UNKNOWN_NPDID}")
    assert response.status_code == 404


def test_r6_unknown_field_returns_typed_field_not_found_error(client) -> None:
    """003-R6: the 404 body is a typed ``ErrorResponse`` whose ``code == "field_not_found"``.

    The typed error shape (contracts.md §Error body) is what 004 parses; ``code`` is the machine-
    readable reason. ``field_not_found`` is the **distinct** code for "no such field" — T4 asserts the
    sibling ``forecast_not_available`` so the two 404s are told apart by ``code``, never by prose.
    """
    from ncs.api.responses import ErrorCode, ErrorResponse

    response = client.get(f"/fields/{UNKNOWN_NPDID}")
    assert response.status_code == 404

    error = ErrorResponse.model_validate(response.json())
    assert error.code == ErrorCode.field_not_found
    # The detail echoes the offending NPDID (contracts.md: "echoes the offending npdid").
    assert str(UNKNOWN_NPDID) in error.detail


def test_r6_non_integer_npdid_is_422(client) -> None:
    """003-R6 boundary: a non-integer NPDID path param is a 422 (FastAPI int coercion), not a 404.

    ``npdid`` is typed ``int`` on the route, so FastAPI rejects a non-numeric segment with 422
    (validation) before the store is touched — distinct from the 404 an *unknown but well-formed*
    NPDID gets. Pins that the path param stays ``int``-typed (plan.md §Endpoints).
    """
    response = client.get("/fields/not-an-integer")
    assert response.status_code == 422
