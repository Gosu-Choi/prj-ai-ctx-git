param(
  [switch]$NoPath
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BinPath = Join-Path $RepoRoot "bin"
$CmdPath = Join-Path $BinPath "ctxgit.cmd"

if (!(Test-Path $CmdPath)) {
  throw "Missing $CmdPath"
}

if (-not $NoPath) {
  $CurrentPath = [Environment]::GetEnvironmentVariable("Path", "User")
  $Parts = @()
  if ($CurrentPath) {
    $Parts = $CurrentPath -split ";" | Where-Object { $_ -ne "" }
  }
  $AlreadyInstalled = $Parts | Where-Object { $_.TrimEnd("\") -ieq $BinPath.TrimEnd("\") }
  if (-not $AlreadyInstalled) {
    $NextPath = (@($BinPath) + $Parts) -join ";"
    [Environment]::SetEnvironmentVariable("Path", $NextPath, "User")
  }
}

Write-Host "ctxgit installed for Windows."
Write-Host "Repo: $RepoRoot"
Write-Host "Bin:  $BinPath"
Write-Host ""
Write-Host "Open a new PowerShell window, then run:"
Write-Host "  ctxgit --help"
