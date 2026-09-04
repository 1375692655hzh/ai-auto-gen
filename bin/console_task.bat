@echo off
rem aag 数据站控制台(8786)·登录自启/兜底拉起(幂等: 8786 已在听则直接退出)
rem 登记: schtasks /create /tn "aag-console" /tr "<项目路径>\bin\console_task.bat" /sc onlogon /f
set PYTHONUTF8=1
cd /d "%~dp0.."
netstat -ano | findstr "127.0.0.1:8786" | findstr LISTENING >nul && exit /b 0
if not exist data mkdir data
start "" /min cmd /c "py -3.11 cli.py sources console >> data\console_task.log 2>&1"
exit /b 0
