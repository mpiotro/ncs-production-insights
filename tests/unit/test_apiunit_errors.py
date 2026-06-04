"""Unit tests for ``ncs.api.errors`` (developer-owned, white-box) — 003-T7 / R6, R4.

White-box checks of the two domain exceptions and the 404 handler that maps them to a typed body.
Covers: each exception carries its distinct ``code`` and echoes the NPDID in ``detail``; the handler
returns HTTP 404 with a JSON body that validates as ``ErrorResponse`` carrying the exception's code;
and the two codes are distinct (the machine-readable R4 distinctness). The handler is exercised
directly (it is a plain function of a request + the exception) — the app-level wiring is covered by
the meta acceptance suite.
"""

from __future__ import annotations

import json

from ncs.api.errors import (
    FieldNotFoundError,
    ForecastNotAvailableError,
    not_found_handler,
)
from ncs.api.responses import ErrorCode, ErrorResponse


def test_field_not_found_carries_code_and_npdid() -> None:
    """``FieldNotFoundError`` carries the ``field_not_found`` code and echoes the NPDID (R6)."""
    exc = FieldNotFoundError(123)

    assert exc.code == ErrorCode.field_not_found
    assert exc.npdid == 123
    assert "123" in exc.detail


def test_forecast_not_available_carries_code_and_npdid() -> None:
    """``ForecastNotAvailableError`` carries the ``forecast_not_available`` code + NPDID (R4)."""
    exc = ForecastNotAvailableError(456)

    assert exc.code == ErrorCode.forecast_not_available
    assert exc.npdid == 456
    assert "456" in exc.detail


def test_the_two_codes_are_distinct() -> None:
    """The two exceptions' codes differ — the distinctness the two 404s rely on (R4)."""
    assert FieldNotFoundError(1).code != ForecastNotAvailableError(1).code


def test_handler_maps_field_not_found_to_typed_404() -> None:
    """The handler returns 404 + an ``ErrorResponse`` body with the field-not-found code (R6)."""
    response = not_found_handler(request=None, exc=FieldNotFoundError(789))  # type: ignore[arg-type]

    assert response.status_code == 404
    body = ErrorResponse.model_validate(json.loads(response.body))
    assert body.code == ErrorCode.field_not_found
    assert "789" in body.detail


def test_handler_maps_forecast_not_available_to_typed_404() -> None:
    """The handler returns 404 + an ``ErrorResponse`` body with the forecast-not-available code (R4)."""
    response = not_found_handler(request=None, exc=ForecastNotAvailableError(789))  # type: ignore[arg-type]

    assert response.status_code == 404
    body = ErrorResponse.model_validate(json.loads(response.body))
    assert body.code == ErrorCode.forecast_not_available


def test_handler_serialises_code_as_its_string_value() -> None:
    """The serialised body uses the enum's string value (JSON-mode dump), so 004 reads a plain string."""
    response = not_found_handler(request=None, exc=FieldNotFoundError(1))  # type: ignore[arg-type]

    raw = json.loads(response.body)
    assert raw["code"] == "field_not_found"  # the enum value, not a Python repr
