# MoA 答卷 ① — cursor（第四板块·前端工作台 执行方案）

> 2026-09-03 同题并行任务原文：「制定执行方案并且汇总出最优先的plan，执行」。以下为 cursor 答卷原文。

---

已完成仓库摸底（AGENTS.md、三大板块实施方案.md、cli.py、供数服务.md、serve.py 源码、auto-publisher/ai-workflow 目录结构），本轮未写任何代码、未改动任何文件。以下为第四板块【前端工作台】完整执行方案。

# 第四板块【前端工作台 workbench】执行方案

## 0. 现状关键事实（方案依据）

1. **供数 API 已就绪且对浏览器友好**：`sources serve`（FastAPI，`global-news-sources\sources\serve.py`）默认 `127.0.0.1:8787`，全 GET 只读端点，**已内置 `CORS allow_origins=["*"] / GET / Authorization 头放行**（serve.py 第 104 行注释明确写着"同事的工作台若是浏览器页面直连，需要 CORS 放行"）——浏览器前端可**直连供数服务，无需自建代理**。
2. **鉴权语义现成**：`config/api_keys.local.json` 配 Bearer Key；**localhost 且无键时免密**（serve.py `_auth_scope`），本机自用零配置；有键后前端存 Key 即可。
3. **条目 Schema 稳定（v2）**：`id/source_id/source/time/text/title/url/media` + 打平标签 `kind/form/channel/markets[]/lang` + 信息标签 `info_type/tickers[]/event_type/sentiment/sectors[]` + 中译字段（`display=1` 时 `text/title` 直接是中文，原文在 `text_src/title_src`）。游标分页 `next_cursor`、`dedup`、`q` 拆词检索、`since` 增量——**资讯页所需的全部筛选能力服务端已支持，前端不需要自己过滤大数组**。
4. **生成/发布产物全部是文件契约**：`data/runs/<流>/<日期>/run.json`、`ai-workflow/generator/output/`（文章/口播/长图/daily JSON）、`auto-publisher/autopub/articles/`（待发队列 md/docx）、`auto-publisher/autopub/state.json`（发布账本，只读）。前端工作台读这些文件即可完成图文/视频/发布状态展示。
5. **已有 web 先例**：`auto-publisher\autopub\webapp\app.py` 是 Flask + 单 `templates/index.html` 的本地控制台（端口 5001），证明"Python 后端 + 免构建页面"路线在本项目已跑通。但它只管发布上传，且耦合 autopub 内部，新工作台**不重用它、与它并存**，后续再考虑收敛。
6. **cli.py 挂板块模式清晰**：每个板块 = `sys.path.insert(0, <板块目录>)` + import 门面模块（见 `sources_cmd` 第 176 行、`flows_cmd` 第 280 行），第四板块照此挂载即可。

---

## 1. 技术栈选型与理由

### 候选对比

| 方案 | 构成 | 优点 | 缺点 |
|---|---|---|---|
| **A. 静态 SPA + Python 后端（推荐）** | 前端：免构建单页（Vue 3 global build 或 Alpine.js 单文件 vendored + hash 路由 + 原生 fetch）；后端：FastAPI/uvicorn 静态托管 + 本地聚合 API | 用户 `pip install` 即用，**零 Node 零构建**；fastapi/uvicorn 已是项目依赖（doctor 里已体检）；前端资源随仓库分发，离线可用；与 sources serve 技术栈同源，维护者只需会 Python | 复杂交互（拖拽排版）天花板低于 React 生态 |
| B. React/Vite 构建 | 前端 React+Vite 构建出 dist，Python 托管 dist | 生态最强、组件库丰富 | **用户或发布流程必须带 Node**；违背"下载即用、尽量免 Node 构建"硬约束；构建产物与源码双份维护 |
| C. htmx + 服务端模板（Flask/Jinja2） | 服务端渲染为主 | 最简单 | 资讯页多维筛选/分页/折叠簇这类高交互场景会写得别扭；与已有 webapp 同构但交互上限低 |

### 裁决：方案 A，具体选型

- **后端**：**FastAPI + uvicorn**（与 sources serve 完全一致，无新增重依赖），新增 `workbench/` 板块，命令 `python cli.py workbench serve`。
- **前端**：**Vue 3 global build（`vue.global.prod.js` 单文件 vendored 进仓库）+ 自写 hash 路由（约 40 行）+ 原生 fetch 封装的 api client**。不引入 npm/打包器；CSS 手写设计令牌（CSS 变量）+ Flexbox/Grid，不引 UI 框架（Element Plus 等都要构建或不搭免构建路线）。图标用内联 SVG。
  - 若后续交互复杂度暴涨，逃生舱 = 前端目录整体换成 Vite 构建产物，后端 API 不变（前端只认 `workbench` 自有 API + sources serve，不耦合实现）。
- **架构形态**：**双服务**——`workbench serve`（默认 `127.0.0.1:8788`）托管前端静态文件 + 提供**本地资源 API**（读 run.json / output / 队列 / 账本 / 设置）；**资讯数据直连 sources serve（8787）**，不经 workbench 中转（减少一跳、复用其鉴权与限流；浏览器跨域已由 CORS 解决）。设置页可切换为"经 workbench 代理"模式以兼容云端演进（见 §4）。

---

## 2. 目录结构与 cli.py 挂载

### 2.1 新板块目录（顶层，与三板块平级）

```
workbench/                        # ★ 板块四: 前端工作台
├── README.md                     # 板块说明 + 快速开始
├── server/
│   ├── __init__.py
│   ├── app.py                    # FastAPI 应用: 静态托管 + /wb-api/* 本地资源 API
│   ├── local_api.py              # 读 run.json / generator output / 队列 / 账本(只读) / doctor
│   ├── settings.py               # 工作台配置读写(config.local.yaml, 唯一写接口)
│   └── proxy.py                  # (预留) sources serve 代理模式, 云端演进缝
├── web/                          # 纯静态, 免构建
│   ├── index.html                # 单页壳: 侧边导航 + <div id="app">
│   ├── vendor/vue.global.prod.js # vendored, 锁版本
│   ├── css/app.css               # 设计令牌 + 布局 + 组件样式
│   └── js/
│       ├── app.js                # Vue 应用 + hash 路由(#/news /article /video /track /settings)
│       ├── api.js                # 两个 client: sourcesClient(8787, 可配) + wbClient(8788 同源)
│       ├── store.js              # 轻量状态(筛选条件/设置缓存, localStorage 持久化)
│       └── pages/                # news.js article.js video.js track.js settings.js (每页一个组件)
├── config/
│   └── workbench.example.yaml    # 配置样例(源端点/端口/追踪账号清单/云同步预留字段)
└── docs/
    └── 工作台方案.md              # 本方案沉淀 + 页面设计稿说明
```

运行时数据遵守现有约定：用户配置写 `workbench/config/workbench.local.yaml`（gitignored，与 `data/config.local.yaml` 同语义），或并入 `data/` 下——**建议放 `data/workbench/settings.json`**，与"data/ 是全部运行时数据"的板块边界规则保持一致，`workbench/` 本身只含代码与样例。

### 2.2 cli.py 挂载（第四板块命令）

仿照 `sources_cmd`/`flows_cmd` 的既有模式新增：

| 命令 | 作用 | 副作用 |
|---|---|---|
| `python cli.py workbench serve [--port 8788] [--open]` | 启动工作台（托管前端 + 本地 API），`--open` 自动开浏览器 | 常驻进程 |
| `python cli.py workbench status [--json]` | 检查 8788/8787 双服务可达性 + 配置有效性 | 无 |
| `python cli.py workbench config [--set k=v]` | 读写工作台设置（等价设置页写操作） | 写 data/workbench/settings.json |

- `main()` 中 `sub.add_parser("workbench")`，处理函数内 `sys.path.insert(0, str(ROOT / "workbench"))` 后 `from server import app` 起 uvicorn——与 `sources serve` 的 `serve.run()` 同构。
- `doctor` 增补两项体检：`workbench 端口可绑`（warn 级）、`sources serve 可达`（warn 级，提示先起 `sources serve`）。
- `bin/aag.cmd` 无需改（它透传 cli.py）。
- AGENTS.md 目录地图、命令速查表相应补一行（实施时改，本轮不动）。

**进程关系**：`sources refresh`（任务计划写侧）→ `sources serve`（8787 数据）+ `workbench serve`（8788 界面）→ 用户浏览器。工作台**永不触发抓取、永不写账本**，与供数服务"消费者永不触发抓取"的红线一致。

---

## 3. 五个页面 UI 设计

### 全局壳

- 左侧固定导航栏（宽 200px）：Logo + 5 个页面入口 + 底部"数据站连接状态"指示灯（轮询 `GET /v1/health`，绿/黄/红）。
- 顶栏：当前页标题 + 全局搜索框（资讯页=q 检索）+ 数据时间戳（"数据更新于 HH:MM"，取自 `/v1/status` 的 refresh 账本）。
- 主区：各页内容，最大宽度 1200px 居中。

### 3.1 资讯页（核心页，对接 `/v1/items` + `/v1/sources`）

**布局：三栏**
- **左栏·标签筛选器**（240px，可折叠），全部筛选维度对应 API 参数，分四组：
  - 市场 `markets[]`：多选 chip（A股/港股/美股/台湾/土耳其…，选项来自 `/v1/sources` 聚合去重）；
  - 类型 `kinds[]`：flash 快讯 / peer_article 文章 / calendar 日历 / market 行情 / announcement 公告 / evidence 证据；
  - 信息标签：`info_types[]` / `event_types[]` / `sentiments[]`（利好/利空/中性）/ `sectors[]` 赛道；
  - 来源：`sources[]` 多选（带健康标记，dead 源灰显）+ `channels[]`/`forms[]`。
  - 每个维度一个 `<FilterGroup>` 组件：标题 + chip 列表 + "全选/清空"；选中态实时拼成 querystring。
- **中栏·信息流**：
  - 工具条：`q` 搜索框（回车触发，服务端拆词 AND，同时检索原文与译文）、`since` 时间窗快捷选项（1h/4h/今日/自定义）、`dedup` 开关（默认开，"同事件折叠"）、排序固定为时间倒序。
  - 条目卡片 `<NewsCard>`：时间（北京时）+ 来源名 + kind 徽章 + 情绪点（利好绿/利空红）+ tickers 标签 + 正文（`text`，display=1 已是中文；有 `text_src` 时提供"查看原文"展开）+ 链接跳转 + `dup_count>1` 时"同事件 N 条"展开簇。
  - 分页：**游标式"加载更多"按钮**（`next_cursor` 追加渲染，不用页码）；限流 429 时按 `Retry-After` 显示冷却提示。
- **右栏·状态面板**（260px，可隐藏）：当前筛选命中数（`total`）、数据站统计（`/v1/status`：库内条数/最近刷新/dead 源清单）、已选条件摘要 + 一键清空。

**组件清单**：`FilterGroup`、`Chip`、`NewsCard`、`ClusterExpander`、`SearchBox`、`TimeWindowPicker`、`LoadMore`、`StatusPanel`、`DeadSourceList`。

### 3.2 图文页（基于信息源做图文内容）

**布局：左素材右编辑**
- 左栏·素材抽屉：复用资讯页筛选器（简化版），条目卡片增加"＋加入素材篮"；素材篮固定底部，可排序/移除。
- 中栏·生成区：
  - 工作流选择下拉（`GET /wb-api/flows` ← 读 `ai-workflow/flows` 包清单 + lint 状态）；
  - 参数表单（读包 manifest 的 params 渲染）；
  - "开始生成"按钮（本期为桩：提示请运行 `python cli.py flows run <wf>`，或经 workbench API 以 subprocess 异步触发并轮询 run.json——见 §5 衔接点，触发能力放二期）；
  - 运行状态卡：读 `data/runs/<流>/<日期>/run.json`，分步展示 done/waiting_review，waiting_review 高亮"待人工审核"。
- 右栏·产物预览：列出生成产物（`generator/output/` 下的 md/长图 PNG/daily JSON），md 渲染预览、图片灯箱；"送入发布队列"按钮（本期桩，二期=复制进 `autopub/articles/`）。

**组件清单**：`MaterialDrawer`、`FlowPicker`、`ParamsForm`、`RunStatusCard`、`ArtifactList`、`MarkdownPreview`、`ImageLightbox`。

### 3.3 视频页（基于信息源做视频内容）

**布局：上下两段**
- 上段·视频项目列表：读 `ai-workflow/video/videos/` 项目目录 + 各项目 `project.json` 审核门禁状态（draft→reviewed→built），卡片显示封面缩略图/标题/状态徽章/产出 mp4 是否存在。
- 下段·项目详情：选中项目后展示 story.json 摘要（场景序列只读预览）、TTS 状态、渲染产物（`out/*.mp4` 内嵌 `<video>` 播放）；"构建视频""发布到 B站/抖音"按钮本期为桩（提示 `python cli.py video build` / `publish run-video --draft`，红线：发布命令必须先 --draft）。

**组件清单**：`VideoProjectCard`、`StoryPreview`、`VideoPlayer`、`GateBadge`（审核门禁状态）。

### 3.4 追踪页（账号粉丝/流量数据）

**本期纯桩 + 数据结构先行**：
- 布局：账号卡片网格（每卡：平台图标/账号名/粉丝数/7 日曲线占位/最近抓取时间）+ "添加追踪账号"按钮。
- 数据契约预留：`data/workbench/tracked_accounts.json`（`[{platform, account_id, display_name, note}]`）与 `data/workbench/metrics/<platform>/<account_id>/<date>.json`（`{followers, views, likes, fetched_at}`）——目录与 schema 本期建好，页面渲染 mock 空态（"未配置采集器"）。
- 明确提示文案：采集器未来接 X 账号池（`config/twitter_pool.local.yaml` 已有 X 池先例）与各平台后台数据，本期不实现。

**组件清单**：`AccountCard`、`MetricSparkline`（SVG 迷你曲线，本期渲染占位）、`AccountForm`。

### 3.5 设置页（工作台设置 + 信息源链接配置）

**分组表单**（保存即写 `data/workbench/settings.json`，唯一写口走 `/wb-api/settings`）：
1. **信息源连接**（核心）：
   - 连接模式三选：`local`（本机 127.0.0.1:8787，免密或本机 Key）/ `lan`（局域网数据站，填 `http://192.168.x.x:8787` + Key）/ `cloud`（灰显预留，未来云端域名）；
   - API Key 输入框（存 localStorage，**不进 settings.json、永不提交**）；
   - "测试连接"按钮 → `GET /v1/health` 实时验证并显示库统计/快照时间。
2. **界面偏好**：主题（亮/暗）、每页条数（limit 默认 200）、默认筛选记忆开关。
3. **生成与发布路径自检**：只读展示三板块关键路径存在性（队列目录几篇待发、账本记录数、flows 包数）——数据来自 `/wb-api/doctor`（复用 cli.py doctor 逻辑的服务化版本）。
4. **账号与云同步（预留，本期 UI 壳+接口定义）**：登录/注册表单灰显 + 文案"云端同步将在后续版本开放"；配置 schema 预留 `cloud: {endpoint, account, sync_token, last_sync_at}` 字段位，前端代码按字段存在性渲染，未来填上即启用。

**组件清单**：`EndpointModePicker`、`KeyInput`、`ConnectionTester`、`PathSelfCheck`、`CloudLoginStub`。

---

## 4. 与 sources serve 的数据契约 + 本地→云端演进

### 4.1 前端直连契约（本期实现）

| 前端需求 | 端点 | 参数 |
|---|---|---|
| 连接状态/库统计 | `GET /v1/health`、`GET /v1/status` | — |
| 筛选项字典 | `GET /v1/sources` | `markets/channels/forms/kinds` |
| 信息流 | `GET /v1/items` | `markets, kinds, info_types, event_types, channels, forms, sources, tickers, sentiments, q, since, limit, cursor, dedup=1, display=1` |
| 全量备份（设置页"导出数据"预留） | `GET /v1/snapshot/latest` | — |

- 鉴权头 `Authorization: Bearer <key>`，Key 只存浏览器 localStorage；`local-anonymous` 免密场景前端自动不带头。
- 429 处理：读 `Retry-After`，UI 冷却倒计时。
- workbench 自有 `/wb-api/*` 只承载 sources serve **没有**的东西：本地文件（runs/output/队列/账本只读视图）、设置读写、（二期）命令触发。

### 4.2 云端演进预留（本期只定契约不实现）

1. **端点抽象**：前端所有请求走 `api.js` 的 `sourcesClient`，base URL 唯一来自设置页配置——切云 = 改配置，零代码改动。
2. **代理模式**：`server/proxy.py` 预留 `/wb-api/sources/*` 反代（本期返回 501）。云端场景若 Key 不宜暴露给浏览器，或需聚合多个数据站，切到代理模式；本地直连模式保持不变。
3. **账号同步接口预留**：定义 `POST /wb-api/cloud/login`、`POST /wb-api/cloud/sync`、`GET /wb-api/cloud/status` 三个端点签名与 settings.json 的 `cloud.*` schema，本期全部返回 501 + 灰显 UI。同步内容 = settings.json + tracked_accounts.json +（可选）用户自定义筛选预设——全是小 JSON，云端就是一个 KV 存储，未来实现成本低。
4. **多数据站**：配置 schema 允许 `endpoints: []` 数组（本期 UI 只用第一个），为未来"本地站+云站双源"留位。

---

## 5. 与 ai-workflow / auto-publisher 的衔接点

| 衔接 | 方式 | 方向 | 本期/二期 |
|---|---|---|---|
| flows 工作流清单与 lint 状态 | `/wb-api/flows` 读 `ai-workflow/flows` 包（复用 `flows.engine.discover/lint`） | 只读 | 本期 |
| 运行状态展示 | 读 `data/runs/<流>/<日期>/run.json`（状态机+产物清单） | 只读 | 本期 |
| 触发工作流运行 | **不 import 内部模块**：workbench subprocess 调 `python cli.py flows run <wf> --auto`，异步任务表 + 轮询 run.json；exit 2 = waiting_review 时前端弹审核提示 | 写（经 CLI） | **二期**（本期按钮为桩） |
| 生成产物浏览 | 读 `ai-workflow/generator/output/`（文章 md、长图、口播、daily JSON）与 `video/videos/<id>/out/*.mp4` | 只读 | 本期 |
| 送入发布队列 | 复制产物文件到 `auto-publisher/autopub/articles/`（队列目录即契约） | 写（文件） | 二期 |
| 发布状态看板 | 读 `autopub/state.json` 账本（published/failed/uncertain 分平台）+ 队列清单——复刻 `publish status --json` 的服务化 | 只读（红线：不手编账本） | 本期只读展示可先做 |
| 触发发布 | subprocess `python cli.py publish run --draft`；真发必须用户在前端显式确认后才去掉 --draft（红线 1 的 UI 化：真发按钮二次确认 + 默认锁死） | 写（经 CLI） | **三期**，且 draft-only 先行 |
| 视频发布 | subprocess `python cli.py publish run-video --draft` | 写（经 CLI） | 三期 |

**统一原则**：workbench 对三板块**只通过 ①CLI subprocess ②文件契约 ③HTTP API 三种方式交互**，与 AGENTS.md"一律 subprocess 调 cli.py、不直接 import 驱动物理操作"的驱动契约完全一致。写操作只落在 `data/workbench/` 与（二期后）队列目录；账本、run.json、active-story.ts 等红线文件一律只读。

---

## 6. 分期实施计划（本期 = 展示/UI 壳，功能留桩）

| 期 | 内容 | 验收标准 | 预估 |
|---|---|---|---|
| **W0 骨架**（本期第一阶段） | `workbench/` 目录落地；`cli.py workbench serve/status` 挂载；FastAPI 托管静态壳 + `/wb-api/health`；hash 路由 + 侧边导航 5 页空态；doctor 增补两项 | `python cli.py workbench serve --open` 起服务，5 个页面可切换，无 Node 参与 | 1-1.5 天 |
| **W1 资讯页联通**（本期核心交付） | api.js 双 client；资讯页三栏完整实现（筛选器/信息流/状态面板）；设置页"信息源连接"分组真实可用（模式切换/Key/测试连接/配置持久化到 data/workbench/settings.json） | 本机起 sources serve 后，资讯页按标签筛选、搜索、游标翻页、簇折叠全部可用；断供数服务时全局指示灯变红并有引导文案 | 2-3 天 |
| **W2 只读看板**（本期收尾） | 图文页/视频页的**只读部分**：flows 清单、run.json 状态卡、output 产物浏览、视频项目列表与 mp4 播放；发布账本只读看板；追踪页/云同步/全部触发按钮 = 桩（501 + 灰显 + 提示对应 CLI 命令）；`docs/工作台方案.md` 沉淀 | 干净 clone 冒烟：`doctor → sources refresh → sources serve → workbench serve` 四步后 5 页全部可浏览真实数据 | 2-3 天 |
| W3 二期（下轮） | flows 触发（subprocess+异步任务）、素材篮→生成、送入队列、追踪页采集器接口落地 | flows run 可从页面触发并看审核挂起 | 另立方案 |
| W4 三期（下轮） | publish --draft 触发与确认流、视频发布、云端登录同步实现、多数据站 | draft 发布全链路 UI 完成 | 另立方案 |

**本期（W0-W2）交付边界**：不写任何触发类业务逻辑；所有"生成/发布/同步"按钮统一为桩组件 `<StubAction>`（显示对应 CLI 命令文案 + 复制按钮），保证用户看到壳就知道底层命令是什么——这也延续了项目"CLI 是最大公约数"的哲学。

---

## 7. 风险与红线检查

1. **不违反任何现有红线**：不碰 state.json（只读）、不碰 active-story.ts、不提交 data/ 与 Key；前端发发布命令永远 draft 优先（且本期根本不做）。
2. **CORS 与鉴权**：sources serve 的 `allow_origins=["*"]` 在内网/本机场景可接受；若未来 `--bind 0.0.0.0` 暴露内网，工作台文档需提醒"配 Key + 走隧道"（沿用供数服务网络红线）。
3. **双服务端口冲突**：8787/8788 写进 doctor 与 workbench status 检查，占用时给明确提示。
4. **vue.global.prod.js vendored 体积**（~150KB gzip 前）可接受，锁版本防供应链漂移；不引 CDN（用户可能离线/内网）。
5. **与既有 Flask webapp（:5001）并存**：本期不动它；工作台发布看板成熟后再评估收敛，避免一次改两个面。

---

**最优先 plan（立即执行项）汇总**：W0 骨架（目录 + cli.py 第四命令 + 静态壳路由）→ W1 资讯页直连 8787（筛选器/信息流/设置页源连接配置）→ W2 只读看板 + 全量桩位 + 文档沉淀。全程零 Node、零对三板块内部模块的物理驱动、零红线文件写入。
