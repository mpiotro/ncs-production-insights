# Tech Standards — durable, cross-cutting constraints

Stack and constraints that hold across the whole project. **Feature-specific design choices
(e.g. which library implements decline-curve fitting vs the statistical forecast) belong in that
phase's `plan.md`, never here.**

- **Language & tooling:** Python 3.12+, managed with `uv` (uv-managed venv; `uv.lock` committed).
- **Contract style:** contract-first. Everything crossing a boundary is a typed **Pydantic v2** model,
  defined before the code that produces or consumes it.
- **Storage:** **DuckDB** — a single embedded file. No external database service.
- **API:** **FastAPI** serving the Pydantic models; OpenAPI / Swagger is auto-generated, never hand-written.
- **Frontend:** **React + Vite + TypeScript.** Charts: **Plotly**. Maps: **Leaflet** (no API token, no paid tiles).
- **Tests:** **pytest**.
- **Test layout & ownership:** `tests/acceptance/` — black-box tests derived from EARS, owned by the
  **test-author**; `tests/unit/` — white-box tests of internal logic, owned by the **developer**.
  Implementers write unit tests, never their own acceptance tests (principle 4).
- **Coverage ratchet (principle 9):** every EARS ID must be cited by ≥1 passing test (verified from
  the principle-8 IDs); CI measures coverage with **`pytest-cov`** and fails any drop below the recorded
  baseline, which only moves up. Frontend coverage tooling is fixed in phase 004. A deliberate
  reduction needs a coordinator-recorded waiver (e.g. a `COVERAGE-WAIVER:` line in the PR).
- **Geometry:** **WKT in** (from SODIR) → **GeoJSON out** (to the frontend), converted with **shapely**.
- **Parallel work:** each git worktree gets **its own DuckDB file** and a **distinct API port**, so
  002 / 003 / 004 run side by side without collision.
- **Secrets:** none in code or git (principle 7); configuration via environment.
