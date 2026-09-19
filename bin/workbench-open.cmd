@echo off
rem Double-click launcher for the workbench (2026-09-20): ensures the workbench
rem server (8788) is up -- and the local data station (8787) when settings point
rem to localhost -- then opens the browser. Safe to re-run; port-idempotent.
rem probe python launcher with fallback (2026-09-20: py -3.11 alone breaks on
rem Store-Python (no py launcher) or 3.12-only machines -- same fix as config.py_cmd)
set PYEXE=
py -3.11 -c "1" >nul 2>&1 && set PYEXE=py -3.11
if not defined PYEXE py -3 -c "1" >nul 2>&1 && set PYEXE=py -3
if not defined PYEXE python -c "1" >nul 2>&1 && set PYEXE=python
if not defined PYEXE (
  echo [ERROR] Python 3.10+ not found. Install from python.org and re-run.
  exit /b 1
)
%PYEXE% "%~dp0workbench-open.py" %*
if errorlevel 1 pause
