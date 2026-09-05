@echo off
rem aag 工作台 workbench(8788)·登录自启/兜底拉起(幂等: 8788 已在听则直接退出)
rem 登记: schtasks /create /tn "aag-workbench" /tr "wscript.exe <项目路径>\bin\silent_run.vbs <项目路径>\bin\workbench_task.bat" /sc onlogon /f
set PYTHONUTF8=1
cd /d "%~dp0.."
netstat -ano | findstr "127.0.0.1:8788" | findstr LISTENING >nul && exit /b 0
if not exist data mkdir data
where py >nul 2>nul && (start "" /b cmd /c "py -3.11 cli.py workbench serve >> data\workbench_task.log 2>&1") || (start "" /b cmd /c "python cli.py workbench serve >> data\workbench_task.log 2>&1")
exit /b 0
