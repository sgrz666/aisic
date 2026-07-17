$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function Assert-CommandSucceeded([string]$Name) {
  if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE" }
}

& (Join-Path $PSScriptRoot "security-check.ps1") -Root $Root
Assert-CommandSucceeded "Repository security scan"

Push-Location (Join-Path $Root "backend")
try {
  & ".\.venv\Scripts\python.exe" -m ruff check edusci tests
  Assert-CommandSucceeded "Backend lint"
  & ".\.venv\Scripts\python.exe" -m pytest tests -q --cov=edusci --cov-report=term-missing:skip-covered --cov-fail-under=85 -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
  Assert-CommandSucceeded "Backend tests"
} finally { Pop-Location }

& (Join-Path $PSScriptRoot "eval-quality.ps1") -Mode Offline
Assert-CommandSucceeded "Offline research quality evaluation"

Push-Location (Join-Path $Root "frontend")
try {
  npm test -- --run
  Assert-CommandSucceeded "Frontend tests"
  npm run build
  Assert-CommandSucceeded "Frontend build"
} finally { Pop-Location }
