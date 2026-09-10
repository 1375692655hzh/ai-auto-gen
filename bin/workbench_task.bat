@echo off
rem aag workbench(8788) resident starter (idempotent: exit 0 if already LISTENING)
rem registered in schtasks as aag-workbench (onlogon) + called by aag-resident-watchdog every 15min
rem NOTE: keep this file pure ASCII -- non-ASCII comments break under GBK cmd parsing
rem (2026-09-11 incident: UTF-8 comment bytes swallowed the timeout line -> rc=3 loop).
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
cd /d "%~dp0.."
netstat -ano | findstr ":8788" | findstr LISTENING >nul && exit /b 0
rem launch via run_detached.py (DETACHED_PROCESS): start /b gets killed when the parent
rem (wscript/scheduled task) exits; detached survives. Wait 8s then re-check the port;
rem exit 3 if bind failed (silent_run passes the code through; watchdog counts it).
py -3.11 bin\run_detached.py workbench serve
timeout /t 8 /nobreak >nul
netstat -ano | findstr ":8788" | findstr LISTENING >nul && exit /b 0
exit /b 3
