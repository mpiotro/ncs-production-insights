#Requires -Version 5.1
<#
.SYNOPSIS
    Start the entire NCS Production Insights stack locally — the 003 API + the 004 dashboard.

.DESCRIPTION
    One command to run the whole solution on your machine:
      1. checks prerequisites (uv for the backend, node/npm for the frontend);
      2. installs dependencies (uv sync; npm ci if frontend/node_modules is missing);
      3. ensures a DuckDB store exists — seeds a synthetic, forecast-bearing DEMO store
         (scripts/seed_demo.py, no network) if there is none;
      4. starts the read-only API (uvicorn) and waits for /health;
      5. starts the Vite dashboard pointed at that API;
      6. prints the URLs and runs until you press Ctrl+C, then stops both servers.

    For REAL SODIR data instead of the demo store, build it first with
    `python -m ncs.api.seed` (see README "Running the app") and pass its path via -DbPath.

.PARAMETER DbPath
    DuckDB store path (default: ncs-local.duckdb in the repo root). If it does not exist, a demo
    store is seeded there. Point this at a store built by `python -m ncs.api.seed` to serve real data.

.PARAMETER ApiPort
    Port for the 003 API (default: 8003).

.PARAMETER WebPort
    Port for the 004 dashboard dev server (default: 5173 — the API's default CORS origin).

.PARAMETER Reseed
    Rebuild the demo store even if the DbPath file already exists.

.PARAMETER Mock
    Skip the backend entirely and run the dashboard against its built-in typed mock (no API, no store).

.EXAMPLE
    ./scripts/start-local.ps1
.EXAMPLE
    ./scripts/start-local.ps1 -Reseed
.EXAMPLE
    ./scripts/start-local.ps1 -Mock
.EXAMPLE
    ./scripts/start-local.ps1 -DbPath ncs.duckdb   # serve a store you built from real SODIR data
#>
[CmdletBinding()]
param(
    [string]$DbPath  = "ncs-local.duckdb",
    [int]   $ApiPort = 8003,
    [int]   $WebPort = 5173,
    [switch]$Reseed,
    [switch]$Mock
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Resolve-Tool([string]$Name, [string]$Hint) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "Required tool '$Name' not found on PATH. $Hint" }
    return $cmd.Source
}

function Stop-OnPort([int]$Port) {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($procId in ($conns.OwningProcess | Select-Object -Unique)) {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "==> Checking prerequisites..."
$uv  = Resolve-Tool uv  "Install uv: https://docs.astral.sh/uv/"
$npm = Resolve-Tool npm "Install Node 20+ (bundles npm): https://nodejs.org/"

Write-Host "==> Installing backend dependencies (uv sync)..."
& $uv sync

if (-not (Test-Path (Join-Path $RepoRoot "frontend/node_modules"))) {
    Write-Host "==> Installing frontend dependencies (npm ci)..."
    Push-Location (Join-Path $RepoRoot "frontend")
    try { & $npm ci } finally { Pop-Location }
}

$procs = [System.Collections.Generic.List[object]]::new()
# 127.0.0.1, not "localhost": uvicorn binds IPv4 only (--host 127.0.0.1), but on Windows
# "localhost" resolves to ::1 (IPv6) first, so a localhost health probe times out and never
# reaches the server. Using the literal IPv4 address keeps the health gate and the dashboard's
# API calls pointed at the address uvicorn is actually listening on.
$ApiBase = "http://127.0.0.1:$ApiPort"

try {
    if (-not $Mock) {
        $DbFull = if ([System.IO.Path]::IsPathRooted($DbPath)) { $DbPath } else { Join-Path $RepoRoot $DbPath }
        if ($Reseed -and (Test-Path $DbFull)) { Remove-Item $DbFull -Force }
        if (-not (Test-Path $DbFull)) {
            Write-Host "==> Seeding demo store at $DbPath (synthetic data; no network)..."
            & $uv run python (Join-Path $RepoRoot "scripts/seed_demo.py") $DbFull
        }
        else {
            Write-Host "==> Using existing store $DbPath"
        }

        Write-Host "==> Starting API at $ApiBase ..."
        $env:NCS_DB_PATH      = $DbFull
        $env:API_PORT         = "$ApiPort"
        $env:API_CORS_ORIGINS = "http://localhost:$WebPort"
        $api = Start-Process -FilePath $uv -PassThru -NoNewWindow -ArgumentList @(
            "run", "python", "-m", "uvicorn",
            "ncs.api.app:create_app", "--factory", "--host", "127.0.0.1", "--port", "$ApiPort"
        )
        $procs.Add($api)

        Write-Host "    waiting for the API to come up..."
        $up = $false
        for ($i = 0; $i -lt 60; $i++) {
            try { Invoke-RestMethod "$ApiBase/health" -TimeoutSec 2 | Out-Null; $up = $true; break }
            catch { Start-Sleep -Milliseconds 500 }
        }
        if (-not $up) { throw "API did not become healthy on $ApiBase (see output above)." }
        Write-Host "    API healthy."
    }

    Write-Host "==> Starting dashboard at http://localhost:$WebPort ..."
    if ($Mock) {
        $env:VITE_API_SOURCE = "mock"
        Remove-Item Env:\VITE_API_BASE_URL -ErrorAction SilentlyContinue
    }
    else {
        $env:VITE_API_SOURCE   = "http"
        $env:VITE_API_BASE_URL = $ApiBase
    }
    Push-Location (Join-Path $RepoRoot "frontend")
    try {
        # npm is a .cmd shim on Windows; Start-Process can't track it directly (the shim exits
        # immediately, tripping the liveness check below). Launch it via cmd.exe, which stays
        # alive as the parent of the long-running node/vite child.
        $web = Start-Process -FilePath "$env:ComSpec" -PassThru -NoNewWindow -ArgumentList @(
            "/c", "`"$npm`"", "run", "dev", "--", "--port", "$WebPort", "--strictPort"
        )
    }
    finally { Pop-Location }
    $procs.Add($web)

    Write-Host ""
    Write-Host "  NCS Production Insights is running:" -ForegroundColor Green
    if (-not $Mock) { Write-Host "    API:       $ApiBase   (OpenAPI docs: $ApiBase/docs)" }
    Write-Host    "    Dashboard: http://localhost:$WebPort"
    Write-Host ""
    Write-Host "  Press Ctrl+C to stop."

    # Block until interrupted; bail out early if either server dies on its own.
    while ($true) {
        Start-Sleep -Seconds 1
        foreach ($p in $procs) {
            if ($p.HasExited) { throw "A server process exited unexpectedly (see output above)." }
        }
    }
}
finally {
    Write-Host "`n==> Stopping servers..."
    foreach ($p in $procs) {
        if ($p -and -not $p.HasExited) {
            # /T kills the whole tree (the npm/uv launcher and the node/python child it spawned).
            & taskkill.exe /PID $p.Id /T /F *> $null
        }
    }
    if (-not $Mock) { Stop-OnPort $ApiPort }
    Stop-OnPort $WebPort
    Write-Host "    done."
}
