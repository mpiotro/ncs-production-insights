"""Unit tests for ``ncs.fetch`` (developer-owned, white-box) — 001-T8 / R1, R2, R3.

White-box checks of the sourcing layer: the CSV and REST parsers normalize to the same
list-of-dicts shape, the local-file vs http and url-building dispatch, and — the load-bearing R3
behavior — ``fetch_dataset`` tries sources **in order**, first success wins, a bad/empty/missing
source is skipped, and only an all-source failure raises. Driven with real temp files so the actual
parse path runs; the acceptance suite proves the same ordering end-to-end through ``ingest``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import httpx

from ncs.config import Source
from ncs.contracts import Dataset, Transport
from ncs.fetch import (
    FetchError,
    _geometry_to_wkt,
    _load_bytes,
    _looks_like_http,
    _parse_csv,
    _parse_rest,
    _read_source,
    _source_url,
    fetch_dataset,
)

_PRODUCTION_CSV = (
    "prfInformationCarrier,prfYear,prfMonth,prfPrdOilNetMillSm3,prfPrdGasNetBillSm3,"
    "prfPrdNGLNetMillSm3,prfPrdCondensateNetMillSm3,prfPrdOeNetMillSm3,"
    "prfPrdProducedWaterInFieldMillSm3,prfNpdidInformationCarrier\n"
    "ALPHA,2022,1,1.180,0.940,0.105,0.0,2.205,0.500,1001\n"
)

_FIELD_JSON = """
{
  "features": [
    {
      "attributes": {
        "fldNpdidField": 1001,
        "fldName": "ALPHA",
        "fldCurrentActivitySatus": "Producing",
        "geometry_wkt": "POLYGON ((2.0 60.0, 2.5 60.0, 2.5 60.5, 2.0 60.5, 2.0 60.0))"
      }
    }
  ]
}
"""


def _write(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


# --- Dispatch helpers ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("location", "is_http"),
    [
        ("http://example.com/x.csv", True),
        ("https://factpages.sodir.no/x.csv", True),
        (r"C:\data\production.csv", False),
        ("/tmp/production.csv", False),
    ],
)
def test_looks_like_http_dispatch(location: str, is_http: bool) -> None:
    """An http(s) location takes the HTTP path; everything else is read as a local file."""
    assert _looks_like_http(location) is is_http


def test_source_url_keeps_http_and_files_become_file_uri(tmp_path: Path) -> None:
    """An http URL is recorded as-is; a local path becomes a file:// URI (AnyUrl-valid)."""
    assert _source_url("https://sodir.no/x.csv") == "https://sodir.no/x.csv"
    local = _write(tmp_path, "production_fallback.csv", _PRODUCTION_CSV)
    url = _source_url(local)
    assert url.startswith("file://")
    assert "production_fallback.csv" in url


# --- Parsers normalize to the same list-of-dicts shape -------------------------------------------


def test_parse_csv_yields_column_keyed_dicts() -> None:
    """The CSV parser keys each row by the SODIR header columns."""
    rows = _parse_csv(_PRODUCTION_CSV.encode("utf-8"))
    assert len(rows) == 1
    assert rows[0]["prfInformationCarrier"] == "ALPHA"
    assert rows[0]["prfNpdidInformationCarrier"] == "1001"


def test_parse_csv_header_only_is_empty() -> None:
    """A header-only CSV yields zero rows (the 'empty payload' failure the loop falls back on)."""
    header_only = _PRODUCTION_CSV.splitlines()[0] + "\n"
    assert _parse_csv(header_only.encode("utf-8")) == []


def test_parse_rest_reads_feature_attributes_with_wkt() -> None:
    """The REST parser lifts each feature's attributes (incl. the geometry_wkt string)."""
    rows = _parse_rest(_FIELD_JSON.encode("utf-8"))
    assert len(rows) == 1
    assert rows[0]["fldNpdidField"] == 1001
    assert rows[0]["geometry_wkt"].startswith("POLYGON")


@pytest.mark.parametrize("bad", [b"not json", b"{}", b'{"features": []}', b'{"features": 5}'])
def test_parse_rest_malformed_or_empty_yields_no_rows(bad: bytes) -> None:
    """Malformed JSON or a missing/empty features array yields zero rows (→ fallback)."""
    assert _parse_rest(bad) == []


# --- REST: live GeoJSON shape (FactMaps f=geojson) + geometry → WKT ------------------------------

_FIELD_GEOJSON = """
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "fldNpdidField": 2001,
        "fldName": "LIVEFIELD",
        "fldCurrentActivitySatus": "Producing"
      },
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[2.0, 60.0], [2.5, 60.0], [2.5, 60.5], [2.0, 60.5], [2.0, 60.0]]]
      }
    }
  ]
}
"""


def test_parse_rest_reads_geojson_properties_and_derives_wkt() -> None:
    """REST also handles a GeoJSON FeatureCollection (live FactMaps ``f=geojson``): ``properties``
    are the columns and the GeoJSON ``geometry`` is converted to a ``geometry_wkt`` string."""
    rows = _parse_rest(_FIELD_GEOJSON.encode("utf-8"))
    assert len(rows) == 1
    assert rows[0]["fldNpdidField"] == 2001
    assert rows[0]["fldName"] == "LIVEFIELD"
    assert rows[0]["geometry_wkt"].startswith("POLYGON")


def test_parse_rest_geojson_null_geometry_leaves_geometry_absent() -> None:
    """A GeoJSON feature with ``geometry: null`` (SODIR publishes no outline) gets no derived WKT."""
    doc = (
        '{"type":"FeatureCollection","features":[{"type":"Feature",'
        '"properties":{"fldNpdidField":3001,"fldName":"NOGEO"},"geometry":null}]}'
    )
    rows = _parse_rest(doc.encode("utf-8"))
    assert len(rows) == 1
    assert rows[0].get("geometry_wkt") is None


def test_geometry_to_wkt_converts_geojson_polygon_and_multipolygon() -> None:
    """A GeoJSON Polygon/MultiPolygon geometry round-trips to the matching WKT (via shapely)."""
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    assert _geometry_to_wkt(poly).startswith("POLYGON")
    multi = {"type": "MultiPolygon",
             "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]]}
    assert _geometry_to_wkt(multi).startswith("MULTIPOLYGON")


@pytest.mark.parametrize(
    "geom",
    [None, {}, {"type": "Polygon"}, {"coordinates": []}, {"rings": [[[0, 0]]]}, "x", 5],
)
def test_geometry_to_wkt_none_for_missing_or_unsupported(geom: object) -> None:
    """Missing / null / non-GeoJSON (e.g. raw Esri ``rings``) geometry → ``None`` (null outline)."""
    assert _geometry_to_wkt(geom) is None


# --- fetch_dataset: ordering & fallback (the R3 heart) -------------------------------------------


def test_first_source_wins_when_primary_succeeds(tmp_path: Path) -> None:
    """The primary source wins when it succeeds; its SourceRef records the right transport/url."""
    primary = _write(tmp_path, "production_primary.csv", _PRODUCTION_CSV)
    fallback = _write(tmp_path, "production_fallback.csv", _PRODUCTION_CSV)
    sources = [
        Source(transport=Transport.csv, location=primary),
        Source(transport=Transport.csv, location=fallback),
    ]

    rows, ref = fetch_dataset(Dataset.production, sources)

    assert len(rows) == 1
    assert ref.dataset == Dataset.production
    assert ref.transport == Transport.csv
    assert "production_primary.csv" in str(ref.url)  # primary won, not the fallback


def test_fallback_wins_when_primary_missing(tmp_path: Path) -> None:
    """A missing primary is skipped and the fallback wins — the core R3 ordering guarantee."""
    missing = str(tmp_path / "does_not_exist.csv")
    fallback = _write(tmp_path, "production_fallback.csv", _PRODUCTION_CSV)
    sources = [
        Source(transport=Transport.csv, location=missing),
        Source(transport=Transport.csv, location=fallback),
    ]

    rows, ref = fetch_dataset(Dataset.production, sources)

    assert len(rows) == 1
    assert "production_fallback.csv" in str(ref.url)


def test_transport_flip_when_rest_primary_missing(tmp_path: Path) -> None:
    """A missing REST primary falls back to the CSV source — the rest→csv transport flip (R3)."""
    missing = str(tmp_path / "missing.json")
    field_csv = (
        "fldNpdidField,fldName,fldCurrentActivitySatus,fldHcType,fldMainArea,cmpLongName,"
        "fldDiscoveryYear,geometry_wkt\n"
        "1001,ALPHA,Producing,OIL,North sea,Alpha Operator AS,1979,"
        '"POLYGON ((2.0 60.0, 2.5 60.0, 2.5 60.5, 2.0 60.5, 2.0 60.0))"\n'
    )
    fallback = _write(tmp_path, "field_fallback.csv", field_csv)
    sources = [
        Source(transport=Transport.rest, location=missing),
        Source(transport=Transport.csv, location=fallback),
    ]

    rows, ref = fetch_dataset(Dataset.field, sources)

    assert len(rows) == 1
    assert ref.transport == Transport.csv  # flipped from rest


def test_empty_payload_source_is_skipped(tmp_path: Path) -> None:
    """A source that parses to zero rows is treated as a failure and skipped (→ next source)."""
    header_only = _write(
        tmp_path, "empty.csv", _PRODUCTION_CSV.splitlines()[0] + "\n"
    )
    good = _write(tmp_path, "good.csv", _PRODUCTION_CSV)
    sources = [
        Source(transport=Transport.csv, location=header_only),
        Source(transport=Transport.csv, location=good),
    ]

    rows, ref = fetch_dataset(Dataset.production, sources)

    assert len(rows) == 1
    assert "good.csv" in str(ref.url)


def test_all_sources_failing_raises(tmp_path: Path) -> None:
    """When every source fails, fetch_dataset raises (R3: only an all-fail run fails)."""
    sources = [
        Source(transport=Transport.csv, location=str(tmp_path / "a.csv")),
        Source(transport=Transport.csv, location=str(tmp_path / "b.csv")),
    ]
    with pytest.raises(FetchError):
        fetch_dataset(Dataset.production, sources)


def test_no_sources_configured_raises() -> None:
    """An empty source list raises rather than silently returning nothing."""
    with pytest.raises(FetchError):
        fetch_dataset(Dataset.production, [])


# --- HTTP path (production dispatch; mocked so the suite stays hermetic) --------------------------


def test_http_source_is_read_and_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """An http(s) location is fetched over HTTP and parsed — the production CSV dispatch.

    ``httpx.get`` is stubbed so no real network call is made (the hermetic constraint holds); the
    point is that ``_looks_like_http`` routes to the HTTP loader and the bytes flow into the parser.
    """

    class _Resp:
        content = _PRODUCTION_CSV.encode("utf-8")

        def raise_for_status(self) -> None:  # 2xx — no error
            return None

    monkeypatch.setattr(httpx, "get", lambda url, timeout: _Resp())

    rows = _read_source(Source(transport=Transport.csv, location="https://sodir.no/p.csv"))
    assert rows[0]["prfInformationCarrier"] == "ALPHA"


def test_http_error_becomes_fetch_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A connection/timeout/non-2xx (any httpx.HTTPError) maps to FetchError (→ fallback, R3)."""

    def _boom(url: str, timeout: float) -> None:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", _boom)

    with pytest.raises(FetchError):
        _load_bytes("https://sodir.no/down.csv")
