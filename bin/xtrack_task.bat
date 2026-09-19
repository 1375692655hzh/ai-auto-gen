@echo off
rem aag X账号追踪采集·任务计划专用(相对路径自适应; 日志落盘 data\xtrack_task.log)
rem 登记(每小时 :33 相位, 呼应 8:30 统计锚点; 页内「定时」按钮自带电池限制/错过补跑补丁): schtasks /create /tn "aag-xtrack-refresh" /tr "wscript.exe <项目路径>\bin\silent_run.vbs <项目路径>\bin\xtrack_task.bat" /sc hourly /st 00:33 /f
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
cd /d "%~dp0.."
if not exist data mkdir data
if exist data\xtrack_task.log for %%F in (data\xtrack_task.log) do if %%~zF gtr 5242880 move /y data\xtrack_task.log data\xtrack_task.1.log >nul 2>&1
echo ===== %date% %time% 轮开始 ===== >> data\xtrack_task.log
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
%PYEXE% -u cli.py workbench refresh-x-track >> data\xtrack_task.log 2>&1
set AAG_RC=%errorlevel%
echo ===== %date% %time% 轮结束 rc=%AAG_RC% ===== >> data\xtrack_task.log
exit /b %AAG_RC%
