# AGENTS.md — ai-auto-gen agent 驱动契约

> 本文件是给任何 AI agent（Claude Code / Codex CLI / Cursor / ZCode 等）的操作契约。
> 项目 = AI 财经内容 **来源采集 → 生成 → 工作台** 一体化工具。架构总方案见 `docs/三大板块实施方案.md`。
>
> **发布板块已拆仓（2026-09-07）**：自动发布在独立私有仓 [ai-auto-publisher](https://github.com/1375692655hzh/ai-auto-publisher)。
> 两仓衔接约定 = 发布仓克隆为本仓兄弟目录 `../ai-auto-publisher`，或设 `AAG_AUTOPUB_ROOT` 指到其 `autopub/` 目录。
> 代码内统一解析顺序：**`AAG_AUTOPUB_ROOT` 环境变量 > 兄弟仓 > 仓内旧路径**。发布仓未就位时 `publish` 命令提示并 exit 4。

## 驱动方式

- 一律 subprocess 调 `python cli.py <板块> <命令>`（或 `bin/aag.cmd`）；不要直接 import 内部模块驱动物理操作。
- 机器可读：`doctor --json` / `publish status --json`（后续 `sources`/`flows` 命令同样支持 `--json`）。
- 退出码：`0` 成功 ｜ `2` 需人工介入（登录/审核/验证码——告知用户后停） ｜ `3` 业务失败 ｜ `4` 配置缺失（含发布仓未就位）。
- 全命令幂等可重跑：工作流按步骤存档断点续跑；发布按账本跳过已发/结果未确认项。

## 命令速查（P0 门面，逐步扩展）

| 命令 | 作用 | 副作用 |
|---|---|---|
| `python cli.py doctor [--json]` | 环境体检（密钥/依赖/服务探活；发布仓未就位只算 warn） | 无 |
| `python cli.py sources list/check/fetch <id>` | 来源库（110 源+四标签+健康+缓存，list 支持 --markets/--channels/--forms 过滤） | `check/fetch` 会请求外网 |
| `python cli.py sources gather [--markets/--ids/--fresh] [--json]` | 按标签聚合抓取（显式 --ids 不受 enabled 约束） | 会请求外网（TTL 内走缓存） |
| `python cli.py sources refresh [--dry-run]` | 数据站写侧：到期源调度刷新→SQLite 服务库+快照（详见 global-news-sources/docs/供数服务.md）；单实例锁（撞锁跳过 exit 0）+12min 抓取预算+3min 收尾预算 | **真抓外网**，任务计划每 15min 触发 |
| `python cli.py sources serve [--bind/--port]` | 数据站读侧：只读 HTTP 供数（默认 127.0.0.1:8787，Bearer Key 鉴权） | 常驻进程 |
| `python cli.py sources console [--bind/--port 8786]` | 数据站运维控制台（进程/任务计划/刷新轮/存储；loopback 免密，对外绑定走 Bearer key） | 常驻进程 |
| `python cli.py sources enable <id> [on\|off]` | 启停来源（行级写 config.local.yaml 覆盖段，保留注释；缺省=翻转当前状态） | 改 config.local.yaml |
| `python cli.py flows list/lint/run <wf>/status/new/export/import` | 生成工作流（断点续跑/审核挂起 exit 2） | `run` 会调 LLM |
| `python cli.py gen <args>` | 生成模块透传（旧入口，等价 flows） | `run` 会调 LLM |
| `python cli.py publish status [--json]` | 待发队列 + 发布账本（读发布仓；未就位 exit 4） | 无 |
| `python cli.py publish targets` | 平台矩阵（14 平台×引擎×验证状态；经发布仓薄 shim） | 无 |
| `python cli.py skills list/install` | 把 skills/ 装到本机 agent 技能目录 | 复制文件 |
| `python cli.py publish login [plat]` | 一键登录平台（薄 shim → 发布仓 autopub/login.py） | 弹浏览器等人工扫码 |
| `python cli.py publish run [--draft ...]` | 发全部启用平台（薄 shim → 发布仓） | **真发**！必须先 `--draft` |
| `python cli.py publish run-video --video <mp4> --title <t> [--draft]` | B站/抖音投稿（薄 shim → 发布仓） | **真发**！必须先 `--draft` |
| `python cli.py video build <id> [--estimate]` | Remotion 出片（横版 Story / 竖版 VerticalShort，渲染前 story-validate 门禁，QA 报告写 out/verify.json） | 写 ai-workflow/video/videos/&lt;id&gt;/out |
| `python cli.py video remove <id>` | 删除视频项目目录（videos/&lt;id&gt;/ 整目录，不可恢复） | 删 ai-workflow/video/videos/&lt;id&gt;/ |
| `python cli.py workbench serve [--bind/--port 8788/--open]` | 板块四·前端工作台（资讯/图文/视频/追踪/设置 5 页 SPA，方案见 docs/第四板块-前端工作台方案.md） | 常驻进程；只写 data/workbench/ 自有 JSON |
| `python cli.py workbench refresh-yt-track [--force]` | YouTube 热点追踪采集（Data API v3 → yt_channels/yt_videos 快照；任务计划每天一次，方案见 docs/workbench-moa/16-18） | **真抓 YouTube 外网** |
| `python cli.py workbench analyze-video [--force]` / `gen-script` | 视频工坊：YouTube 视频分析(Gemini 看片→字幕→元数据降级链)与脚本生成(muse) | **真外呼 LLM/YouTube** |
| `python cli.py workbench build-video [--json]` | 视频制作渲染编排（workbench→CLI 子进程入口：脚本转分镜→建项目→node build.mjs 真渲染，分钟级；日志落 data/workbench/video_builds/） | **真渲染**，写 videos/&lt;project_id&gt;/ 与日志 |
| `python cli.py workbench gen-post [--json]` | 内容生成成稿编排（workbench→CLI 子进程入口：retrieve 补全→yfinance/东财行情→mplfinance K线图→摆动点支撑阻力→大V/机构观点聚合→LLM 按 X风格/语种/字数档成稿；产物 gen_posts+gen_assets；详见 docs/workbench-moa/21-24） | **真外呼行情+LLM**，写 data/workbench/gen_* |
| `python cli.py workbench test-llm` | 成稿模型连接测试（设置页「测试连接」按钮的后端：读 compose 段发最小 ping，输出 JSON，不透传传输层异常防泄露 key） | 调 1 次成稿 LLM |
| `python cli.py workbench status [--json]` | 工作台/数据源双探活 + 设置有效性 | 无 |

## 目录地图（三板块 + 兄弟仓，可单独下载）

```
cli.py / bin/aag.cmd        统一入口(P0, 自动挂各板块上 sys.path)
global-news-sources/        板块一·来源: sources/ 注册表 + fetchers/ 抓取实现 + docs/ 源清单
ai-workflow/                板块二·工作流: flows/ YAML引擎+步骤库 + generator/ 生成实现 + video/ Remotion
workbench/                  板块四·前端工作台: server/ FastAPI后端(代理+只读视图) + web/ 免构建SPA(Vue3 vendored)
../ai-auto-publisher/       板块三·发布(独立私有仓, 兄弟目录): autopub/ 浏览器引擎(10平台)
                            + adapters-kit/ Node API + publish/ 门面; publish 命令经薄 shim 透传过去
data/                       运行时数据(gitignored: 缓存/健康/运行产物/workbench配置)
docs/                       方案与操作手册
scripts/ skills/            工具脚本 / agent 技能
bin/*_task.bat              24/7 运维: 幂等启动脚本(端口已听则零副作用退出), 由 schtasks 登录自启
                            (aag-serve/aag-workbench/aag-omniroute/aag-console) + 每15min刷新(aag-sources-refresh/:00相位,
                            aag-xsurge-refresh/:07相位错开) + 每日yttrack(aag-yttrack-refresh 09:00)
                            + 常驻自愈(aag-resident-watchdog 每15min依次调四个常驻bat, 崩溃最长15min自愈)
                            登记必须经 bin/silent_run.vbs 静默包装(/tr "wscript.exe ...\\silent_run.vbs ...\\xx_task.bat"), 直跑bat会弹黑窗打扰桌面;
                            vbs 是同步等待+退出码透传(IgnoreNew/执行时限才生效); 笔记本任务已放开电池限制(拔电不停+错过补跑)
```

**运维入口**：桌面快捷方式「数据站控制台」→ `bin/console.bat` 打开数据站自带控制台 `http://127.0.0.1:8786/`（`global-news-sources/sources/console.py` + `global-news-sources/web/console.html`，与数据站同机部署，未来上云随站部署、对外绑定用 Bearer key）；工作台是用户端，只填数据站地址+key 接入。

## 状态文件（agent 的共享内存）

| 文件 | 语义 | 谁写 |
|---|---|---|
| `<发布仓>/autopub/state.json` | 发布账本：`published/failed/uncertain`。**agent 只读**；`uncertain` = 已点发布未确认，禁止自动重试，须人工到平台后台核实（发布仓 = 兄弟仓 ai-auto-publisher，路径经 AAG_AUTOPUB_ROOT 解析） | autopub 写 |
| `data/runs/<流>/<日期>/run.json` | 工作流状态机（done/waiting_review/stopped + 产物清单） | 引擎写 |
| `data/health/sources-health.json` | 来源健康（dead 自动跳过） | 来源库写 |
| `ai-workflow/generator/output/workflows/<流>/<日期>/` | 旧引擎步骤存档（flows 新引擎在 data/runs） | 引擎写 |
| `<发布仓>/autopub/articles/` | 待发队列（md/docx），发完全平台自动归档 `_done/`；生成产物落点经 AAG_AUTOPUB_ROOT 解析 | 人/生成写 |
| `ai-workflow/generator/output/` | 生成产物（文章/口播/长图/daily JSON） | 生成写 |
| `data/workbench/settings.json` `tracked_accounts.json` | 工作台设置（含数据源 Key）与追踪账号清单 | workbench 写（板块四唯一写口） |

## 红线（违反会造成事故）

1. **发布命令先 `--draft` 验证**，用户明确同意后才去掉 `--draft` 真发。
2. **不手编发布仓 `autopub/state.json`**——它是防重复发布的唯一账本（原子写+损坏熔断，误改会导致重发或漏发）。
3. **不提交** `data/`、发布仓 `autopub/secret.local.json`、`autopub/profiles/`、任何日志/截图（发布仓自带 .gitignore 已兜住，本仓已无此目录）。
4. **不改** `ai-workflow/video/src/active-story.ts`（渲染时自动生成）与 `ai-workflow/video/src/story-types.ts` 契约。
5. B站/抖音上传框是**多文件累加**队列——绝不重复 set_input_files；适配器已有队列防重逻辑，别绕过。
6. Chrome 调试模式（9222）接管的是用户日常浏览器：发布期间提示用户勿手动操作该浏览器。
7. workbench（板块四）对全仓**全程只读**（views.py 只扫文件、proxy.py 只转 GET）；唯一写口是 `data/workbench/` 自有 JSON。（服务器运维已迁至数据站自带控制台 `sources/console.py`，与工作台无关。）

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

Python ≥3.10（本机用 `py -3.11`）；Node ≥20（视频/API 发布才需要）；`pip install -r ai-workflow/generator/requirements.txt -r global-news-sources/requirements.txt -r workbench/requirements.txt`；`playwright install chromium`；LLM 密钥三选一（发布仓网页控制台 / `AUTOPUB_API_KEY` / 发布仓 `autopub/secret.local.json`）。发布前：兄弟仓 ai-auto-publisher 就位后，双击其 `autopub/chrome_debug.bat` 启动自动化 Chrome 并完成各平台登录（`publish login`）。
