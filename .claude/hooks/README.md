# Hooks

`role-guard.ps1` — a **PreToolUse** guard wired in [`../settings.json`](../settings.json)
(matcher `Write|Edit`). It reads the event's `agent_type` and hard-enforces only the
**load-bearing** boundaries, **by permission, not instruction**:

| Agent | Hard-blocked from |
|-------|-------------------|
| `developer`   | `tests/acceptance/` |
| `test-author` | `src/` |
| `architect`   | `src/`, `tests/` |
| `validator`   | anything (read-only) |

Two boundaries actually matter, and only those are enforced: only the **test-author** writes
`tests/acceptance/` (so no agent certifies its own work — principle 4), and `src/` is the
**developer's**. The `tests/unit/` split (developer-owned unit tests) is **convention** — stated in
the agent docs, not policed here. No active agent ⇒ the human **coordinator**, who is unrestricted.
Allowed calls pass through to the normal permission flow; denials return `permissionDecision: "deny"`
with a reason.

Notes:
- Covers the **Write/Edit** tools only — it does not police file writes made through `Bash`.
- PowerShell is used because it is always present on this repo's Windows dev host; `python` / `uv`
  are not guaranteed on PATH before phase 001 provisions them.
- Hook changes take effect on the next session start (or after `/hooks` reload); Claude Code may ask
  you to review/approve the hook the first time.
