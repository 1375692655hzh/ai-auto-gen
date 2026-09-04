@echo off
rem 数据站控制台入口(桌面快捷方式目标): 确保工作台在跑 → 打开运维页
rem 全灭场景也能用: 工作台没起就先拉起(幂等), 再开浏览器
cd /d "%~dp0.."
netstat -ano | findstr "127.0.0.1:8788" | findstr LISTENING >nul || (start "" /min "%~dp0workbench_task.bat" & timeout /t 4 /nobreak >nul)
start "" "http://127.0.0.1:8788/#/ops"
exit /b 0
