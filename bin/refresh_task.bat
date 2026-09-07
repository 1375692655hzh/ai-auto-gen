@echo off
rem aag 数据站刷新·任务计划专用(相对路径自适应; 日志落盘 data\refresh_task.log)
rem 登记: schtasks /create /tn "aag-sources-refresh" /tr "wscript.exe <项目路径>\bin\silent_run.vbs <项目路径>\bin\refresh_task.bat" /sc minute /mo 15 /f
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
cd /d "%~dp0.."
if not exist data mkdir data
rem 日志切割: >5MB 滚动一代(防无限膨胀拖慢控制台读日志)
if exist data\refresh_task.log for %%F in (data\refresh_task.log) do if %%~zF gtr 5242880 move /y data\refresh_task.log data\refresh_task.1.log >nul 2>&1
echo ===== %date% %time% 轮开始 ===== >> data\refresh_task.log
rem 注意: 不能用 where py ^&^& (py ...) ^|^| (python ...)——业务非零退出会触发换解释器重跑一整轮
where py >nul 2>nul
if errorlevel 1 (
  python -u cli.py sources refresh >> data\refresh_task.log 2>&1
) else (
  py -3.11 -u cli.py sources refresh >> data\refresh_task.log 2>&1
)
set AAG_RC=%errorlevel%
echo ===== %date% %time% 轮结束 rc=%AAG_RC% ===== >> data\refresh_task.log
exit /b %AAG_RC%
