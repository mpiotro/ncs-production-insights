"""Per-field monthly production route (task 003-T8; R3, R6).

``GET /fields/{npdid}/production`` returns a field's **full** ``MonthlyProduction`` history in a
``ProductionHistoryResponse`` envelope (``field_npdid`` echoes the path param, ``count``, and the
ordered ``production`` list). The store orders ``(year, month)`` in SQL and preserves nulls (a JSON
``null`` stream is distinct from a real ``0.0`` — R3, mirroring 001-R6). An unknown NPDID is the
shared typed 404 (``field_not_found``, R6). GET only.
"""

from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends

from ncs.api import store
from ncs.api.deps import get_connection
from ncs.api.responses import ErrorResponse, ProductionHistoryResponse

router = APIRouter(tags=["production"])


@router.get(
    "/fields/{npdid}/production",
    response_model=ProductionHistoryResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_production(
    npdid: int,
    con: duckdb.DuckDBPyConnection = Depends(get_connection),
) -> ProductionHistoryResponse:
    """Return a field's full monthly history, ordered (year, month), nulls preserved (003-R3, R6)."""
    production = store.get_production(con, npdid)
    return ProductionHistoryResponse(
        field_npdid=npdid,
        count=len(production),
        production=production,
    )
