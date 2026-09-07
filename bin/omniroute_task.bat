@echo off
rem aag OmniRoute 翻译网关(20128)·登录自启/兜底拉起(幂等: 20128 已在听则直接退出)
rem 仅回环绑定(安全红线); 网关不在时翻译链自动落付费位, 本任务只恢复免费层
rem 登记: schtasks /create /tn "aag-omniroute" /tr "wscript.exe <项目路径>\bin\silent_run.vbs <项目路径>\bin\omniroute_task.bat" /sc onlogon /f
rem 另由 aag-resident-watchdog 每 15min 兜底调用(崩溃自愈, 端口在听即零副作用退出)
cd /d "%~dp0.."
netstat -ano | findstr ":20128" | findstr LISTENING >nul && exit /b 0
if not exist data mkdir data
set OMNIROUTE_SERVER_HOST=127.0.0.1
omniroute serve --daemon --no-open >> data\omniroute_task.log 2>&1
exit /b 0
