$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function Assert-CommandSucceeded([string]$Name) {
  if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE" }
}

Push-Location (Join-Path $Root "backend")
try {
  & ".\.venv\Scripts\python.exe" -m pytest tests\test_e2e_routes.py -q
  Assert-CommandSucceeded "Four-route E2E"
} finally { Pop-Location }

Push-Location (Join-Path $Root "frontend")
try {
  npm run e2e
  Assert-CommandSucceeded "Browser E2E"
}
finally { Pop-Location }
