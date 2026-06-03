"""Acceptance suite: read-only API & auto-generated OpenAPI/Swagger — EARS 003-R1, 003-R7 (003-T6).

Black-box over HTTP through the seeded read-only store (``conftest_api.py``). Two requirements plus a
light operational check:

* **003-R7** — "The system SHALL auto-generate its OpenAPI schema and interactive Swagger docs from
  the typed models (never hand-written), reflecting every endpoint and response model." Proven by:
  - ``GET /openapi.json`` -> 200, an OpenAPI document whose ``paths`` include every endpoint
    (``/fields``, ``/fields/{npdid}``, ``/fields/{npdid}/production``, ``/fields/{npdid}/forecast``,
    ``/fields.geojson``) and whose ``components.schemas`` include the response models
    (``FieldListResponse``, ``ProductionHistoryResponse``, ``FieldFeatureCollection``,
    ``ErrorResponse``, and the served frozen ``Field`` / ``FieldForecast``);
  - ``GET /docs`` -> 200 (the Swagger UI HTML).
* **003-R1** — "The system SHALL expose a **read-only** HTTP API over the single DuckDB store ... and
  SHALL NOT mutate the store." Proven by:
  - the OpenAPI ``paths`` declare **no** POST/PUT/PATCH/DELETE operation on any route (the surface is
    GET-only);
  - a write request (e.g. ``POST /fields``) is rejected (405 Method Not Allowed) — there is no mutate
    route to hit;
  - the store is **unchanged** after a batch of GETs: field count and per-field forecast availability
    observed through the API are identical before and after (no GET silently writes).
* **operational (non-EARS)** — ``GET /health`` -> 200 ``{"status": "ok"}`` (coordinator decision: a
  trivial liveness probe, no DB hit; documented as operational, no EARS trace).

Red until ``ncs.api`` exists and 003-T8 builds the FastAPI app (``response_model=`` on every route is
what makes the schema auto-generate; ``create_app`` registers ``/health`` + CORS). Pins the
*presence* of the auto-generated artifacts and the read-only surface, never how FastAPI renders them.
"""

from __future__ import annotations

import pytest

from conftest_api import (
    CLEAN_POLYGON_NPDID,
    NON_FORECASTABLE_NPDID,
    SEEDED_NPDIDS_SORTED,
)

# Every endpoint the OpenAPI ``paths`` must document (R7). Path-param segments use the OpenAPI
# ``{npdid}`` placeholder, matching how FastAPI templates a typed path param.
EXPECTED_PATHS: tuple[str, ...] = (
    "/fields",
    "/fields/{npdid}",
    "/fields/{npdid}/production",
    "/fields/{npdid}/forecast",
    "/fields.geojson",
)

# The response/served model schemas the auto-generated components must include (R7). These are the
# 003 envelopes + the served frozen 001/002 models — FastAPI names a component after the model class.
EXPECTED_SCHEMAS: tuple[str, ...] = (
    "FieldListResponse",
    "ProductionHistoryResponse",
    "FieldFeatureCollection",
    "ErrorResponse",
    "Field",            # served frozen 001 model (detail + list items)
    "FieldForecast",    # served frozen 002 model (forecast endpoint)
)

# The HTTP methods that would mutate the store — R1 forbids all of them on every route.
MUTATING_METHODS: tuple[str, ...] = ("post", "put", "patch", "delete")


# ============================================================ R7 — auto-generated OpenAPI ==========


def test_r7_openapi_json_is_served(client) -> None:
    """003-R7: ``GET /openapi.json`` returns 200 with a parseable OpenAPI document (``openapi`` + paths).

    FastAPI auto-generates the schema; the endpoint exists and returns a document with the top-level
    ``openapi`` version string and a ``paths`` object — the contract 004 generates its client against.
    """
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "openapi" in schema, "the OpenAPI document must declare its ``openapi`` version (R7)"
    assert "paths" in schema and schema["paths"], "the OpenAPI document must list paths (R7)"


def test_r7_openapi_documents_every_endpoint(client) -> None:
    """003-R7: the OpenAPI ``paths`` include every API endpoint (the schema reflects the real surface).

    Each of the five endpoints appears as a key in ``paths`` — so the auto-generated document is
    complete (no route omitted), which is exactly what R7 ("reflecting every endpoint") demands.
    """
    paths = client.get("/openapi.json").json()["paths"]

    for endpoint in EXPECTED_PATHS:
        assert endpoint in paths, f"OpenAPI paths is missing {endpoint!r} (R7: every endpoint)"


def test_r7_openapi_documents_the_response_models(client) -> None:
    """003-R7: the OpenAPI components include the response + served models (the schema is self-describing).

    Because every route sets ``response_model=`` (plan.md §Endpoints), FastAPI emits each model into
    ``components.schemas``. The envelopes and the served frozen ``Field`` / ``FieldForecast`` must all
    be present — so 004 generates a typed client off the *real* schemas, not a hand-maintained copy.
    """
    schema = client.get("/openapi.json").json()
    components = schema.get("components", {}).get("schemas", {})

    for model_name in EXPECTED_SCHEMAS:
        assert model_name in components, (
            f"OpenAPI components.schemas is missing {model_name!r} (R7: every response model)"
        )


def test_r7_swagger_docs_are_served(client) -> None:
    """003-R7: ``GET /docs`` returns 200 — the interactive Swagger UI exists.

    The Swagger UI is FastAPI's auto-generated interactive docs (HTML referencing the schema). R7
    requires it to exist; assert a 200 and that the body is HTML (the UI page, not JSON).
    """
    response = client.get("/docs")

    assert response.status_code == 200
    content_type = response.headers.get("content-type", "")
    assert "text/html" in content_type, "/docs must serve the Swagger UI HTML page (R7)"


# ============================================================ R1 — read-only surface ===============


def test_r1_openapi_declares_no_mutating_operation(client) -> None:
    """003-R1: no path in the OpenAPI document declares a POST/PUT/PATCH/DELETE operation.

    The structural read-only guarantee at the schema level: every documented path exposes only
    safe (GET/HEAD/OPTIONS) operations — there is no write/mutate operation anywhere in the surface
    (plan.md §Endpoints: "the app exposes no POST/PUT/PATCH/DELETE"). Iterates every path so a stray
    mutating route is caught wherever it hides.
    """
    paths = client.get("/openapi.json").json()["paths"]

    offending: list[str] = []
    for path, operations in paths.items():
        for method in MUTATING_METHODS:
            if method in operations:
                offending.append(f"{method.upper()} {path}")
    assert not offending, f"read-only API must declare no mutating operations (R1); found {offending}"


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_r1_write_requests_are_rejected(client, method: str) -> None:
    """003-R1: a write request to a read endpoint is rejected (405) — there is no mutate route.

    Hitting ``/fields`` with each mutating verb returns 405 Method Not Allowed (the path exists only
    for GET), confirming the surface offers no way to mutate the store over HTTP. A 2xx here would
    mean a write route slipped in.
    """
    response = client.request(method, "/fields")
    assert response.status_code == 405, (
        f"{method.upper()} /fields must be 405 on a read-only API (R1), got {response.status_code}"
    )


def test_r1_store_is_unchanged_after_a_batch_of_gets(client) -> None:
    """003-R1: the store is unchanged after a batch of GETs — observable counts identical before/after.

    The "SHALL NOT mutate the store" bar, observed black-box: snapshot the field count and the
    forecast-availability of a forecastable and a non-forecastable field, hammer every read endpoint,
    then snapshot again — the two snapshots are identical. A GET that silently wrote (e.g. an upsert
    on read) would shift a count or flip an availability.
    """

    def snapshot() -> tuple[int, int, int]:
        field_count = client.get("/fields").json()["count"]
        forecastable = client.get(f"/fields/{CLEAN_POLYGON_NPDID}/forecast").status_code
        non_forecastable = client.get(f"/fields/{NON_FORECASTABLE_NPDID}/forecast").status_code
        return field_count, forecastable, non_forecastable

    before = snapshot()

    # A batch of reads across every endpoint (the kind of traffic 004 generates).
    for npdid in SEEDED_NPDIDS_SORTED:
        client.get(f"/fields/{npdid}")
        client.get(f"/fields/{npdid}/production")
        client.get(f"/fields/{npdid}/forecast")
    client.get("/fields")
    client.get("/fields.geojson")

    after = snapshot()

    assert before == after, (
        f"a read-only API must leave the store unchanged after GETs (R1); {before} != {after}"
    )


# ============================================================ operational (non-EARS) — /health =====


def test_health_endpoint_is_ok(client) -> None:
    """Operational (non-EARS): ``GET /health`` returns 200 ``{"status": "ok"}`` (coordinator decision).

    A trivial liveness probe the run/verify flow pings — no data, no DB hit. Documented as operational
    (not an EARS requirement), so this is a light check, not an EARS trace.
    """
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
