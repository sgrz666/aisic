param(
  [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
$CredentialPattern = 'sk-[A-Za-z0-9_-]{20,}|DASHSCOPE_API_KEY=[A-Za-z0-9_-]{20,}'

Push-Location $Root
try {
  git rev-parse --is-inside-work-tree *> $null
  if ($LASTEXITCODE -ne 0) { throw "Security scan requires a Git worktree" }

  $worktreeHits = @(git grep -l -I -E $CredentialPattern -- . 2>$null)
  if ($LASTEXITCODE -notin @(0, 1)) { throw "Unable to scan tracked files" }

  $historyHits = @()
  foreach ($commit in @(git rev-list --all)) {
    git grep -q -I -E $CredentialPattern $commit -- . 2>$null
    if ($LASTEXITCODE -eq 0) {
      $historyHits += $commit
    } elseif ($LASTEXITCODE -ne 1) {
      throw "Unable to scan commit $commit"
    }
  }

  if ($worktreeHits.Count -gt 0 -or $historyHits.Count -gt 0) {
    Write-Error (
      "Credential-like values detected. Tracked files: {0}; commits: {1}. " +
      "Values are intentionally redacted."
    ) -f $worktreeHits.Count, $historyHits.Count
    exit 1
  }

  Write-Output "Security scan passed: tracked files and Git history contain no credential-like values."
} finally {
  Pop-Location
}
