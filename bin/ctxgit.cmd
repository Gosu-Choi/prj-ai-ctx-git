@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%.."
set "CTXGIT_PY=%REPO_ROOT%\tools\ctxgit\ctxgit.py"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 "%CTXGIT_PY%" %*
  exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
  python "%CTXGIT_PY%" %*
  exit /b %ERRORLEVEL%
)

echo ctxgit: Python 3 was not found. Install Python 3 or add it to PATH. 1>&2
exit /b 1
