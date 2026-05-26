param(
    [Parameter(Mandatory = $true)]
    [string]$Question,
    [int]$Budget = 2000,
    [switch]$SkipUpdate
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    throw "Missing virtualenv python at $PythonExe"
}

if (-not $SkipUpdate) {
    & $PythonExe -m graphify update "."
    if ($LASTEXITCODE -ne 0) {
        throw "graphify update failed"
    }
}

$GraphPath = Join-Path $RepoRoot "graphify-out\graph.json"
if (-not (Test-Path $GraphPath)) {
    throw "Missing graph file: $GraphPath"
}

& $PythonExe -m graphify query "$Question" --graph "$GraphPath" --budget $Budget
if ($LASTEXITCODE -ne 0) {
    throw "graphify query failed"
}
