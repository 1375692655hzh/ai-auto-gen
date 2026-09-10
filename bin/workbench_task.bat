@echo off
rem aag 工作台 workbench(8788)·登录自启/兜底拉起(幂等: 8788 已在听则直接退出)
rem 登记: schtasks /create /tn "aag-workbench" /tr "wscript.exe <项目路径>\bin\silent_run.vbs <项目路径>\bin\workbench_task.bat" /sc onlogon /f
rem 另由 aag-resident-watchdog 每 15min 兜底调用(崩溃自愈, 端口在听即零副作用退出)
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
cd /d "%~dp0.."
netstat -ano | findstr ":8788" | findstr LISTENING >nul && exit /b 0
netstat -ano | findstr ":8788" | findstr TIME_WAIT >nul && exit /b 0
rem 拉起走 run_detached.py(DETACHED_PROCESS): start /b 在 wscript/计划任务链下会被父退
rem 出连带杀死(实测 60s 内必死不绑端口); 分离进程不挂父控制台, 随会话结束存活。
rem 等 8 秒复查: 没绑上端口说明拉起失败, 退出码 3 供 silent_run 透传/看门狗计数。
py -3.11 bin\run_detached.py workbench serve
timeout /t 8 /nobreak >nul
netstat -ano | findstr ":8788" | findstr LISTENING >nul && exit /b 0
exit /b 3
