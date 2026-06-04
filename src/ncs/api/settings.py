"""API runtime configuration from the environment (task 003-T7; R1).

``ApiSettings`` carries the read-only DB path, the bind host/port, and the CORS allowed origins —
all from environment variables, **never hard-coded in shared code** (CONTRIBUTING's distinct-port
rule; principle 7: configuration via environment, no secrets). Defaults make local/demo runs
zero-config:

* ``NCS_DB_PATH`` -> ``db_path`` (default ``ncs-003.duckdb`` — gitignored, per-worktree);
* ``API_HOST``   -> ``host``    (default ``127.0.0.1``);
* ``API_PORT``   -> ``port``    (default **8003** — 003's distinct port so it runs beside 004);
* ``API_CORS_ORIGINS`` -> ``cors_origins`` (comma-separated; default the 004 dev origin) so 004
  integrates cross-origin without a 003 change (coordinator decision: minimal env-configured CORS).

This is an **internal** config object (not part of the frozen contract), mirroring 001's
``ncs.config.Settings`` boundary. ``from_env()`` is the single seam ``deps`` / ``app`` read, so a
test can build an explicit ``ApiSettings(...)`` instead of touching ``os.environ``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

# Defaults — pinned here (and overridable via env), never hard-coded at the call sites.
DEFAULT_DB_PATH = "ncs-003.duckdb"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8003  # 003's distinct port (plan.md §Read-only, port, deps); 004 uses another
DEFAULT_CORS_ORIGINS = ("http://localhost:5173",)  # the Vite dev origin 004 serves from


class ApiSettings(BaseModel):
    """Where the API reads its store and how it binds — all env-sourced, with safe defaults (R1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    db_path: str = DEFAULT_DB_PATH
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    cors_origins: list[str] = Field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ApiSettings":
        """Build settings from the environment (``os.environ`` by default), applying the defaults.

        ``environ`` is injectable so a unit test can pass a controlled mapping rather than mutating
        the real process environment. An unset/blank variable falls back to the field default; a set
        ``API_CORS_ORIGINS`` is split on commas (blank entries dropped) into the allowed-origin list.
        """
        env = os.environ if environ is None else environ

        kwargs: dict[str, object] = {}
        db_path = env.get("NCS_DB_PATH")
        if db_path:
            kwargs["db_path"] = db_path
        host = env.get("API_HOST")
        if host:
            kwargs["host"] = host
        port = env.get("API_PORT")
        if port:
            kwargs["port"] = int(port)
        cors = env.get("API_CORS_ORIGINS")
        if cors:
            origins = [origin.strip() for origin in cors.split(",") if origin.strip()]
            if origins:
                kwargs["cors_origins"] = origins

        return cls(**kwargs)
