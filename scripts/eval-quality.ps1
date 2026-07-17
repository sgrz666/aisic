param(
  [ValidateSet("Offline", "LiveQwen")]
  [string]$Mode = "Offline",
  [string]$Output = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Backend virtual environment not found: $Python" }
if (-not $Output) { $Output = Join-Path $Root "artifacts\quality-report.json" }
$ResolvedMode = if ($Mode -eq "LiveQwen") { "live-qwen" } else { "offline" }

Push-Location (Join-Path $Root "backend")
try {
  & $Python -m edusci.evaluation --mode $ResolvedMode --output $Output
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
  Pop-Location
}

Write-Output "Quality report written to $Output"
