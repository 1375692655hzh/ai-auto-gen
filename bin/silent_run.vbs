' aag 计划任务静默启动器: 隐藏运行目标 bat(窗口样式 0, 同步等待+透传退出码)
' 用法: wscript.exe silent_run.vbs "<bat 绝对路径>"
' 背景: schtasks 直跑 bat 会弹可见 conhost 窗口(15min 刷新双任务每轮弹两窗),
'       经本包装后全程零窗口
' 注意1: 必须显式 cmd.exe /c 包装——WshShell.Run 直接吃 .bat 路径在本机实测
'        静默不执行(2026-09-07 探针实证), 曾导致 6 个计划任务空转 32 小时
' 注意2: 必须同步等待(True)并透传退出码——不等待时任务实例秒退, 计划程序的
'        IgnoreNew/执行时限/结果码全部落空(双 refresh 并行卡死 45min 的调度层根因,
'        2026-09-07 MoA 六家会诊确诊); 常驻类 bat 内部 start /b 后立即 exit /b 0,
'        等待只挂 bat 本体毫秒级, 不会拖住 start /b 拉起的服务进程
Dim shell, rc
Set shell = CreateObject("WScript.Shell")
rc = shell.Run("cmd.exe /c " & Chr(34) & WScript.Arguments(0) & Chr(34), 0, True)
WScript.Quit rc
