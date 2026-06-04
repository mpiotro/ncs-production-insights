"""The four read-only GET routers for the 003 API (task 003-T8).

Each module owns one resource and exports a FastAPI ``router``; ``ncs.api.app`` includes all four.
The routers are deliberately **thin** — parse the path param, call the read-only ``store`` (or the
``geojson`` layer), and let ``response_model=`` shape + document the body (R7). They are **GET-only**:
the app exposes no POST/PUT/PATCH/DELETE, so write verbs get 405 (R1).
"""

from __future__ import annotations

from ncs.api.routes import fields, forecast, geojson, production

__all__ = ["fields", "production", "forecast", "geojson"]
