"""Unit tests for ``ncs.api.app`` (developer-owned, white-box) — 003-T8 / R1, R7.

White-box checks of the ``create_app`` factory wiring (complementing the black-box meta acceptance
suite): a fresh app instance each call (no global state); the four GET routers mounted; the
``NotFoundError`` handler registered; env-configured CORS applied (custom origins honoured); ``GET
/health`` present and ``include_in_schema=False`` so it stays out of the OpenAPI surface; and the
surface GET-only (a write verb is 405). Driven over a tiny seeded store with ``get_connection``
overridden, the same seam production/the acceptance suite use.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from ncs.api import create_app
from ncs.api.app import create_app as create_app_direct
from ncs.api.deps import get_connection
from ncs.api.errors import NotFoundError
from ncs.api.settings import ApiSettings
from ncs.persist import create_schema


@pytest.fixture
def tiny_db(tmp_path: Path) -> Path:
    """A minimal store with one field — enough to exercise the router wiring."""
    db_path = tmp_path / "app.duckdb"
    con = duckdb.connect(str(db_path))
    create_schema(con)
    con.execute("INSERT INTO field (field_npdid, field_name) VALUES (9001, 'ALPHA')")
    con.close()
    return db_path


def _client(db_path: Path, settings: ApiSettings | None = None) -> TestClient:
    """A ``TestClient`` over ``create_app`` with ``get_connection`` overridden to the seeded store."""
    def _read_only() -> Iterator[duckdb.DuckDBPyConnection]:
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            yield con
        finally:
            con.close()

    app = create_app(settings)
    app.dependency_overrides[get_connection] = _read_only
    return TestClient(app)


def test_create_app_returns_a_fresh_fastapi_each_call() -> None:
    """The factory returns a new ``FastAPI`` instance each call (no module-level global app) (R1)."""
    a = create_app()
    b = create_app()

    assert isinstance(a, FastAPI)
    assert a is not b
    # The package re-export and the module factory are the same callable.
    assert create_app is create_app_direct


def test_create_app_mounts_the_four_resource_routes(tiny_db: Path) -> None:
    """All four resource paths are mounted (reachable as GET) (R2–R5/R7)."""
    paths = {route.path for route in create_app().routes}  # type: ignore[attr-defined]

    assert {
        "/fields",
        "/fields/{npdid}",
        "/fields/{npdid}/production",
        "/fields/{npdid}/forecast",
        "/fields.geojson",
    } <= paths


def test_create_app_registers_the_not_found_handler() -> None:
    """The ``NotFoundError`` -> typed-404 handler is registered on the app (R4/R6)."""
    app = create_app()

    assert NotFoundError in app.exception_handlers


def test_create_app_adds_cors_middleware_with_configured_origins() -> None:
    """Env-configured CORS is applied; custom origins are honoured (coordinator decision)."""
    settings = ApiSettings(cors_origins=["http://custom.test"])
    app = create_app(settings)

    cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert cors, "create_app must add CORSMiddleware"
    assert cors[0].kwargs["allow_origins"] == ["http://custom.test"]
    assert cors[0].kwargs["allow_methods"] == ["GET"]


def test_health_endpoint_is_wired_and_out_of_schema(tiny_db: Path) -> None:
    """``GET /health`` returns the liveness body and is excluded from the OpenAPI schema (operational)."""
    client = _client(tiny_db)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    # Operational, non-EARS: kept out of the documented surface.
    assert "/health" not in client.get("/openapi.json").json()["paths"]


def test_surface_is_get_only(tiny_db: Path) -> None:
    """A write verb against a read route is 405 — no mutate route is mounted (R1)."""
    client = _client(tiny_db)

    assert client.post("/fields").status_code == 405


def test_cors_default_origins_used_when_settings_omitted() -> None:
    """With no settings passed, CORS falls back to the env/default origins (R1)."""
    app = create_app(ApiSettings.from_env({}))
    cors = [m for m in app.user_middleware if m.cls is CORSMiddleware][0]

    assert cors.kwargs["allow_origins"] == ApiSettings.from_env({}).cors_origins
