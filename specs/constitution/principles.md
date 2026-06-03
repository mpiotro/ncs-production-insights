# Principles — the immutable rules

These are binding, **equally weighted, and non-negotiable** — the order is a neutral reading sequence, not a ranking. Each number is a **stable identifier** (cited by tasks, tests, commits, the agents, and the role-guard hook), so principles are appended and **never renumbered**. Changing one is a deliberate constitutional amendment, made rarely.

1. **Specs are the single source of truth.** Code is generated from specs, never the reverse.
2. **Every requirement is a testable EARS statement.**
3. **The data contract is frozen before any downstream component begins.**
4. **Separation of duties.** Acceptance tests (from EARS) are authored by someone other than the implementer; the developer writes unit tests, but never their own acceptance tests.
5. **Every implementation task ships with tests.**
6. **Every forecast-accuracy claim is backed by a held-out backtest.**
7. **No secrets or credentials in code or git.**
8. **Traceability.** Every task, test, and commit names the EARS requirement ID it implements or verifies.
9. **No requirement loses its tests.** Every EARS requirement keeps at least one passing test for the life of the project, and measured coverage never regresses without a recorded waiver.
