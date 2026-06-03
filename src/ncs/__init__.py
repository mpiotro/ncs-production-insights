"""ncs — NCS Production Insights.

The SODIR ingestion layer (phase 001). The public seam is ``ingest(con, settings)``: it runs
fetch → normalize → link → persist → report over the frozen typed contract (``ncs.contracts``) and
the run configuration (``ncs.config``), returning a typed ``IngestionReport`` and writing it (plus
the data) to a single DuckDB store. See ``specs/001-ingestion/`` for the spec/plan/contract.
"""

from __future__ import annotations

from ncs.pipeline import ingest

__version__ = "0.1.0"

__all__ = ["ingest", "__version__"]
