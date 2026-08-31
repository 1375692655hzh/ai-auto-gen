---
name: aag-publish
description: 用 ai-auto-gen 工具把生成好的文章/视频发布到各平台（雪球/东财/富途/长桥/微博/B站/抖音）。当用户要"发布/发出去/投稿"时使用。
---

# 发布流程（安全第一）

项目根目录运行。**发布是不可逆动作，严格按序：**

1. **前置检查**：`python cli.py doctor`
   - Chrome 调试口(9222) 必须 ✅（让用户双击 `auto-publisher/autopub/chrome_debug.bat`）。
   - 提醒用户：发布期间不要手动操作那个 Chrome（工具在接管）。
2. **看队列与账本**：`python cli.py publish status`
   - 账本里 `published`/`uncertain` 的平台会自动跳过（防重发），这是设计不是 bug。
   - `uncertain` = 上次结果未确认，必须让用户去平台后台人工核实，禁止自动重试。
3. **草稿验证**：`python cli.py publish run --draft`
   - 每平台填充+截图但不真发。把日志里的失败项报给用户。
4. **真发（仅当用户明确同意）**：`python cli.py publish run`
5. **视频**：`python cli.py publish run-video --video <mp4> --title <标题> --draft` → 同样先草稿。
6. **收尾**：`python cli.py publish status` 汇总各平台结果链接给用户。

红线：
- 不手编 `auto-publisher/autopub/state.json`（防重发账本）。
- B站/抖音上传框是多文件累加队列，适配器已防重，不要绕过适配器直接操作页面。
- 真发后如某平台"结果未知"，标记 uncertain 等人工核实，不要重跑该平台。
