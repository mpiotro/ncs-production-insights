# 001 ingestion — tasks

## Approach
Build order: **scaffold → failing acceptance tests → implementation**, TDD throughout. The developer
scaffolds the uv project (T1); the **test-author** writes one failing acceptance suite per concern off
the frozen `contracts.md` (T2–T6, sharing the local SODIR fixtures from T2); the **developer** then
implements the contract models and the `fetch → normalize → link → persist → report` pipeline (T7–T12),
each task turning its suite green and shipping unit tests (principle 5). Acceptance suites run
**hermetically** through the `ingest(con, settings)` seam (local fixtures, no live network); integration
and the coverage-ratchet baseline land at T12.

## Tasks
| ID | Title | EARS | Tests | Owner | Depends on |
|----|-------|------|-------|-------|------------|
| 001-T1 | scaffold uv project: layout, deps, pytest+cov, CI | — *(enabling)* | import smoke | developer | — |
| 001-T2 | acceptance suite + shared local SODIR fixtures: sourcing & fallback | 001-R1, R2, R3 | tests/acceptance/test_sourcing.py | test-author | T1 |
| 001-T3 | acceptance suite: normalization & contract conformance | 001-R4, R5, R6, R7 | tests/acceptance/test_normalization.py | test-author | T1, T2 |
| 001-T4 | acceptance suite: NPDID link reconcile (kept + reported) | 001-R8 | tests/acceptance/test_link.py | test-author | T1, T2 |
| 001-T5 | acceptance suite: persistence & idempotent re-run | 001-R10, R11 | tests/acceptance/test_persistence.py | test-author | T1, T2 |
| 001-T6 | acceptance suite: ingestion report & completeness | 001-R9 | tests/acceptance/test_report.py | test-author | T1, T2 |
| 001-T7 | implement frozen contract models + validators | 001-R4, R5, R6, R7 | T3 (+ unit) | developer | T1 |
| 001-T8 | implement fetch + primary/fallback per dataset | 001-R1, R2, R3 | T2 (+ unit) | developer | T2, T7 |
| 001-T9 | implement normalization: absent→null, native units, WKT | 001-R4, R5, R6, R7 | T3 (+ unit) | developer | T3, T7, T8 |
| 001-T10 | implement NPDID link reconcile + unmatched lists | 001-R8 | T4 (+ unit) | developer | T4, T9 |
| 001-T11 | implement DuckDB persistence + ON CONFLICT upsert | 001-R10, R11 | T5 (+ unit) | developer | T5, T7, T9 |
| 001-T12 | implement report + assemble `ingest()` end-to-end; record coverage baseline | 001-R9 *(+ integration R1–R11)* | T6 + all acceptance (+ unit) | developer | T6, T8, T10, T11 |

## Coverage check (principle 9)
Every EARS ID has a test-author task that writes its acceptance test **and** ≥1 developer task that makes it pass:

| EARS | Test written by | Made to pass by |
|------|-----------------|-----------------|
| R1, R2, R3 | T2 | T8 (+ T12 integration) |
| R4, R5, R6, R7 | T3 | T7 (types) + T9 (mapping) |
| R8 | T4 | T10 |
| R9 | T6 | T12 |
| R10, R11 | T5 | T11 |

T1 (scaffold) and the integration in T12 are enabling/integrative — no EARS is uniquely theirs.

## Resolved
- **Python package name → `ncs`** — imports read `from ncs.… import …`; matches the `ncs-` worktree/DB prefix.
- **Hermetic acceptance tests → local fixtures via the `settings` source seam** — the test-author drops
  small sample SODIR files; `ingest()` settings point fetch at them; the R3 test forces the primary to a
  missing/garbage path. So **T8's fetch accepts local/file sources** (not just HTTP) — black-box, exercises
  the real parse path, no live network.
- **CI at scaffold → yes** — T1 wires the GitHub Actions `pytest` + `pytest-cov` workflow and records the
  initial coverage baseline (the ratchet is constitutional, principle 9).
- **Live-source smoke → optional, marked, non-gated** — a manually-run check hitting the real SODIR
  endpoints to catch URL/schema drift; excluded from the CI coverage gate.
