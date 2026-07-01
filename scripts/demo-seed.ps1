$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Push-Location (Join-Path $Root "backend")
try {
  & ".\.venv\Scripts\python.exe" -m scripts.seed_demo
  if ($LASTEXITCODE -ne 0) { throw "Demo seed failed with exit code $LASTEXITCODE" }
}
finally { Pop-Location }
