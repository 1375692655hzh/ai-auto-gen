---
name: aag-morning-paper
description: 用 ai-auto-gen 工具跑每日 AI 财经早报全流程（生成→审核→可选成片）。当用户要"跑早报/生成今日日报/出今天的财经内容"时使用。
---

# 每日早报全流程

项目根目录运行（Windows 用 `py -3.11`，下同）。逐步执行，每步看退出码。

1. **环境体检**：`python cli.py doctor --json`
   - 有 fail 项先报告用户并停止（密钥缺失/字体缺失等）。
   - Chrome 调试口 warn：发布前才必须，生成阶段可继续。
2. **来源健康**（可选）：`python cli.py sources check`，dead 来源会被自动跳过，无需处理。
3. **生成**：`python cli.py flows run morning-paper`
   - 审核点 assemble 会挂起（exit 2）：把 md_path/voice_path 报给用户，等用户说继续后**重跑同一命令**续跑（存档复用不重复花钱）。
   - 用户要全自动：加 `--auto`；指定条数：`--set items=15`。
4. **看产物**：`python cli.py flows status morning-paper`
5. **要视频**（用户明确要求时）：`python cli.py flows run morning-paper --set with_video=true --auto`（或 `python cli.py gen video`）
6. **发布**：见 aag-publish 技能。发布永远最后做且必须先 --draft。

红线：不在审核点替用户确认内容；发布命令不去掉 --draft 除非用户明确说"真发"。
