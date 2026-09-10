@echo off
rem aag 数据站 serve(8787)·登录自启/兜底拉起(幂等: 8787 已在听则直接退出)
rem 登记: schtasks /create /tn "aag-serve" /tr "wscript.exe <项目路径>\bin\silent_run.vbs <项目路径>\bin\serve_task.bat" /sc onlogon /f
rem 另由 aag-resident-watchdog 每 15min 兜底调用(崩溃自愈, 端口在听即零副作用退出)
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
cd /d "%~dp0.."
rem 只匹配端口号: serve_lan 绑 0.0.0.0 场景也能正确判活
netstat -ano | findstr ":8787" | findstr LISTENING >nul && exit /b 0
if not exist data mkdir data
where py >nul 2>nul
if errorlevel 1 (
  start "" /min cmd /c "python -u cli.py sources serve >> data\serve_task.log 2>&1"
) else (
  start "" /min cmd /c "py -3.11 -u cli.py sources serve >> data\serve_task.log 2>&1"
)
exit /b 0
