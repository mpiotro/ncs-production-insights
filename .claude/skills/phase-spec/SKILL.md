---
name: phase-spec
description: "Author a phase's spec.md — EARS requirements + scope — per the SDD loop. Use when starting or revising a phase specification, e.g. /phase-spec 001-ingestion."
argument-hint: "<NNN-name>, e.g. 001-ingestion"
---

# Author a phase spec

You are the **coordinator** authoring a phase's `spec.md`. Write it directly — do **not** invoke the role
agents, and do **not** write `plan.md`, tasks, or any code. Stay at spec altitude and **stop after the
spec for review**.

**Target phase:** the argument you were invoked with (for example `001-ingestion`). If none was given,
ask which phase before proceeding.

## Procedure
1. **Orient.** The constitution is auto-loaded (mission / principles / tech-standards) — follow it. Read
   `specs/roadmap.md` for this phase's intent, scope, and dependencies, and read any **frozen contract**
   or upstream phase specs it builds on.
2. **Ground before you write.** If the phase touches an external source or a prior artifact, check the
   real thing first (schemas, headers, interfaces) — don't assume. Use it to make requirements accurate.
3. **Write `specs/<phase>/spec.md`** from the skeleton below. Every requirement is a **testable EARS
   statement** with a stable ID `<NNN>-R<k>` (e.g. `001-R3`), specific enough that the test-author can
   derive an acceptance test and everything traces (principles 2 and 8).
4. **Ask clarifying questions before finalizing** — never guess on scope or contract details. Keep the
   spec short and behavioral; the artifacts go on screen.
5. **Stop** and hand back for review. (Next loop: the architect turns this into `plan.md` + interfaces.)

## EARS forms (principle 2)
- Ubiquitous — `The <system> SHALL <requirement>.`
- Event-driven — `WHEN <trigger>, the <system> SHALL <response>.`
- State-driven — `WHILE <state>, the <system> SHALL <response>.`
- Unwanted — `IF <condition>, THEN the <system> SHALL <response>.`
- Optional — `WHERE <feature is included>, the <system> SHALL <response>.`

## spec.md skeleton (keep it lean)
```
# <NNN> <name> — spec

## Purpose
<one or two lines: what this phase delivers and why>

## Scope
- In: <...>
- Out: <explicit exclusions>

## Requirements (EARS)
- **<NNN>-R1** — <EARS statement>
- **<NNN>-R2** — <EARS statement>
  ...

## Data / interface contract   (only if this phase defines a boundary others consume)
<entities; each field with type, unit, nullability; key(s) — precise enough to formalize as typed models>

## Acceptance criteria
<how we know each requirement is met; reference the requirement IDs>

## Open questions
<anything still to confirm with the coordinator>
```

This skeleton is intentionally minimal — enrich it once 001 has proven the shape.
