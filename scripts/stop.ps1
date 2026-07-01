$Root = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $Root ".run\pids.json"
if (-not (Test-Path $PidFile)) {
  Write-Host "No EduSci processes were recorded."
  exit 0
}

function Stop-ProcessTree([int]$ProcessId) {
  $Children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
  foreach ($Child in $Children) { Stop-ProcessTree -ProcessId $Child.ProcessId }
  $Process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
  if ($Process) { Stop-Process -Id $ProcessId -Force }
}

$Pids = Get-Content -Raw $PidFile | ConvertFrom-Json
foreach ($ProcessId in @($Pids.api, $Pids.web)) { Stop-ProcessTree -ProcessId $ProcessId }
Remove-Item -LiteralPath $PidFile
Write-Host "EduSci services stopped."
