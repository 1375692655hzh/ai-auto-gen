@echo off
rem 数据站控制台入口(桌面快捷方式目标): 确保数据站控制台在跑 → 打开页面
rem 全灭场景也能用: 控制台没起就先拉起(幂等), 再开浏览器
cd /d "%~dp0.."
netstat -ano | findstr "127.0.0.1:8786" | findstr LISTENING >nul || (start "" /min "%~dp0console_task.bat" & timeout /t 4 /nobreak >nul)
start "" "http://127.0.0.1:8786/"
exit /b 0
