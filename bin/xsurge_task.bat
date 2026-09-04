@echo off
rem aag X起爆帖互动采集·任务计划专用(相对路径自适应; 日志落盘 data\xsurge_task.log)
rem 登记: schtasks /create /tn "aag-xsurge-refresh" /tr "<项目路径>\bin\xsurge_task.bat" /sc minute /mo 15 /f
set PYTHONUTF8=1
cd /d "%~dp0.."
if not exist data mkdir data
where py >nul 2>nul && (py -3.11 cli.py workbench refresh-x-surge >> data\xsurge_task.log 2>&1) || (python cli.py workbench refresh-x-surge >> data\xsurge_task.log 2>&1)
