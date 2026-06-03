"""Unit tests for ``ncs.pipeline`` (developer-owned, white-box) — 001-T12 / R9.

White-box checks on the orchestrator's load-bearing details that the happy-path acceptance suite
cannot reach: the **completeness invariant** raises when the persisted production count would differ
from the source row count (a silent drop, R9-forbidden), and ``retrieved_at`` is stamped at
microsecond resolution so repeated runs append distinct ``ingestion_report`` rows. The end-to-end
happy path is covered black-box by the acceptance suite.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pytest

from ncs import ingest
from ncs.config import Settings, Source
from ncs.contracts import MonthlyProduction, Transport
from ncs.pipeline import CompletenessError

_FIXTURES = (
    Path(__file__).resolve().parents[1] / "acceptance" / "fixtures" / "sodir"
)


def _good_settings() -> Settings:
    """Reuse the canonical acceptance fixtures (both primaries valid) for the happy path."""
    return Settings(
        production_sources=[
            Source(transport=Transport.csv, location=str(_FIXTURES / "production_primary.csv")),
        ],
        field_sources=[
            Source(transport=Transport.rest, location=str(_FIXTURES / "field_primary.json")),
        ],
    )


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(str(tmp_path / "pipeline.duckdb"))
    try:
        yield connection
    finally:
        connection.close()


def test_completeness_invariant_raises_on_silent_drop(
    con: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If persisted production < source rows, the run raises rather than under-counting (R9).

    Simulate a drop by patching the normalizer the pipeline calls to discard one production row;
    the persisted count then trails the source count and the completeness check must fail loudly.
    """
    import ncs.pipeline as pipeline

    real_normalize = pipeline.normalize_production

    def _dropping_normalize(raw_rows: list[dict[str, object]]) -> list[MonthlyProduction]:
        models = real_normalize(raw_rows)
        return models[:-1]  # silently drop one row

    monkeypatch.setattr(pipeline, "normalize_production", _dropping_normalize)

    with pytest.raises(CompletenessError):
        ingest(con, _good_settings())


def test_retrieved_at_is_utc_microsecond_resolution(con: duckdb.DuckDBPyConnection) -> None:
    """retrieved_at is timezone-aware UTC, stamped at run time (the window brackets the call)."""
    before = datetime.now(timezone.utc)
    report = ingest(con, _good_settings())
    after = datetime.now(timezone.utc)

    assert report.retrieved_at.tzinfo is not None
    assert report.retrieved_at.utcoffset().total_seconds() == 0
    assert before <= report.retrieved_at <= after


def test_repeated_runs_append_distinct_report_rows(con: duckdb.DuckDBPyConnection) -> None:
    """Two runs over the same store append two ingestion_report rows (distinct microsecond PKs, R9).

    This is the reason retrieved_at keeps full microsecond resolution: a coarser stamp would collide
    on the TIMESTAMPTZ primary key when ingest runs twice in quick succession.
    """
    ingest(con, _good_settings())
    ingest(con, _good_settings())

    (report_rows,) = con.execute("SELECT count(*) FROM ingestion_report").fetchone()
    assert report_rows == 2

    # The data tables stay idempotent across those runs (no duplication).
    (production_rows,) = con.execute("SELECT count(*) FROM monthly_production").fetchone()
    assert production_rows == 10
