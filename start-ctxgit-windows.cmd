@echo off
setlocal EnableExtensions

set "REPO_DIR=%~dp0"
set "PROJECT_ROOT="

if defined CTXGIT_ROOT set "PROJECT_ROOT=%CTXGIT_ROOT%"

if not defined PROJECT_ROOT if exist "%REPO_DIR%.env" (
  for /f "usebackq tokens=1,* delims==" %%A in ("%REPO_DIR%.env") do (
    if /I "%%A"=="CTXGIT_ROOT" set "PROJECT_ROOT=%%~B"
  )
)

if not defined PROJECT_ROOT if exist "%REPO_DIR%..\..\Lit review\" (
  set "PROJECT_ROOT=%REPO_DIR%..\..\Lit review"
)

if not defined PROJECT_ROOT set "PROJECT_ROOT=%REPO_DIR%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO_DIR%scripts\windows\start-ctxgit.ps1" "%PROJECT_ROOT%"
if errorlevel 1 pause
