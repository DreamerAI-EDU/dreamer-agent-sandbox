<#
.SYNOPSIS
    PR-5 local trilingual harness launcher (§8.3 「CI ＋ 本地人工过三语」).

.DESCRIPTION
    Starts the aiohttp backend on http://127.0.0.1:8001 (the port frontend/vite.config.ts
    proxies /api to) against the throw-away harness database, and/or the Vite dev
    server on http://localhost:3000.

    Nothing here touches the production database: DREAMER_DB_PATH is set to
    .pr5_harness/pr5_harness.db for the backend process only.

.PARAMETER Seed
    Rebuild the harness DB (1 teacher + 1 class + 1 student + 3 weeks of scores +
    3 approved reports: en / zh-hk / zh-cn) before starting the backend.
    The previous DB file is renamed aside as *.bak-<timestamp>, never deleted.

.PARAMETER Backend
    Start only the backend.

.PARAMETER Frontend
    Start only the Vite dev server (runs `npm ci` first when node_modules is missing).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/pr5_start_local.ps1 -Seed

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/pr5_start_local.ps1 -Frontend

.NOTES
    With no switch both halves start (seed is NOT re-run).
#>
[CmdletBinding()]
param(
    [switch]$Seed,
    [switch]$Backend,
    [switch]$Frontend
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$harnessDb = Join-Path $repoRoot '.pr5_harness\pr5_harness.db'

if (-not (Test-Path $python)) {
    throw "venv interpreter not found: $python (run python -m venv .venv first)"
}

# No switch at all -> start both halves.
if (-not $Backend -and -not $Frontend) {
    $Backend = $true
    $Frontend = $true
}

if ($Backend) {
    if ($Seed) {
        Write-Host '==> seeding harness DB ...' -ForegroundColor Cyan
        Push-Location $repoRoot
        try {
            & $python 'scripts\pr5_seed_local.py' '--reset'
            if ($LASTEXITCODE -ne 0) { throw "seed failed (exit $LASTEXITCODE)" }
        }
        finally {
            Pop-Location
        }
    }
    elseif (-not (Test-Path $harnessDb)) {
        throw "harness DB missing: $harnessDb - re-run with -Seed"
    }

    $env:DREAMER_DB_PATH = $harnessDb
    $backendCode = "from aiohttp import web; from auth.api import build_app; web.run_app(build_app(), host='127.0.0.1', port=8001)"
    Write-Host '==> backend  http://127.0.0.1:8001  (DREAMER_DB_PATH=' -NoNewline -ForegroundColor Cyan
    Write-Host $harnessDb -NoNewline
    Write-Host ')' -ForegroundColor Cyan
    Start-Process -FilePath $python `
        -ArgumentList @('-c', $backendCode) `
        -WorkingDirectory $repoRoot `
        -WindowStyle Normal
}

if ($Frontend) {
    $frontendDir = Join-Path $repoRoot 'frontend'
    Push-Location $frontendDir
    try {
        if (-not (Test-Path (Join-Path $frontendDir 'node_modules'))) {
            Write-Host '==> npm ci ...' -ForegroundColor Cyan
            npm ci
            if ($LASTEXITCODE -ne 0) { throw "npm ci failed (exit $LASTEXITCODE)" }
        }
        Write-Host '==> frontend http://localhost:3000' -ForegroundColor Cyan
        Write-Host '    /teacher/login  /teacher/scores  /teacher/reports  /teacher/crosswalk'
        Write-Host '    /parent/reports (three languages already approved in the seed)'
        npm run dev
    }
    finally {
        Pop-Location
    }
}
