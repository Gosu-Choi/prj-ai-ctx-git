@echo off
setlocal EnableExtensions

set "REPO_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO_DIR%scripts\windows\stop-ctxgit.ps1"
if errorlevel 1 pause
