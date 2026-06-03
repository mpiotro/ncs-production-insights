# NCS Production Insights

Spec-driven development. **Specs are the single source of truth; code is generated from them.**
The project constitution below is binding and auto-loaded every session.

@specs/constitution/mission.md
@specs/constitution/principles.md
@specs/constitution/tech-standards.md

## Orientation
- Living roadmap: `specs/roadmap.md` (ordered phases). Not imported here — the coordinator loads it per phase.
- Git / GitHub workflow — branching, worktrees, PRs, the contract freeze: `CONTRIBUTING.md`.
- Each phase runs in `specs/00N-<name>/` through the loop: **spec → plan → tasks → implement → validate**.
- Role agents in `.claude/agents/`: `architect`, `test-author`, `developer`, `validator`. The human is **coordinator**.
- `src/` and `tests/` are generated from specs — do not hand-author ahead of a phase's plan and tests.
