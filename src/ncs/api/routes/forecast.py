"""Per-field forecast route (task 003-T8; R4, R6).

``GET /fields/{npdid}/forecast`` returns the field's frozen ``FieldForecast`` directly on success
(24 points, method, MAPE, credibility). The R4 "insufficient history" case is a **distinct** HTTP
outcome — 404 + ``ErrorResponse(forecast_not_available)`` — never an empty or fabricated forecast;
an unknown NPDID is instead 404 + ``field_not_found`` (R6). The store raises the right exception for
each; the app handler builds the typed body. GET only.
"""

from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends

from ncs.api import store
from ncs.api.deps import get_connection
from ncs.api.responses import ErrorResponse
from ncs.forecast.contracts import FieldForecast

router = APIRouter(tags=["forecast"])


@router.get(
    "/fields/{npdid}/forecast",
    response_model=FieldForecast,
    responses={404: {"model": ErrorResponse}},
)
def get_forecast(
    npdid: int,
    con: duckdb.DuckDBPyConnection = Depends(get_connection),
) -> FieldForecast:
    """Return the field's ``FieldForecast``; 404 distinguishes no-forecast from no-field (003-R4, R6)."""
    return store.get_forecast(con, npdid)
