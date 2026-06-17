param(
  [Parameter(Position = 0)]
  [string]$Root = "",
  [string]$HostAddress = "",
  [int]$Port = 0,
  [switch]$Foreground,
  [switch]$RequireRoot
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$CtxgitPy = Join-Path $RepoRoot "tools\ctxgit\ctxgit.py"

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

function Resolve-PythonCommand {
  function Test-PythonVersion {
    param([string]$File, [string[]]$Prefix = @())
    try {
      & $File @Prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
      return $LASTEXITCODE -eq 0
    } catch {
      return $false
    }
  }

  $localPrograms = Join-Path $env:LOCALAPPDATA "Programs\Python"
  if (Test-Path -LiteralPath $localPrograms) {
    $candidates = Get-ChildItem -LiteralPath $localPrograms -Directory -Filter "Python*" |
      Sort-Object Name -Descending |
      ForEach-Object { Join-Path $_.FullName "python.exe" } |
      Where-Object { Test-Path -LiteralPath $_ }
    foreach ($candidate in $candidates) {
      if (Test-PythonVersion -File $candidate) { return @{ File = $candidate; Prefix = @() } }
    }
  }

  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python -and (Test-PythonVersion -File $python.Source)) {
    return @{ File = $python.Source; Prefix = @() }
  }

  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    foreach ($version in @("-3.12", "-3.11", "-3.10", "-3")) {
      if (Test-PythonVersion -File $py.Source -Prefix @($version)) {
        return @{ File = $py.Source; Prefix = @($version) }
      }
    }
  }

  throw "Python 3.10+ was not found. Install Python 3.10 or newer, or add it to PATH."
}

function Quote-Arg {
  param([string]$Value)
  if ($Value -notmatch '[\s"]') { return $Value }
  return '"' + ($Value -replace '"', '\"') + '"'
}

function Normalize-PathValue {
  param([string]$Value)
  return ("" + $Value).Trim().Trim('"').Trim("'")
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

if (-not $HostAddress) { $HostAddress = if ($env:CTXGIT_HOST) { $env:CTXGIT_HOST } else { "127.0.0.1" } }
if (-not $Port) { $Port = if ($env:CTXGIT_PORT) { [int]$env:CTXGIT_PORT } else { 8766 } }
if (-not $Root) { $Root = $env:CTXGIT_ROOT }
$Root = Normalize-PathValue $Root
if (-not $Root -and $RequireRoot) {
  throw "CTXGIT_ROOT is not set. Set CTXGIT_ROOT in this repository's .env file, or run scripts\windows\start-ctxgit.ps1 with a project root argument."
}
if ($Root) {
  try {
    $Root = (Resolve-Path -LiteralPath $Root).Path
  } catch {
    throw "Project root does not exist or is invalid: $Root"
  }
}

$existing = @(Get-CtxgitServerProcess -ListenPort $Port)
if ($existing.Count) {
  Write-Host "ctxgit server is already running on http://${HostAddress}:$Port/"
  $existing | ForEach-Object { Write-Host "PID $($_.ProcessId): $($_.CommandLine)" }
  exit 0
}

$python = Resolve-PythonCommand
$argumentList = @($python.Prefix + @($CtxgitPy))
if ($Root) {
  $argumentList += @("--root", $Root)
}
$argumentList += @("serve", "--host", $HostAddress, "--port", [string]$Port)

if ($Foreground) {
  & $python.File @argumentList
  exit $LASTEXITCODE
}

$logDir = Join-Path $RepoRoot ".ctxgit\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stdoutPath = Join-Path $logDir "server-$Port.out.log"
$stderrPath = Join-Path $logDir "server-$Port.err.log"
$pidPath = Join-Path $RepoRoot ".ctxgit\server-$Port.pid"
$argumentText = ($argumentList | ForEach-Object { Quote-Arg $_ }) -join " "

$process = Start-Process `
  -FilePath $python.File `
  -ArgumentList $argumentText `
  -WorkingDirectory $RepoRoot `
  -WindowStyle Hidden `
  -RedirectStandardOutput $stdoutPath `
  -RedirectStandardError $stderrPath `
  -PassThru

Set-Content -LiteralPath $pidPath -Value $process.Id -Encoding ASCII

$url = "http://${HostAddress}:$Port/"
$deadline = (Get-Date).AddSeconds(10)
$started = $false
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Milliseconds 300
  $process.Refresh()
  if ($process.HasExited) {
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
    $stderr = if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Tail 40 -ErrorAction SilentlyContinue } else { @() }
    throw "ctxgit server exited during startup. STDERR: $($stderr -join ' ')"
  }
  try {
    Invoke-WebRequest -UseBasicParsing -Uri "${url}api/auth/status" -TimeoutSec 1 | Out-Null
    $started = $true
    break
  } catch {
  }
}
if (-not $started) {
  throw "ctxgit server process started but did not respond at $url within 10 seconds."
}

Write-Host "ctxgit server started: http://${HostAddress}:$Port/"
Write-Host "PID: $($process.Id)"
Write-Host "Root: $(if ($Root) { $Root } else { '(none; open a project in the browser)' })"
Write-Host "Logs: $stdoutPath ; $stderrPath"
