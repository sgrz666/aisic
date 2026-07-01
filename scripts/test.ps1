$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function Assert-CommandSucceeded([string]$Name) {
  if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE" }
}

Push-Location (Join-Path $Root "backend")
try {
  & ".\.venv\Scripts\python.exe" -m pytest tests -q
  Assert-CommandSucceeded "Backend tests"
} finally { Pop-Location }

Push-Location (Join-Path $Root "frontend")
try {
  npm test -- --run
  Assert-CommandSucceeded "Frontend tests"
  npm run build
  Assert-CommandSucceeded "Frontend build"
} finally { Pop-Location }
