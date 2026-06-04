"""Field list + detail routes (task 003-T8; R2, R6).

* ``GET /fields`` — every persisted field in a ``FieldListResponse`` (count + items), ordered by
  ``field_npdid`` (R2).
* ``GET /fields/{npdid}`` — that field's frozen ``Field`` directly (no envelope); a 404 +
  ``ErrorResponse(field_not_found)`` when the NPDID is absent (R6).

Both are ``GET`` only. ``npdid`` is typed ``int`` so FastAPI 422s a non-integer path segment before
the store is touched. The store raises ``FieldNotFoundError`` for an unknown NPDID; the app-level
handler maps it to the typed 404 (``responses={404: ...}`` documents that for R7).
"""

from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends

from ncs.api import store
from ncs.api.deps import get_connection
from ncs.api.responses import ErrorResponse, FieldListResponse
from ncs.contracts import Field

router = APIRouter(tags=["fields"])


@router.get("/fields", response_model=FieldListResponse)
def list_fields(
    con: duckdb.DuckDBPyConnection = Depends(get_connection),
) -> FieldListResponse:
    """Return every persisted field with its descriptive attributes (003-R2)."""
    fields = store.list_fields(con)
    return FieldListResponse(count=len(fields), fields=fields)


@router.get(
    "/fields/{npdid}",
    response_model=Field,
    responses={404: {"model": ErrorResponse}},
)
def get_field(
    npdid: int,
    con: duckdb.DuckDBPyConnection = Depends(get_connection),
) -> Field:
    """Return one field's frozen ``Field``; 404 + ``field_not_found`` if the NPDID is absent (003-R2, R6)."""
    return store.get_field(con, npdid)
