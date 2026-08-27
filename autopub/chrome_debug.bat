@echo off
rem 启动"自动化专用 Chrome"(你的 Chrome 程序 + 独立登录目录, 调试端口 9222)。
rem 首次使用: 启动后在这个 Chrome 里逐个登录平台(扫码), 之后工具自动接管发文。
rem 注意: Chrome 136+ 安全限制, 日常默认目录不允许开调试端口, 所以必须用独立目录。
chcp 65001 >nul
set DATADIR=C:\chrome-autopub
for %%P in (
  "%ProgramFiles%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
  "%LocalAppData%\Google\Chrome\Application\chrome.exe"
) do if exist %%P (
  echo 正在启动自动化 Chrome(数据目录 %DATADIR%)...
  start "" %%P --remote-debugging-port=9222 --user-data-dir=%DATADIR%
  exit /b 0
)
echo 未找到 chrome.exe
pause
