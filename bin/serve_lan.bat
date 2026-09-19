@echo off
rem aag 供数服务·局域网模式(双击即用, 相对路径自适应任何机器)
title aag sources serve (LAN 0.0.0.0:8787)
set PYTHONUTF8=1
cd /d "%~dp0.."
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
%PYEXE% cli.py sources serve --bind 0.0.0.0 --port 8787
echo. & echo [serve exited] press any key to close... & pause >nul
