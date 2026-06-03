---
name: phase-tasks
description: "Author a phase's tasks.md — ordered, EARS-traced work items that map the approved plan + frozen contracts to acceptance tests and implementation, per the SDD loop. Use after plan.md is approved, e.g. /phase-tasks 001-ingestion."
argument-hint: "<NNN-name>, e.g. 001-ingestion"
---

# Author a phase's tasks

You are the **coordinator** authoring a phase's `tasks.md` — the ordered bridge from the approved
`plan.md` + frozen `contracts.md` to the **test-author's** acceptance tests and the **developer's**
implementation. Write it directly — do **not** invoke the role agents, and do **not** write tests or
code. Stay at task altitude and **stop after the tasks for review**.

**Target phase:** the argument you were invoked with (for example `001-ingestion`). If none was given,
ask which phase before proceeding.

## Procedure
1. **Orient.** The constitution is auto-loaded — follow it. Read the phase's `spec.md` (the EARS IDs),
   `plan.md` (the design seams), and `contracts.md` (the frozen types); skim `specs/roadmap.md` for
   sequencing.
2. **Decompose the plan into ordered tasks** — each a small, independently reviewable increment of the
   design. Sequence by dependency and honor **TDD**: the acceptance test for an EARS ID is authored (and
   must fail) **before** the implementation that makes it pass.
3. **Trace everything (principles 8, 9).** Every task names the **EARS ID(s)** it implements or verifies
   and the **acceptance test(s)** it delivers or satisfies — so each EARS ID has a task that writes its
   test and a task that makes it pass. No requirement is left uncovered.
4. **Assign, don't author (principle 4).** Tasks route work to the **test-author** (`tests/acceptance/`)
   and the **developer** (`src/` + `tests/unit/`, shipped with tests — principle 5); they never contain
   test bodies or implementation. You own sequencing and increment scope.
5. **Ask clarifying questions before finalizing**, then **stop** and hand back for review. (Next loop:
   the test-author writes the failing acceptance tests, then the developer implements. After your review,
   this snapshot is checkpointed as the `<NNN>-tasks` tag.)

## Task anatomy (one row each, keep it lean)
- **ID** — `<NNN>-T<k>` (stable; cited by commits and PRs, principle 8).
- **Title** — the increment, in a few words.
- **EARS** — the requirement ID(s) it implements/verifies.
- **Tests** — the acceptance test(s) it delivers (test-author) or must pass (developer).
- **Owner** — `test-author` | `developer` (principle 4).
- **Depends on** — prerequisite task IDs (enforces TDD / build order).

## tasks.md skeleton (keep it lean)
```
# <NNN> <name> — tasks

## Approach
<one or two lines: build order and any increment boundaries>

## Tasks
| ID | Title | EARS | Tests | Owner | Depends on |
|----|-------|------|-------|-------|------------|
| <NNN>-T1 | author acceptance tests for <...> | <NNN>-R1, R2 | tests/acceptance/test_<...>.py | test-author | — |
| <NNN>-T2 | implement <...> to pass them | <NNN>-R1, R2 | T1 (+ unit tests) | developer | T1 |
| ... |

## Coverage check (principle 9)
<every EARS ID maps to ≥1 task that writes its test and ≥1 that makes it pass — list any gaps>

## Open questions
<anything to confirm with the coordinator>
```

This skeleton is intentionally minimal — enrich it once 001 has proven the shape.
