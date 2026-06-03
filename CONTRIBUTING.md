# Contributing

How we work with git and GitHub on **NCS Production Insights**. This is the *operational* layer; the
immutable rules live in the constitution (`specs/constitution/`) and override anything here. Several git
invariants are already constitutional and are not restated below — no secrets in git (principle 7), every
commit cites its EARS requirement ID (principle 8), the data contract is frozen before downstream work
(principle 3), and coverage never regresses (principle 9).

## Branching — trunk-based
- **`main`** is the trunk: always green, protected, the single merged source of truth.
- Work happens on **short-lived branches** named for the phase (and task, when useful): `001-ingestion`,
  `002-analytics`, `003-api`, `004-frontend`, or `00N-<short-task>`.
- No direct pushes to `main` — everything lands through a reviewed pull request.

## Phases & worktrees
001 is sequential and **freezes the data contract**; 002 / 003 / 004 then fan out **in parallel**, each in
its own **git worktree** off the frozen contract — with its own DuckDB file and a distinct API port, so they
never collide (tech-standards).

```
# once 001's contract is frozen on main:
git worktree add ../ncs-002-analytics 002-analytics
git worktree add ../ncs-003-api       003-api
git worktree add ../ncs-004-frontend  004-frontend
```

| Worktree | Branch | DuckDB file |
|----------|--------|-------------|
| `ncs-002-analytics` | `002-analytics` | `ncs-002.duckdb` |
| `ncs-003-api` | `003-api` | `ncs-003.duckdb` |
| `ncs-004-frontend` | `004-frontend` | `ncs-004.duckdb` |

Each phase that serves over HTTP (003's API, 004's dev server) pins a **distinct port** in its `plan.md` /
local env — never hard-coded into shared code. DB files (`*.duckdb`), `node_modules/`, and `dist/` are
gitignored.

## Freezing the contract (principle 3)
When 001 merges, the contract is frozen:
1. **Tag** the contract commit — `git tag 001-contract-frozen` (push the tag).
2. **Protect** the contract path with `.github/CODEOWNERS` so changes require coordinator review, and enable
   branch protection on `main`.
3. 002 / 003 / 004 branch off the frozen point and treat the contract as read-only.

Changing a frozen contract is a deliberate amendment, not a casual edit: version it (`contract v2`), re-tag,
and re-validate every downstream phase. *(Optional hardening: extend the role-guard hook to lock the contract
files locally, the way it already guards `tests/acceptance/`.)*

## Pull requests
Every change reaches `main` through a PR whose body:
- names the **EARS requirement IDs** it implements or verifies (principle 8);
- summarizes the spec → plan → tests → implementation trail for those IDs;
- records a `COVERAGE-WAIVER:` line (tech-standards) if a coverage drop is intended.

A PR merges only when **all** hold:

- [ ] CI green — all `pytest` tests pass, including the phase's **acceptance** tests.
- [ ] Coverage didn't regress (`pytest-cov`); each cited EARS ID has ≥1 passing test (principle 9).
- [ ] The **validator's** findings are resolved (or explicitly waived by the coordinator).
- [ ] No secrets or credentials added (principle 7).

**Separation of duties (principle 4):** the implementer never approves or merges their own work — the
**validator** reviews and returns findings; the **coordinator** approves and merges.

## Who runs git
Only the **coordinator** and the **developer** agent have a shell, so only they run git. The **architect**,
**test-author**, and **validator** produce artifacts (plan, tests, findings) but never touch git — their
outputs are committed by the coordinator or the developer.

## Commits
- Lead the subject with the requirement ID, e.g. `[001-R3] add monthly-production model`.
- Keep commits small and focused so `main` stays green.
- Attribute agent work with a trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## CI
GitHub Actions runs `pytest` + `pytest-cov` on every PR and enforces the coverage ratchet (principle 9); the
frontend's coverage tooling is fixed in phase 004. The workflow file is added during build-out — it does not
exist yet.
