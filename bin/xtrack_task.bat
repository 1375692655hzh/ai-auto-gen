@echo off
rem aag X账号追踪采集·任务计划专用(相对路径自适应; 日志落盘 data\xtrack_task.log)
rem 登记(每小时, 与 :00/:07/:15 相位错开): schtasks /create /tn "aag-xtrack-refresh" /tr "wscript.exe <项目路径>\bin\silent_run.vbs <项目路径>\bin\xtrack_task.bat" /sc hourly /st 00:11 /f
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
cd /d "%~dp0.."
if not exist data mkdir data
if exist data\xtrack_task.log for %%F in (data\xtrack_task.log) do if %%~zF gtr 5242880 move /y data\xtrack_task.log data\xtrack_task.1.log >nul 2>&1
echo ===== %date% %time% 轮开始 ===== >> data\xtrack_task.log
where py >nul 2>nul
if errorlevel 1 (
  python -u cli.py workbench refresh-x-track >> data\xtrack_task.log 2>&1
) else (
  py -3.11 -u cli.py workbench refresh-x-track >> data\xtrack_task.log 2>&1
)
set AAG_RC=%errorlevel%
echo ===== %date% %time% 轮结束 rc=%AAG_RC% ===== >> data\xtrack_task.log
exit /b %AAG_RC%
