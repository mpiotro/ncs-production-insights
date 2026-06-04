"""Unit tests for ``ncs.api.responses`` (developer-owned, white-box) — 003-T7 / R2–R7.

White-box checks of the transport models: the list envelopes wrap the frozen 001/002 models, the
GeoJSON Feature / FeatureCollection default their RFC-7946 ``type`` discriminators, the error body
carries the typed ``ErrorCode``, and every model is ``extra="forbid"`` (a malformed shape is rejected
at the boundary). The frozen models are re-used verbatim — asserted by constructing an envelope around
a real ``Field`` / ``MonthlyProduction``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ncs.api.responses import (
    ErrorCode,
    ErrorResponse,
    FieldFeature,
    FieldFeatureCollection,
    FieldListResponse,
    FieldProperties,
    ProductionHistoryResponse,
)
from ncs.contracts import Field, MonthlyProduction

_FIELD = Field(field_npdid=9001, field_name="ALPHA")
_ROW = MonthlyProduction(field_npdid=9001, field_name="ALPHA", year=2014, month=1, oil=1.0)


def test_field_list_response_wraps_frozen_fields() -> None:
    """``FieldListResponse`` carries a count + the frozen ``Field`` items verbatim (R2)."""
    resp = FieldListResponse(count=1, fields=[_FIELD])

    assert resp.count == 1
    assert resp.fields[0] is _FIELD
    assert isinstance(resp.fields[0], Field)


def test_production_history_response_echoes_npdid_and_rows() -> None:
    """``ProductionHistoryResponse`` echoes the NPDID + count and carries frozen rows (R3)."""
    resp = ProductionHistoryResponse(field_npdid=9001, count=1, production=[_ROW])

    assert resp.field_npdid == 9001
    assert resp.count == 1
    assert resp.production[0] is _ROW


def test_feature_defaults_its_type_discriminator() -> None:
    """A ``FieldFeature`` defaults ``type == "Feature"`` (RFC 7946) and accepts null geometry (R5)."""
    feature = FieldFeature(geometry=None, properties=FieldProperties(field_npdid=1, field_name="X"))

    assert feature.type == "Feature"
    assert feature.geometry is None


def test_feature_collection_defaults_its_type_discriminator() -> None:
    """A ``FieldFeatureCollection`` defaults ``type == "FeatureCollection"`` (RFC 7946) (R5)."""
    collection = FieldFeatureCollection(features=[])

    assert collection.type == "FeatureCollection"
    assert collection.features == []


def test_field_properties_are_identity_only_and_forbid_extras() -> None:
    """``FieldProperties`` is identity-only; an extra key is rejected (extra='forbid') (R5)."""
    props = FieldProperties(field_npdid=1, field_name="X")
    assert props.model_dump() == {"field_npdid": 1, "field_name": "X"}

    with pytest.raises(ValidationError):
        FieldProperties(field_npdid=1, field_name="X", extra="nope")  # type: ignore[call-arg]


def test_error_response_carries_typed_code() -> None:
    """``ErrorResponse`` carries the typed ``ErrorCode`` and a detail string (R6)."""
    err = ErrorResponse(code=ErrorCode.field_not_found, detail="No field 1")

    assert err.code is ErrorCode.field_not_found
    assert err.detail == "No field 1"


def test_error_code_values_are_the_wire_strings() -> None:
    """The two error codes serialise to their documented wire strings (R4 distinctness)."""
    assert ErrorCode.field_not_found.value == "field_not_found"
    assert ErrorCode.forecast_not_available.value == "forecast_not_available"


def test_envelopes_forbid_extra_fields() -> None:
    """Every envelope is ``extra='forbid'`` — a stray field fails at the boundary (contract safety)."""
    with pytest.raises(ValidationError):
        FieldListResponse(count=0, fields=[], stray=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ProductionHistoryResponse(field_npdid=1, count=0, production=[], stray=1)  # type: ignore[call-arg]
