@echo off
rem aag YouTube热点追踪采集·任务计划专用(相对路径自适应; 日志落盘 data\yttrack_task.log)
rem 登记(每天 09:00 一次): schtasks /create /tn "aag-yttrack-refresh" /tr "wscript.exe <项目路径>\bin\silent_run.vbs <项目路径>\bin\yttrack_task.bat" /sc daily /st 09:00 /f
set PYTHONUTF8=1
cd /d "%~dp0.."
if not exist data mkdir data
where py >nul 2>nul && (py -3.11 cli.py workbench refresh-yt-track >> data\yttrack_task.log 2>&1) || (python cli.py workbench refresh-yt-track >> data\yttrack_task.log 2>&1)
