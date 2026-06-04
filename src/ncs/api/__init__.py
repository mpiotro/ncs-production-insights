"""ncs.api — phase 003 read-only FastAPI layer over the single DuckDB store.

The public seam (plan.md §Component shape):

* ``create_app() -> FastAPI`` — the app **factory**: builds the read-only API (four GET routers, the
  typed-404 handler, env-configured CORS, ``/health``), with OpenAPI/Swagger auto-generated from the
  typed response models (R1, R2–R7). ``uvicorn`` serves it in production; the acceptance suite spins
  it over a seeded store with ``get_connection`` overridden.
* ``ncs.api.deps.get_connection`` — the injected read-only DuckDB dependency every route depends on.
* ``ncs.api.responses`` — the response models (envelopes / GeoJSON / typed error) FastAPI serialises.

This package is **purely additive**: it reads the existing 001 (``ncs.*``) / 002 (``ncs.forecast.*``)
tables read-only and never touches those frozen layers. Populating the store is the separate
``ncs.api.seed`` entrypoint — never the API (R1).
"""

from __future__ import annotations

from ncs.api.app import create_app

__all__ = ["create_app"]
