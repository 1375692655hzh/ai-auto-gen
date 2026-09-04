@echo off
rem aag 数据站 serve(8787)·登录自启/兜底拉起(幂等: 8787 已在听则直接退出)
rem 登记: schtasks /create /tn "aag-serve" /tr "<项目路径>\bin\serve_task.bat" /sc onlogon /f
set PYTHONUTF8=1
cd /d "%~dp0.."
netstat -ano | findstr "127.0.0.1:8787" | findstr LISTENING >nul && exit /b 0
if not exist data mkdir data
where py >nul 2>nul && (start "" /min cmd /c "py -3.11 cli.py sources serve >> data\serve_task.log 2>&1") || (start "" /min cmd /c "python cli.py sources serve >> data\serve_task.log 2>&1")
exit /b 0
