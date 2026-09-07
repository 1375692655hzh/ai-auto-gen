@echo off
rem aag X起爆帖互动采集·任务计划专用(相对路径自适应; 日志落盘 data\xsurge_task.log)
rem 登记(与 sources-refresh 错相 7 分钟): schtasks /create /tn "aag-xsurge-refresh" /tr "wscript.exe <项目路径>\bin\silent_run.vbs <项目路径>\bin\xsurge_task.bat" /sc minute /mo 15 /st 00:07 /f
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
cd /d "%~dp0.."
if not exist data mkdir data
if exist data\xsurge_task.log for %%F in (data\xsurge_task.log) do if %%~zF gtr 5242880 move /y data\xsurge_task.log data\xsurge_task.1.log >nul 2>&1
echo ===== %date% %time% 轮开始 ===== >> data\xsurge_task.log
where py >nul 2>nul
if errorlevel 1 (
  python -u cli.py workbench refresh-x-surge >> data\xsurge_task.log 2>&1
) else (
  py -3.11 -u cli.py workbench refresh-x-surge >> data\xsurge_task.log 2>&1
)
set AAG_RC=%errorlevel%
echo ===== %date% %time% 轮结束 rc=%AAG_RC% ===== >> data\xsurge_task.log
exit /b %AAG_RC%
