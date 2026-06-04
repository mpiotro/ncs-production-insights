"""Store-read errors + the 404 handler that maps them to a typed body (task 003-T7; R6, R4).

The store layer raises one of two domain exceptions; ``create_app`` registers
:func:`not_found_handler` for both, so each maps to **HTTP 404** with an :class:`ErrorResponse`
whose ``code`` tells the two conditions apart (the distinctness R4 demands):

* :class:`FieldNotFoundError` -> ``code = field_not_found`` — no such NPDID in the ``field`` table
  (R6);
* :class:`ForecastNotAvailableError` -> ``code = forecast_not_available`` — the field **exists** but
  has no ``field_forecast`` row (< 60 months of history, R4 / 002-R5).

Keeping the HTTP mapping in one handler (rather than scattering ``HTTPException(404, ...)`` through
the routers) means the routes stay thin — they just call the store and let the raised exception
shape the response — and there is exactly one place that builds the typed error body.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from ncs.api.responses import ErrorCode, ErrorResponse


class NotFoundError(Exception):
    """Base for the two 404 conditions — carries the typed ``code`` and the offending NPDID.

    Subclasses fix the ``code``; the message echoes the NPDID so :class:`ErrorResponse.detail`
    can surface it (contracts.md: "echoes the offending npdid"). A common base lets one handler
    catch both while each subclass keeps its distinct code.
    """

    code: ErrorCode

    def __init__(self, npdid: int, detail: str) -> None:
        super().__init__(detail)
        self.npdid = npdid
        self.detail = detail


class FieldNotFoundError(NotFoundError):
    """No ``field`` row for the requested NPDID — the unknown-field 404 (R6)."""

    code = ErrorCode.field_not_found

    def __init__(self, npdid: int) -> None:
        super().__init__(npdid, f"No field with NPDID {npdid}")


class ForecastNotAvailableError(NotFoundError):
    """The field exists but has no forecast (insufficient history) — the distinct 404 (R4)."""

    code = ErrorCode.forecast_not_available

    def __init__(self, npdid: int) -> None:
        super().__init__(
            npdid,
            f"No forecast available for field {npdid} (insufficient history)",
        )


def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    """Map a :class:`NotFoundError` to HTTP 404 + a typed :class:`ErrorResponse` body (R6, R4).

    The exception's ``code`` (``field_not_found`` vs ``forecast_not_available``) carries straight into
    the body, so the two 404s are distinguishable by ``code`` — never by prose (R4). Registered for
    the :class:`NotFoundError` base in ``create_app``, so both subclasses route through it.
    """
    body = ErrorResponse(code=exc.code, detail=exc.detail)
    return JSONResponse(status_code=404, content=body.model_dump(mode="json"))
