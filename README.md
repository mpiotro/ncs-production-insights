# NCS Production Insights

Fast, trustworthy view of Norwegian Continental Shelf (NCS) field production with
**credible, backtested decline forecasts** — built entirely from SODIR open data, spec-first.

**Specs are the single source of truth; code is generated from them.** The binding project
constitution lives in [`specs/constitution/`](specs/constitution/); the git/GitHub workflow is in
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Layout
- `specs/` — phases (`00N-<name>/`) running the loop spec -> plan -> tasks -> implement -> validate.
- `src/ncs/` — the importable Python package (src-layout).
- `tests/acceptance/` — black-box tests from EARS (test-author); `tests/unit/` — white-box tests (developer).
- `frontend/` — the React + Vite + TypeScript dashboard (its own npm toolchain; Vitest tests).

## Develop
Python 3.12+, managed with [`uv`](https://docs.astral.sh/uv/); the frontend uses Node 20+ / npm.

```bash
uv sync                              # backend: resolve + install (writes uv.lock)
uv run pytest                        # backend suite with the coverage gate
cd frontend && npm ci && npm run coverage   # frontend suite with coverage
```

## Running the app

Three layers off the frozen data contract: **ingestion + forecasting** build a DuckDB store, the
**API** serves it read-only, and the **dashboard** displays it.

**Prerequisites:** Python 3.12+ with `uv` (backend) and Node 20+ with npm (frontend). Install once with
`uv sync` and `cd frontend && npm ci`.

> Env vars below use POSIX `export`. On **Windows PowerShell** set them with `$env:NAME = 'value'`
> instead (and run Python tools as `uv run python -m <tool>`).

### 1. Build the data store (ingestion → forecasts)

The store is populated **out of band** — the API only ever reads it. `ncs.api.seed` runs the frozen 001
ingestion then the 002 forecasting against one writable DuckDB file, given the SODIR sources to pull:

```bash
export NCS_DB_PATH=ncs.duckdb            # where to write the store
export NCS_INGEST_SETTINGS_JSON='{
  "production_sources": [
    { "transport": "csv",  "location": "https://factpages.sodir.no/.../field_production_monthly.csv" }
  ],
  "field_sources": [
    { "transport": "rest", "location": "https://factmaps.sodir.no/api/rest/services/DataService/.../7100" },
    { "transport": "csv",  "location": "https://factpages.sodir.no/downloads/csv/fldArea.csv" }
  ]
}'
uv run python -m ncs.api.seed
# -> "Seeded ncs.duckdb: N fields, M production rows, K forecasts (...)"
```

- Each `*_sources` list is tried **in order** — primary first, then the documented fallback (001-R3).
- A `location` that is an `http(s)` URL is fetched over HTTP; **a local filesystem path is read
  directly**, so you can ingest from downloaded SODIR files offline. The exact SODIR sources the
  contract is grounded on are in [`specs/001-ingestion/spec.md`](specs/001-ingestion/spec.md) §Sources.
- Forecasts are produced only for fields with **≥ 60 months** of history (the credibility gate); shorter
  fields are served history-only.

> **Offline / quick check:** point the `location`s at local SODIR-format files instead of URLs — the
> repo ships a tiny sample under `tests/acceptance/fixtures/sodir/` that ingestion is verified against.

### 2. Run the API (003)

Serves the store read-only as JSON; OpenAPI/Swagger is auto-generated at `/docs`.

```bash
export NCS_DB_PATH=ncs.duckdb            # the store from step 1
uv run python -m uvicorn ncs.api.app:create_app --factory --port 8003
# health: http://localhost:8003/health   ·   docs: http://localhost:8003/docs
```

`API_PORT` (default 8003) and `API_CORS_ORIGINS` (comma-separated; defaults to the Vite dev origin
`http://localhost:5173`) are also read from the environment.

### 3. Run the dashboard (004)

```bash
cd frontend
# against the live API from step 2 …
export VITE_API_SOURCE=http VITE_API_BASE_URL=http://localhost:8003
npm run dev                              # -> http://localhost:5173

# … or standalone against the built-in typed mock (no backend needed):
VITE_API_SOURCE=mock npm run dev
```

Production build: `npm run build`; preview it locally with `npx vite preview`.
