# AGENTS.md — ai-auto-gen agent 驱动契约

> 本文件是给任何 AI agent（Claude Code / Codex CLI / Cursor / ZCode 等）的操作契约。
> 项目 = AI 财经内容 **来源采集 → 生成 → 发布** 一体化工具。架构总方案见 `docs/三大板块实施方案.md`。

## 驱动方式

- 一律 subprocess 调 `python cli.py <板块> <命令>`（或 `bin/aag.cmd`）；不要直接 import 内部模块驱动物理操作。
- 机器可读：`doctor --json` / `publish status --json`（后续 `sources`/`flows` 命令同样支持 `--json`）。
- 退出码：`0` 成功 ｜ `2` 需人工介入（登录/审核/验证码——告知用户后停） ｜ `3` 业务失败 ｜ `4` 配置缺失。
- 全命令幂等可重跑：工作流按步骤存档断点续跑；发布按账本跳过已发/结果未确认项。

## 命令速查（P0 门面，逐步扩展）

| 命令 | 作用 | 副作用 |
|---|---|---|
| `python cli.py doctor [--json]` | 环境体检（密钥/浏览器/队列/账本） | 无 |
| `python cli.py gen <args>` | 生成模块透传（`workflows`/`run <wf> --auto`/`daily`/`morning`/`fetch`/`llm-status`） | `run` 会调 LLM |
| `python cli.py publish status [--json]` | 待发队列 + 发布账本 | 无 |
| `python cli.py publish login [plat]` | 一键登录平台 | 弹浏览器等人工扫码 |
| `python cli.py publish run [--draft ...]` | 发全部启用平台 | **真发**！必须先 `--draft` |
| `python cli.py publish run-video --video <mp4> --title <t> [--draft]` | B站/抖音投稿 | **真发**！必须先 `--draft` |
| `python cli.py video build <id> [--estimate]` | Remotion 出片 | 写 video/videos/&lt;id&gt;/out |

## 目录地图

```
cli.py / bin/aag.cmd   统一入口(P0)
generator/             生成引擎(P1 起抽 sources/flows, 留 shim)
autopub/               浏览器发布引擎(10 平台, CDP 接管用户 Chrome)
adapters-kit/          Node API 发布引擎(搜狐/头条/网易/值得买)
video/                 Remotion 视频引擎(story.json 契约)
data/                  运行时数据(gitignored: 缓存/健康/运行产物)
docs/                  方案与操作手册
```

## 状态文件（agent 的共享内存）

| 文件 | 语义 | 谁写 |
|---|---|---|
| `autopub/state.json` | 发布账本：`published/failed/uncertain`。**agent 只读**；`uncertain` = 已点发布未确认，禁止自动重试，须人工到平台后台核实 | autopub 写 |
| `generator/output/workflows/<流>/<日期>/` | 工作流步骤存档（存在即跳过=断点续跑） | 引擎写 |
| `autopub/articles/` | 待发队列（md/docx），发完全平台自动归档 `_done/` | 人/生成写 |
| `generator/output/` | 生成产物（文章/口播/长图/daily JSON） | 生成写 |

## 红线（违反会造成事故）

1. **发布命令先 `--draft` 验证**，用户明确同意后才去掉 `--draft` 真发。
2. **不手编 `autopub/state.json`**——它是防重复发布的唯一账本（原子写+损坏熔断，误改会导致重发或漏发）。
3. **不提交** `data/`、`autopub/secret.local.json`、`autopub/profiles/`、任何日志/截图。
4. **不改** `video/src/active-story.ts`（渲染时自动生成）与 `video/src/story-types.ts` 契约。
5. B站/抖音上传框是**多文件累加**队列——绝不重复 set_input_files；适配器已有队列防重逻辑，别绕过。
6. Chrome 调试模式（9222）接管的是用户日常浏览器：发布期间提示用户勿手动操作该浏览器。

## 常见任务配方

**每日早报全流程**
```
python cli.py doctor                       # 环境就绪?
python cli.py gen run morning-paper --auto # 生成(断点续跑)
python cli.py publish status               # 看队列与账本
python cli.py publish run --draft          # 草稿验证 → 用户确认 → 去掉 --draft 真发
```

**某来源挂了**：`python cli.py gen fetch` 看各源抓取输出 → 失败源按 `docs/add-a-source.md`（P1 提供）修选择器/接口。

**视频**：`python cli.py gen video --date <d>`（生成 story.json+TTS+渲染+封面）→ `python cli.py publish run-video --video <mp4> --title <标题> --draft`。

## 环境

Python ≥3.10（本机用 `py -3.11`）；Node ≥20（视频/API 发布才需要）；`pip install -r generator/requirements.txt -r autopub/requirements.txt`；`playwright install chromium`；LLM 密钥三选一（网页控制台 / `AUTOPUB_API_KEY` / `autopub/secret.local.json`）。发布前：双击 `autopub/chrome_debug.bat` 启动自动化 Chrome 并完成各平台登录（`publish login`）。
