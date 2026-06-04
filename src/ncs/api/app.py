"""The FastAPI app factory — ``create_app()`` (task 003-T8; R1, R7).

``create_app()`` builds the read-only API: it includes the four GET routers, registers the
not-found exception handler (the two distinct 404s, R4/R6), adds env-configured CORS so 004
integrates cross-origin, and exposes a trivial ``/health`` liveness probe. FastAPI auto-generates
``/openapi.json`` + ``/docs`` from the ``response_model=`` set on every route — the schema is never
hand-written (R7).

**Why a factory, not a module-level ``app``.** The acceptance suite spins the app over a hermetically
seeded store with the ``get_connection`` dependency overridden (``app.dependency_overrides``); a
factory + injected ``get_connection`` makes that a one-liner and keeps the app free of global state
(R1: read-only, testable). ``uvicorn`` serves ``create_app()`` in production.

The app is **read-only by construction**: only GET routers are mounted (no mutate route anywhere), so
a write verb against any path is 405 (R1) and the OpenAPI surface declares no POST/PUT/PATCH/DELETE.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ncs.api.errors import NotFoundError, not_found_handler
from ncs.api.routes import fields, forecast, geojson, production
from ncs.api.settings import ApiSettings


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    """Build and return the read-only FastAPI app (R1, R7).

    ``settings`` is injectable (defaults to ``ApiSettings.from_env()``) so a test can pin the CORS
    origins without touching the environment. Wires: the four GET routers; the ``NotFoundError`` ->
    typed-404 handler; env-configured ``CORSMiddleware``; and ``GET /health``. No write route is
    registered anywhere, which is what makes the surface read-only (R1).
    """
    settings = settings or ApiSettings.from_env()

    app = FastAPI(
        title="NCS Production Insights API",
        description=(
            "Read-only API over the SODIR-derived DuckDB store: field list/detail, monthly "
            "production, 24-month forecasts, and fields as GeoJSON."
        ),
        version="0.1.0",
    )

    # CORS so 004 (a separate dev origin) can call the API cross-origin (coordinator decision).
    # GET-only surface, no credentials — the methods are limited to the safe read verbs.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    # One handler maps both not-found conditions to 404 + a typed body, told apart by ``code`` (R4/R6).
    app.add_exception_handler(NotFoundError, not_found_handler)

    # The four read-only resource routers (R2–R6). No prefix (coordinator decision): unversioned paths.
    app.include_router(fields.router)
    app.include_router(production.router)
    app.include_router(forecast.router)
    app.include_router(geojson.router)

    @app.get("/health", tags=["meta"], include_in_schema=False)
    def health() -> dict[str, str]:
        """Trivial liveness probe (operational, non-EARS) — no data, no DB hit."""
        return {"status": "ok"}

    return app
