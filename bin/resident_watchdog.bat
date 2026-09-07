@echo off
rem aag 常驻服务自愈·每 15min 兜底拉起(2026-09-07 MoA 新增)
rem 背景: 四个登录自启任务(serve/console/workbench/omniroute)崩溃或被电池事件停掉后,
rem       下次触发要等重新登录——数据站会静默死掉。本任务每 15min 依次调四个幂等 bat
rem       (端口在听即零副作用退出), 实现崩溃最长 15min 自愈。
rem 登记: schtasks /create /tn "aag-resident-watchdog" /tr "wscript.exe <项目路径>\bin\silent_run.vbs <项目路径>\bin\resident_watchdog.bat" /sc minute /mo 15 /f
cd /d "%~dp0"
call serve_task.bat
call console_task.bat
call workbench_task.bat
call omniroute_task.bat
exit /b 0
