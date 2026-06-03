"""Run configuration for the ingestion pipeline (task 001-T8).

This is the **internal** config object (intentionally *not* part of the frozen contract consumed by
002/003/004 — plan.md open-question 4). It tells ``ingest()`` which sources to try for each dataset
and in what order: the first source that succeeds wins, the rest are the documented R3 fallbacks.

A ``Source`` is a ``(transport, location)`` pair. ``location`` is a filesystem path in the hermetic
acceptance tests and an ``http(s)://`` URL in production; the fetch layer dispatches on which it is.
``Settings`` carries no DuckDB path — the connection is passed to ``ingest(con, settings)`` by the
caller (the DB lifecycle is owned outside config; plan.md, conftest).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ncs.contracts import Transport


class Source(BaseModel):
    """One candidate source for a dataset: a transport plus where to read it from.

    ``location`` is a local filesystem path (hermetic tests) or an ``http(s)://`` URL (production).
    The fetch layer (``ncs.fetch``) decides local-file vs HTTP from the location at retrieval time.
    """

    model_config = ConfigDict(extra="forbid")

    transport: Transport      # Transport.rest | Transport.csv
    location: str             # local fixture path here; a URL in production


class Settings(BaseModel):
    """Ordered sources per dataset — primary first, then documented fallback(s) (R1, R2, R3).

    ``ingest()`` tries each list in order and uses the first source that yields usable rows, so the
    R3 fallback runs automatically when an earlier source fails (plan.md §Sourcing & fallback).
    """

    model_config = ConfigDict(extra="forbid")

    production_sources: list[Source]   # ordered: primary first, then fallback(s)
    field_sources: list[Source]        # ordered: primary first, then fallback(s)
