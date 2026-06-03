#Requires -Version 5.1
<#
  role-guard.ps1 - PreToolUse separation-of-duties guard.

  Hard-enforces ONLY the load-bearing boundaries, by PERMISSION (not instruction):
    - tests/acceptance/ is written solely by the test-author (no agent grades its own homework)
    - src/ is written solely by the developer
  By role:
    developer    -> may NOT write tests/acceptance/    (writes src/ + unit tests)
    test-author  -> may NOT write src/                 (writes acceptance tests)
    architect    -> may NOT write src/ or tests/       (design only: plan.md + interfaces)
    validator    -> may NOT write anything             (read-only)
  The tests/unit/ split (developer-owned) is CONVENTION - see the agent docs - not policed here.
  When no agent is active (the human coordinator), nothing is restricted.

  Reads the PreToolUse event JSON on stdin and emits a deny decision as documented at
  https://code.claude.com/docs/en/hooks  (hookSpecificOutput.permissionDecision).
  Allowed calls exit 0 with no output, so the normal permission flow still applies.
  Scope: guards the Write/Edit tools only (see the matcher in .claude/settings.json);
  file writes made through Bash are out of scope of this guard.
#>

function Allow { exit 0 }

function Deny([string]$reason) {
  @{
    hookSpecificOutput = @{
      hookEventName            = 'PreToolUse'
      permissionDecision       = 'deny'
      permissionDecisionReason = $reason
    }
  } | ConvertTo-Json -Compress -Depth 5
  exit 0
}

try { $raw = [Console]::In.ReadToEnd() } catch { Allow }
if ([string]::IsNullOrWhiteSpace($raw)) { Allow }

# Fail open on a malformed event: a guard must never wedge the session.
try { $evt = $raw | ConvertFrom-Json } catch { Allow }

$role = [string]$evt.agent_type
if ([string]::IsNullOrWhiteSpace($role)) { Allow }   # human coordinator: unrestricted

$file = [string]$evt.tool_input.file_path
if ([string]::IsNullOrWhiteSpace($file)) { Allow }   # tool is not writing a file

$root = [string]$evt.cwd
if ([string]::IsNullOrWhiteSpace($root)) { $root = (Get-Location).Path }

try {
  if (-not [System.IO.Path]::IsPathRooted($file)) { $file = Join-Path $root $file }
  $sep      = [System.IO.Path]::DirectorySeparatorChar
  $fileFull = [System.IO.Path]::GetFullPath($file)
  $srcDir   = [System.IO.Path]::GetFullPath((Join-Path $root 'src'))              + $sep
  $testsDir = [System.IO.Path]::GetFullPath((Join-Path $root 'tests'))            + $sep
  $accDir   = [System.IO.Path]::GetFullPath((Join-Path $root 'tests\acceptance')) + $sep
} catch { Allow }

$inSrc   = $fileFull.StartsWith($srcDir,   [System.StringComparison]::OrdinalIgnoreCase)
$inTests = $fileFull.StartsWith($testsDir, [System.StringComparison]::OrdinalIgnoreCase)
$inAcc   = $fileFull.StartsWith($accDir,   [System.StringComparison]::OrdinalIgnoreCase)

switch ($role) {
  'developer' {
    if ($inAcc) {
      Deny "Separation of duties (principle 4): the 'developer' agent must not create or edit acceptance tests (tests/acceptance/) - those are the test-author's. If an acceptance test looks wrong, report it to the coordinator rather than changing it."
    }
  }
  'test-author' {
    if ($inSrc) {
      Deny "Separation of duties (principle 4): the 'test-author' agent writes tests (acceptance) and must not write implementation (src/)."
    }
  }
  'architect' {
    if ($inSrc -or $inTests) {
      Deny "Role boundary: the 'architect' agent designs (plan.md + interfaces) and must not write implementation (src/) or tests (tests/)."
    }
  }
  'validator' {
    Deny "Role boundary: the 'validator' agent is read-only and must never modify files."
  }
}

Allow
