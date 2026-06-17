param(
  [Parameter(Position = 0)]
  [int]$Port = 0
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path

function Import-DotEnv {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return }
  Get-Content -LiteralPath $Path | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    if ($line.StartsWith("export ")) { $line = $line.Substring(7).Trim() }
    $index = $line.IndexOf("=")
    if ($index -lt 1) { return }
    $key = $line.Substring(0, $index).Trim()
    $value = $line.Substring($index + 1).Trim().Trim('"').Trim("'")
    if ($key -and -not [Environment]::GetEnvironmentVariable($key, "Process")) {
      [Environment]::SetEnvironmentVariable($key, $value, "Process")
    }
  }
}

function Get-CtxgitServerProcess {
  param([int]$ListenPort)
  $connections = Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue
  $pids = @($connections | Select-Object -ExpandProperty OwningProcess -Unique)
  if (-not $pids.Count) { return @() }
  Get-CimInstance Win32_Process |
    Where-Object {
      $pids -contains $_.ProcessId -and
      $_.CommandLine -match "ctxgit\.py" -and
      $_.CommandLine -match "\bserve\b"
    }
}

Import-DotEnv (Join-Path $RepoRoot ".env")

if (-not $Port) { $Port = if ($env:CTXGIT_PORT) { [int]$env:CTXGIT_PORT } else { 8766 } }

$targets = @(Get-CtxgitServerProcess -ListenPort $Port)
if (-not $targets.Count) {
  Write-Host "No ctxgit server found on port $Port."
  exit 0
}

foreach ($target in $targets) {
  Write-Host "Stopping ctxgit server PID $($target.ProcessId)"
  Stop-Process -Id $target.ProcessId -Force -ErrorAction SilentlyContinue
}

$pidPath = Join-Path $RepoRoot ".ctxgit\server-$Port.pid"
Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
Write-Host "ctxgit server stopped on port $Port."
