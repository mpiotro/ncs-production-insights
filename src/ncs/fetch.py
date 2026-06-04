"""Sourcing & fallback — retrieve a dataset's raw rows from the first source that works (T8).

One ``fetch_dataset`` per dataset tries its ordered ``Source`` list (primary first, then the
documented fallback) and returns the first success: the raw rows **plus** the winning ``SourceRef``
recording the transport/url that served (so an R3 fallback is visible in the report). A source
"fails" — and the next is tried before any failure is reported — on: missing file / connection
error / non-2xx status / empty or malformed payload (zero usable rows). Only if **all** sources
fail does ``fetch_dataset`` raise (R1, R2, R3, plan.md §Sourcing & fallback).

Every transport normalizes to the **same in-memory shape** before the normalizer sees it: a list of
raw column dicts keyed by the SODIR ``prf*`` / ``fld*`` column names (plan.md). The normalizer is
therefore transport-agnostic, so the R3 path exercises identical downstream code.

Dispatch is two-dimensional:
- **where** — a ``location`` that parses as an ``http(s)`` URL is fetched with ``httpx``; anything
  else is read as a local file (the hermetic acceptance tests use local paths).
- **format** — ``Transport.csv`` parses CSV columns; ``Transport.rest`` parses the layer-7100 JSON
  (``features[].attributes``, reading geometry from the ``geometry_wkt`` attribute per the fixture
  README's documented hermetic assumption).
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx
from shapely.errors import ShapelyError
from shapely.geometry import shape as _geojson_to_shape

from ncs.config import Source
from ncs.contracts import Dataset, SourceRef, Transport

# Default timeout for the production HTTP path (seconds). The hermetic tests never hit this.
_HTTP_TIMEOUT_SECONDS = 30.0


class FetchError(Exception):
    """A single source could not be retrieved or yielded no usable rows.

    Raised per-source and caught by the fallback loop so the next source is tried. It escapes
    ``fetch_dataset`` only when **every** source for a dataset has failed (R3).
    """


def _looks_like_http(location: str) -> bool:
    """True when ``location`` is an ``http``/``https`` URL (→ HTTP path), else local-file path."""
    return urlparse(location).scheme in {"http", "https"}


def _source_url(location: str) -> str:
    """A URL string for ``SourceRef.url`` (typed ``AnyUrl``).

    An ``http(s)`` location is used as-is; a local filesystem path is turned into a ``file://`` URI
    (``AnyUrl``-valid) so the report can record exactly which file served — the R3 production test
    asserts the fallback filename appears in this URL.
    """
    if _looks_like_http(location):
        return location
    return Path(location).as_uri()


def _load_bytes(location: str) -> bytes:
    """Read the raw payload at ``location`` — local file or HTTP — or raise ``FetchError``.

    Local: a missing path raises ``FetchError`` (→ fallback). HTTP: a connection/timeout error or a
    non-2xx status raises ``FetchError`` (→ fallback). The body is returned undecoded; the per-format
    reader decodes it, so a malformed payload surfaces there as "zero usable rows".
    """
    if _looks_like_http(location):
        try:
            response = httpx.get(location, timeout=_HTTP_TIMEOUT_SECONDS)
            response.raise_for_status()
        except httpx.HTTPError as exc:  # connection, timeout, and non-2xx all subclass HTTPError
            raise FetchError(f"HTTP fetch failed for {location!r}: {exc}") from exc
        return response.content

    path = Path(location)
    if not path.is_file():
        raise FetchError(f"source file not found: {location!r}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise FetchError(f"could not read source file {location!r}: {exc}") from exc


def _parse_csv(payload: bytes) -> list[dict[str, str | None]]:
    """Parse a SODIR CSV payload into a list of raw column dicts (one per data row).

    Uses ``csv.DictReader`` so each row is keyed by the SODIR header columns; the normalizer maps
    those keys to model fields. A header-only or unparseable payload yields zero rows, which the
    caller treats as a failed source (→ fallback).
    """
    text = payload.decode("utf-8-sig")  # tolerate a BOM-prefixed export
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    return [dict(row) for row in reader]


def _geometry_to_wkt(geometry: object) -> str | None:
    """Convert a REST feature's geometry to a WKT string, or ``None`` when there is none.

    Handles the **GeoJSON** geometry the live FactMaps service returns with ``f=geojson`` (a
    ``{"type", "coordinates"}`` object) by passing it through shapely (``shape(...).wkt``). The
    hermetic fixtures instead carry the outline as a ready ``geometry_wkt`` *attribute* (consumed in
    ``_parse_rest``), so this is the live-service path the fixtures never exercised. A missing /
    null / empty / unreadable geometry returns ``None`` — SODIR publishes no outline (R7's null
    case); the contract validator still rejects a non-polygonal WKT at construction.
    """
    if not isinstance(geometry, dict):
        return None
    if "type" not in geometry or "coordinates" not in geometry:
        return None
    try:
        geom = _geojson_to_shape(geometry)
    except (ShapelyError, ValueError, TypeError, KeyError):
        return None
    if geom.is_empty:
        return None
    return geom.wkt


def _parse_rest(payload: bytes) -> list[dict[str, object]]:
    """Parse a field REST JSON payload into raw column dicts — ArcGIS *or* GeoJSON shape.

    Two feature shapes are accepted, so one handler serves both the hermetic fixture and the live
    FactMaps service:

    * **ArcGIS** ``features[].attributes`` — the fixture's shape; the attributes object already
      carries the ``fld*`` columns *and* a ready ``geometry_wkt`` string (fixture README), so the
      attributes dict is the raw column dict as-is.
    * **GeoJSON** ``features[].properties`` + ``features[].geometry`` — what live FactMaps layer 502
      returns with ``f=geojson``; the properties are the columns and the geometry is converted to
      ``geometry_wkt`` via :func:`_geometry_to_wkt` (shapely).

    If the columns don't already carry ``geometry_wkt``, it is derived from the feature geometry when
    present. Malformed JSON or a missing/empty ``features`` array yields zero rows → the caller falls
    back.
    """
    try:
        document = json.loads(payload.decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(document, dict):
        return []
    features = document.get("features")
    if not isinstance(features, list):
        return []
    rows: list[dict[str, object]] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        columns = feature.get("attributes")
        if not isinstance(columns, dict):
            columns = feature.get("properties")
        if not isinstance(columns, dict):
            continue
        row = dict(columns)
        # Live GeoJSON path: derive the outline WKT from the feature geometry when the columns
        # don't already carry it (the ArcGIS fixture's attributes already include ``geometry_wkt``).
        if not row.get("geometry_wkt"):
            wkt = _geometry_to_wkt(feature.get("geometry"))
            if wkt is not None:
                row["geometry_wkt"] = wkt
        rows.append(row)
    return rows


# Map each transport to the reader that turns its raw bytes into the shared list-of-dicts shape.
_READERS = {
    Transport.csv: _parse_csv,
    Transport.rest: _parse_rest,
}


def _read_source(source: Source) -> list[dict[str, object]]:
    """Retrieve and parse a single ``Source`` into raw column dicts, or raise ``FetchError``.

    Combines the *where* (``_load_bytes``) and *format* (``_READERS``) dispatch. A successful read
    that yields **zero** rows (empty/malformed payload) is itself a failure — raised as
    ``FetchError`` so the fallback loop moves on.
    """
    payload = _load_bytes(source.location)
    reader = _READERS[source.transport]
    rows = reader(payload)
    if not rows:
        raise FetchError(
            f"source {source.location!r} ({source.transport.value}) yielded zero usable rows"
        )
    return rows


def fetch_dataset(
    dataset: Dataset, sources: list[Source]
) -> tuple[list[dict[str, object]], SourceRef]:
    """Try ``sources`` in order; return the first success's rows plus its ``SourceRef`` (R1–R3).

    The fallback loop: each source is attempted; a ``FetchError`` (missing/empty/malformed/HTTP
    failure) means "try the next". The first source that yields rows wins and its
    ``(dataset, url, transport)`` is recorded. Only when **every** source has failed does this raise
    — the all-transports-before-failure guarantee R3's acceptance test drives.
    """
    if not sources:
        raise FetchError(f"no sources configured for dataset {dataset.value!r}")

    failures: list[str] = []
    for source in sources:
        try:
            rows = _read_source(source)
        except FetchError as exc:
            failures.append(str(exc))
            continue
        source_ref = SourceRef(
            dataset=dataset,
            url=_source_url(source.location),
            transport=source.transport,
        )
        return rows, source_ref

    raise FetchError(
        f"all sources failed for dataset {dataset.value!r}: " + "; ".join(failures)
    )
