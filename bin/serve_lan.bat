@echo off
rem aag 供数服务·局域网模式(双击即用, 相对路径自适应任何机器)
title aag sources serve (LAN 0.0.0.0:8787)
set PYTHONUTF8=1
cd /d "%~dp0.."
where py >nul 2>nul && (py -3.11 cli.py sources serve --bind 0.0.0.0 --port 8787) || (python cli.py sources serve --bind 0.0.0.0 --port 8787)
echo. & echo [serve exited] press any key to close... & pause >nul
