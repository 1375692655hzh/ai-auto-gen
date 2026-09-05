' aag 计划任务静默启动器: 隐藏运行目标 bat(窗口样式 0, 不等待)
' 用法: wscript.exe silent_run.vbs "<bat 绝对路径>"
' 背景: schtasks 直跑 bat 会弹可见 conhost 窗口(15min 刷新双任务每轮弹两窗),
'       经本包装后全程零窗口; bat 内部进程照常脱离运行, 不影响服务生命周期
CreateObject("WScript.Shell").Run Chr(34) & WScript.Arguments(0) & Chr(34), 0, False
