$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RunDir = Join-Path $Root ".run"
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
  throw "Backend virtual environment is missing. See README.md for setup."
}
if (-not (Test-Path (Join-Path $Root "frontend\node_modules"))) {
  throw "Frontend dependencies are missing. Run npm install in frontend."
}

$ApiArguments = @("-m", "uvicorn", "edusci.app:app", "--host", "127.0.0.1", "--port", "8000", "--reload")
$EnvFile = Join-Path $Root ".env"
if (Test-Path $EnvFile) {
  $ApiArguments += @("--env-file", $EnvFile)
}

$Api = Start-Process -FilePath $Python -ArgumentList $ApiArguments -WorkingDirectory (Join-Path $Root "backend") -RedirectStandardOutput (Join-Path $RunDir "api.log") -RedirectStandardError (Join-Path $RunDir "api-error.log") -WindowStyle Hidden -PassThru
$Web = Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev", "--", "--host", "127.0.0.1" -WorkingDirectory (Join-Path $Root "frontend") -RedirectStandardOutput (Join-Path $RunDir "web.log") -RedirectStandardError (Join-Path $RunDir "web-error.log") -WindowStyle Hidden -PassThru

@{ api = $Api.Id; web = $Web.Id } | ConvertTo-Json | Set-Content (Join-Path $RunDir "pids.json")
Write-Host "EduSci started:"
Write-Host "  Web  http://127.0.0.1:5173"
Write-Host "  API  http://127.0.0.1:8000/docs"
Write-Host "Logs: $RunDir; stop with scripts\stop.ps1"
