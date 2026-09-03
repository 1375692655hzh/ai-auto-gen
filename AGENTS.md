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
| `python cli.py sources list/check/fetch <id>` | 来源库（110 源+四标签+健康+缓存，list 支持 --markets/--channels/--forms 过滤） | `check/fetch` 会请求外网 |
| `python cli.py sources gather [--markets/--ids/--fresh] [--json]` | 按标签聚合抓取（显式 --ids 不受 enabled 约束） | 会请求外网（TTL 内走缓存） |
| `python cli.py sources refresh [--dry-run]` | 数据站写侧：到期源调度刷新→SQLite 服务库+快照（详见 global-news-sources/docs/供数服务.md） | **真抓外网**，任务计划每 30min 触发 |
| `python cli.py sources serve [--bind/--port]` | 数据站读侧：只读 HTTP 供数（默认 127.0.0.1:8787，Bearer Key 鉴权） | 常驻进程 |
| `python cli.py flows list/lint/run <wf>/status/new/export/import` | 生成工作流（断点续跑/审核挂起 exit 2） | `run` 会调 LLM |
| `python cli.py gen <args>` | 生成模块透传（旧入口，等价 flows） | `run` 会调 LLM |
| `python cli.py publish status [--json]` | 待发队列 + 发布账本 | 无 |
| `python cli.py publish targets` | 平台矩阵（14 平台×引擎×验证状态） | 无 |
| `python cli.py skills list/install` | 把 skills/ 装到本机 agent 技能目录 | 复制文件 |
| `python cli.py publish login [plat]` | 一键登录平台 | 弹浏览器等人工扫码 |
| `python cli.py publish run [--draft ...]` | 发全部启用平台 | **真发**！必须先 `--draft` |
| `python cli.py publish run-video --video <mp4> --title <t> [--draft]` | B站/抖音投稿 | **真发**！必须先 `--draft` |
| `python cli.py video build <id> [--estimate]` | Remotion 出片 | 写 ai-workflow/video/videos/&lt;id&gt;/out |
| `python cli.py workbench serve [--bind/--port 8788/--open]` | 板块四·前端工作台（资讯/图文/视频/追踪/设置 5 页 SPA，方案见 docs/第四板块-前端工作台方案.md） | 常驻进程；只写 data/workbench/ 自有 JSON |
| `python cli.py workbench status [--json]` | 工作台/数据源双探活 + 设置有效性 | 无 |

## 目录地图（三板块，可单独下载）

```
cli.py / bin/aag.cmd        统一入口(P0, 自动挂四板块上 sys.path)
global-news-sources/        板块一·来源: sources/ 注册表 + fetchers/ 抓取实现 + docs/ 源清单
ai-workflow/                板块二·工作流: flows/ YAML引擎+步骤库 + generator/ 生成实现 + video/ Remotion
auto-publisher/             板块三·发布: autopub/ 浏览器引擎(10平台) + adapters-kit/ Node API + publish/ 门面
workbench/                  板块四·前端工作台: server/ FastAPI后端(代理+只读视图) + web/ 免构建SPA(Vue3 vendored)
data/                       运行时数据(gitignored: 缓存/健康/运行产物/workbench配置)
docs/                       方案与操作手册
scripts/ skills/            工具脚本 / agent 技能
```

## 状态文件（agent 的共享内存）

| 文件 | 语义 | 谁写 |
|---|---|---|
| `auto-publisher/autopub/state.json` | 发布账本：`published/failed/uncertain`。**agent 只读**；`uncertain` = 已点发布未确认，禁止自动重试，须人工到平台后台核实 | autopub 写 |
| `data/runs/<流>/<日期>/run.json` | 工作流状态机（done/waiting_review/stopped + 产物清单） | 引擎写 |
| `data/health/sources-health.json` | 来源健康（dead 自动跳过） | 来源库写 |
| `ai-workflow/generator/output/workflows/<流>/<日期>/` | 旧引擎步骤存档（flows 新引擎在 data/runs） | 引擎写 |
| `auto-publisher/autopub/articles/` | 待发队列（md/docx），发完全平台自动归档 `_done/` | 人/生成写 |
| `ai-workflow/generator/output/` | 生成产物（文章/口播/长图/daily JSON） | 生成写 |
| `data/workbench/settings.json` `tracked_accounts.json` | 工作台设置（含数据源 Key）与追踪账号清单 | workbench 写（板块四唯一写口） |

## 红线（违反会造成事故）

1. **发布命令先 `--draft` 验证**，用户明确同意后才去掉 `--draft` 真发。
2. **不手编 `auto-publisher/autopub/state.json`**——它是防重复发布的唯一账本（原子写+损坏熔断，误改会导致重发或漏发）。
3. **不提交** `data/`、`auto-publisher/autopub/secret.local.json`、`auto-publisher/autopub/profiles/`、任何日志/截图。
4. **不改** `ai-workflow/video/src/active-story.ts`（渲染时自动生成）与 `ai-workflow/video/src/story-types.ts` 契约。
5. B站/抖音上传框是**多文件累加**队列——绝不重复 set_input_files；适配器已有队列防重逻辑，别绕过。
6. Chrome 调试模式（9222）接管的是用户日常浏览器：发布期间提示用户勿手动操作该浏览器。
7. workbench（板块四）对三板块**全程只读**（views.py 只扫文件、proxy.py 只转 GET）；触发类动作未来也只经 subprocess 调 cli.py，唯一写口是 `data/workbench/` 自有 JSON。

## 常见任务配方

**每日早报全流程**
```
python cli.py doctor                       # 环境就绪?
python cli.py gen run morning-paper --auto # 生成(断点续跑)
python cli.py publish status               # 看队列与账本
python cli.py publish run --draft          # 草稿验证 → 用户确认 → 去掉 --draft 真发
```

**某来源挂了**：`python cli.py sources check --id <id>` 实抓定位 → 失败源按 `global-news-sources/docs/add-a-source.md` 修选择器/接口。

**视频**：`python cli.py gen video --date <d>`（生成 story.json+TTS+渲染+封面）→ `python cli.py publish run-video --video <mp4> --title <标题> --draft`。

## 环境

Python ≥3.10（本机用 `py -3.11`）；Node ≥20（视频/API 发布才需要）；`pip install -r ai-workflow/generator/requirements.txt -r auto-publisher/autopub/requirements.txt`；`playwright install chromium`；LLM 密钥三选一（网页控制台 / `AUTOPUB_API_KEY` / `auto-publisher/autopub/secret.local.json`）。发布前：双击 `auto-publisher/autopub/chrome_debug.bat` 启动自动化 Chrome 并完成各平台登录（`publish login`）。
