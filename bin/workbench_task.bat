@echo off
rem aag 工作台 workbench(8788)·登录自启/兜底拉起(幂等: 8788 已在听则直接退出)
rem 登记: schtasks /create /tn "aag-workbench" /tr "wscript.exe <项目路径>\bin\silent_run.vbs <项目路径>\bin\workbench_task.bat" /sc onlogon /f
rem 另由 aag-resident-watchdog 每 15min 兜底调用(崩溃自愈, 端口在听即零副作用退出)
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
cd /d "%~dp0.."
netstat -ano | findstr ":8788" | findstr LISTENING >nul && exit /b 0
if not exist data mkdir data
where py >nul 2>nul
if errorlevel 1 (
  start "" /b cmd /c "python -u cli.py workbench serve >> data\workbench_task.log 2>&1"
) else (
  start "" /b cmd /c "py -3.11 -u cli.py workbench serve >> data\workbench_task.log 2>&1"
)
exit /b 0
