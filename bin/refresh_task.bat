@echo off
rem aag 数据站刷新·任务计划专用(相对路径自适应; 日志落盘 data\refresh_task.log)
rem 登记: schtasks /create /tn "aag-sources-refresh" /tr "wscript.exe <项目路径>\bin\silent_run.vbs <项目路径>\bin\refresh_task.bat" /sc minute /mo 15 /f
set PYTHONUTF8=1
cd /d "%~dp0.."
if not exist data mkdir data
where py >nul 2>nul && (py -3.11 cli.py sources refresh >> data\refresh_task.log 2>&1) || (python cli.py sources refresh >> data\refresh_task.log 2>&1)
