# MoA 答卷 ② — codex（第四板块·前端工作台 执行方案）

> 2026-09-03 同题并行任务原文：「制定执行方案并且汇总出最优先的plan，执行」。以下为 codex 答卷原文。

---

调研完成，以下是第四板块【前端工作台】的详细执行方案。

# 第四板块「前端工作台」（workbench/）执行方案

## 0. 现状摸底结论（方案的事实基础）

- **数据接口已就绪且稳定**：`python cli.py sources serve` 是一个 FastAPI 常驻只读服务（`global-news-sources/sources/serve.py`），全 GET 端点、CORS 已放行（`allow_origins=["*"]`，仅 GET，允许 `Authorization`/`X-API-Key` 头）、Bearer Key 鉴权（localhost 无 key 时免密）、条目 Schema v2 含四标签打平 + 中译字段 + 游标分页。`/v1/items` 的多维过滤参数（markets/kinds/info_types/event_types/channels/forms/q/since/limit/cursor/dedup/display）天然就是资讯页筛选 UI 的数据契约。
- **cli.py 是纯 argparse 手写分发**，新增第四板块只需照抄 `sources`/`flows` 的模式加一个 `workbench` 子命令组，无框架改造成本。
- **三板块交互全部是文件契约**：flows 产物落 `ai-workflow/generator/output/` 和 `data/runs/`，发布消费 `auto-publisher/autopub/articles/` 队列和 `state.json` 账本——工作台读取这些文件即可拿到图文/视频/发布状态，无需侵入三板块代码。
- **用户约束**：下载即用、纯本地、尽量免 Node 构建。这是技术选型的决定性约束。

## 1. 技术栈选型及理由

### 对比表

| 方案 | 免 Node 构建 | 离线可用 | 维护成本 | 演进天花板 | 结论 |
|---|---|---|---|---|---|
| **A. 静态 SPA（Vanilla JS + 单文件组件）+ Python 后端** | 完全免 | 完全离线 | 低（无构建链腐化） | 中（5 页内足够） | **本期采纳** |
| B. React/Vite 构建 | 需 Node ≥20 + npm install + build | 构建产物可离线，但用户机需装 Node | 高（依赖腐化、构建链升级） | 高 | 否——违反"下载即用" |
| C. Vue 3 CDN 版（无构建） | 免 | 需把 vue.global.js 内嵌仓库 | 低 | 中高（有响应式框架红利） | **备选/折中** |
| D. HTMX + 服务端模板 | 免 | 离线 | 低 | 低（富交互页如追踪页图表吃力） | 否 |

### 决策：方案 A 为主干，采纳 C 的一个变体

- **后端**：**FastAPI**（与 sources serve 同栈，依赖已存在于 doctor 体检项 `fastapi+uvicorn`），起独立服务 `python cli.py workbench serve --port 8790`。它做三件事：①静态托管前端页面；②**聚合代理**——工作台自己的 API（`/wb/api/*`），对内转发 sources serve（读 `data/workbench/config.local.json` 里的数据源地址+Key），对文件契约做只读封装（生成产物列表、发布账本、待发队列）；③设置页配置读写。
  - 为什么不复用 sources serve 直接让浏览器直连？因为图文页/视频页/追踪页需要读 `ai-workflow/`、`auto-publisher/` 的文件，这些不是 sources serve 的职责；且未来云端演进时工作台后端是唯一需要替换/上移的层，前端代码零改动。
- **前端**：**单页静态 SPA，零构建**。技术组合：
  - **Vue 3（vue.global.prod.js 本地化内嵌进仓库，~150KB）** 做响应式——比裸 Vanilla 在 5 页规模下省大量 DOM 胶水代码，又不需要构建。若团队更保守可退化为 Vanilla，但资讯页的标签多选联动筛选、追踪页的图表，用 Vue 的成本显著低。
  - CSS 用**单文件 design-token 样式表**（CSS 变量 + flex/grid），不引 Tailwind（CDN 体积与离线约束不合）。
  - 图表（追踪页）预留 **ECharts 本地化单文件**挂载点，本期留桩。
  - 路由用 hash 路由（`#/news`、`#/article`…），静态托管下零服务端配置。
- **关键红线遵守**：不引入 Node 构建链；前端所有依赖（vue.js、未来 echarts.js）以 minified 单文件 vendored 进 `workbench/web/vendor/`，提交进 git，用户 clone 即用。

## 2. 目录结构与 cli.py 挂载

```
workbench/                        # ★ 板块四, 与三板块平级, 可单独下载
├── README.md                     # 快速开始(对应三板块各自的 README)
├── server/
│   ├── __init__.py
│   ├── app.py                    # FastAPI 应用: 静态托管 + /wb/api/* 聚合代理
│   ├── config.py                 # 读 data/workbench/config.local.json(数据源地址/Key/主题等)
│   ├── sources_client.py         # 封装对 sources serve 的 GET(带超时/免密localhost判定)
│   └── fileview.py               # 只读文件契约封装: 生成产物清单/待发队列/发布账本/追踪数据
├── web/
│   ├── index.html                # SPA 壳(左侧导航 + 5 个 hash 路由出口)
│   ├── app.js                    # 路由 + 全局状态(数据源连接状态)
│   ├── api.js                    # 统一 fetch 封装(自动带 Key, 错误规范化)
│   ├── styles/main.css           # design tokens + 布局
│   ├── pages/                    # 每页一个 .js(Vue 组件选项对象, 无 SFC 编译)
│   │   ├── news.js  article.js  video.js  track.js  settings.js
│   └── vendor/
│       └── vue.global.prod.js    # vendored, 免构建
└── docs/
    └── 工作台手册.md              # 页面说明 + 数据源配置说明
```

运行时数据（gitignored）：`data/workbench/config.local.json`（设置页写入）、`data/workbench/track/`（追踪页采集的账号粉丝快照，本期留桩目录）。

**cli.py 挂载**（照搬现有模式，新增一个顶层子命令组）：

| 命令 | 作用 | 副作用 |
|---|---|---|
| `python cli.py workbench serve [--bind 127.0.0.1] [--port 8790]` | 启动工作台（前端+聚合 API） | 常驻进程 |
| `python cli.py workbench doctor` | 检查数据源连通性（转发 sources `/v1/health`）+ 配置文件状态 | 无 |
| `python cli.py workbench open` | 启动后自动开浏览器（`webbrowser.open`） | 常驻进程 |

实现位置：cli.py 新增 `workbench_cmd(args)`，内部 `sys.path.insert(0, str(ROOT/"workbench"))` 后 `from server import app`，uvicorn 起服务——与 `sources serve` 的挂载方式完全同构。doctor 主命令里加一项 warn 级检查：workbench 配置文件是否存在。

## 3. 五个页面逐页 UI 设计

全局壳：左侧固定导航栏（5 项 + 底部"数据源连接状态"指示灯：绿=已连 `/v1/health` 通过，黄=未配置，红=连接失败），右侧内容区。移动端本期不考虑（桌面工具）。

### 3.1 资讯页（`#/news`）——本期功能最完整的一页

布局：顶部筛选栏 + 左侧标签面板 + 主列表。

- **顶部筛选栏**：搜索框（映射 `q` 参数，拆词 AND，提示"同时检索原文与译文"）；时间窗下拉（近1小时/今日/近48h/近7天 → `since`）；去重开关（`dedup`，默认开）；显示译文开关（`display`，默认开）。
- **标签面板（核心设计）**：四组标签对应 Schema 的四标签体系 + 信息标签，组内多选、组间 AND：
  - 市场 `markets[]`（从 `/v1/sources` 聚合去重得到全集）
  - 形态 `forms[]`、渠道 `channels[]`、类型 `kinds/info_types`
  - 事件类型 `event_types`、情绪 `sentiments`、个股 `tickers`（输入框）
  - 已选标签以 chip 形式列在筛选栏下方，单个可点 × 移除；提供"清空全部"。
  - 标签全集来源：启动时调一次 `/v1/sources` 拿源四标签全集；info_type/event_type/sentiment 用 Schema 枚举硬编码一份在 `pages/news.js`（与 `源与信息分类体系.md` 对齐）。
- **主列表**：条目卡片（时间[北京时] + 源名 + 市场/类型小徽章 + 标题/正文[默认中文译文， hover 显示原文] + url 外链图标）；**游标分页**：滚动到底自动加载下一页（`cursor`）；顶部显示"共 N 条 / 数据截止 <fetched_at 最大值>"。
- 组件清单：`TagGroup`（多选标签组）、`FilterBar`、`ItemCard`、`ItemList`（含 IntersectionObserver 无限滚动）、`ConnBadge`（全局复用）。

### 3.2 图文页（`#/article`）——本期 UI 壳 + 产物浏览，生成动作留桩

布局：三栏（左：素材来源条；中：文章编辑/预览；右：产物与发布面板）。

- 左栏：资讯条目选取器——复用资讯页简化版列表，勾选条目作为"素材"（本期仅保存到本地草稿 JSON，不触发工作流）。
- 中栏：Markdown 编辑区 + 预览切换（vendored marked.js 可选，本期可纯 textarea + 预览留桩）；"从工作流产物导入"下拉——调 `GET /wb/api/artifacts/articles`（后端扫 `ai-workflow/generator/output/` 与 `auto-publisher/autopub/articles/`），选中即载入内容。
- 右栏：①待发队列状态（`GET /wb/api/queue`，只读镜像 publish status）；②"生成图文"按钮（**留桩**：禁用态 + tooltip"下一阶段接入 flows run"）；③"放入待发队列"按钮（**留桩**，下一阶段经后端写 `autopub/articles/`）。

### 3.3 视频页（`#/video`）——本期 UI 壳

布局：左：视频项目列表；右：详情/预览。

- 列表来自 `GET /wb/api/videos`（后端扫 `ai-workflow/video/videos/*/`，读取各项目 story.json 标题 + out/ 下 mp4 是否存在 + project.json 审核状态 draft/reviewed/built）。
- 详情区：封面图（若产出）、story 摘要、出片状态徽章；"生成视频/出片/发布视频"三个按钮全部留桩禁用 + 说明文案（下一阶段分别接 `flows run --set with_video=true`、`video build`、`publish run-video --draft`）。
- mp4 预览：`<video>` 标签直连后端静态映射 `/wb/api/videos/<id>/file`（Range 请求由 FastAPI FileResponse 支持）。

### 3.4 追踪页（`#/track`）——本期纯壳 + 数据模型预留

布局：顶部账号管理条 + 图表区 + 数据表。

- 账号管理条：表格列出已追踪账号（平台/账号名/添加时间），"添加账号"弹表单（平台下拉=复用 publish targets 的 14 平台清单、账号 URL/ID）——**本期写入 `data/workbench/track/accounts.json` 即完成**，采集逻辑留桩。
- 图表区：ECharts 折线占位容器（本期显示"数据采集器将在下一阶段接入"占位图）；设计预留：快照文件 `data/workbench/track/<平台>/<账号>/<date>.json`（fans/views/likes），图表读取时间序列。
- 数据表：最近快照列表（本期空态）。

### 3.5 设置页（`#/settings`）——本期唯一有真实写功能的页

布局：分组卡片式表单。

- **数据源配置卡片（核心）**：数据源模式单选 = `local`（默认，指向本机 `http://127.0.0.1:8787`）/ `lan`（局域网数据站，填地址+Key）/ `cloud`（禁用态，"云端服务未来上线"）；地址、API Key 输入框；"测试连接"按钮（后端转发 `/v1/health` 返回源数/最新快照时间/dead 源数）；保存写 `data/workbench/config.local.json`。
- **工作台偏好卡片**：默认市场筛选、每页条数、主题（深/浅）。
- **账号登录卡片（云端预留，本期禁用态 UI）**：登录/注册表单占位 + 说明"登录后工作台配置与追踪数据可云端同步"；下方给出**接口预留清单**（见 §4.3）。
- **关于卡片**：版本、三板块 doctor 摘要（转发 `GET /wb/api/doctor`，后端聚合 `cli.py doctor --json` 的关键项）、数据源访问日志指针。

## 4. 数据契约与本地→云端演进

### 4.1 对接 sources serve（本期唯一真数据源）

后端 `sources_client.py` 封装一个薄客户端，映射关系：

| 工作台 API（前端只调这个） | 转发/实现 |
|---|---|
| `GET /wb/api/health` | → sources `/v1/health` + `/v1/status` 合并 |
| `GET /wb/api/sources` | → `/v1/sources`（四标签全集供筛选面板） |
| `GET /wb/api/items?...` | → `/v1/items`，参数名 1:1 透传（markets/kinds/info_types/event_types/channels/forms/q/since/limit/cursor/dedup/display） |
| `GET /wb/api/artifacts/articles` | 本地文件扫 `generator/output/` + `autopub/articles/` |
| `GET /wb/api/videos`、`/wb/api/videos/<id>/file` | 本地文件扫 `ai-workflow/video/videos/` |
| `GET /wb/api/queue`、`/wb/api/ledger` | 复用 publish_status 逻辑（读 `state.json` + `articles/`，**只读，遵守红线2**） |
| `GET/PUT /wb/api/config` | `data/workbench/config.local.json` |

要点：前端**永远不直连** sources serve——所有请求经工作台后端代理。这样 Key 不出后端进程（浏览器只存"已配置"布尔），也为云端演进留出唯一替换点。

### 4.2 本地→云端演进预留

- **配置抽象**：`config.local.json` 里数据源是 `{mode, base_url, api_key}` 三元组，`sources_client.py` 只依赖这三元组——未来云端模式只是换 base_url + 加用户 token 头，代码路径不变。
- **设置页云端登录接口预留**（本期只定义契约，不实现，写进 `workbench/docs/工作台手册.md`）：
  - `POST /wb/api/cloud/login {username, password}` → 存 token 到 `data/workbench/cloud_session.json`（gitignored）
  - `POST /wb/api/cloud/sync/push`（推送 config + track/accounts.json）
  - `POST /wb/api/cloud/sync/pull`
  - 云端数据范围限定为"配置 + 追踪账号清单 + 追踪快照"，**不含**发布账本与密钥（红线：secret.local.json/state.json 永不上云）。
- **追踪数据格式本地优先**：track 快照用纯 JSON 文件按日期落盘，云端同步 = 文件上传，无需数据库迁移。

### 4.3 安全边界

workbench serve 默认绑 127.0.0.1；`--bind 0.0.0.0` 时复用 sources 的告诫（内网/隧道，禁裸公网），并在 README 明示。工作台自身本期无鉴权（纯本机）；设置页保存的 API Key 只写在 gitignored 的 config.local.json。

## 5. 与 ai-workflow / auto-publisher 的衔接点

| 衔接 | 本期（壳） | 下一阶段（功能） |
|---|---|---|
| 图文生成 | 只读列产物（`generator/output/`、`data/runs/*/run.json` 状态展示） | 后端 subprocess 调 `cli.py flows run <wf> --auto`（**遵守 AGENTS.md：一律 subprocess，不 import 内部模块**）；审核挂起 exit 2 → UI 显示"待人工审核"并链接产物文件 |
| 图文发布 | 只读队列+账本镜像 | "放入队列"= 后端把编辑好的 md 写入 `autopub/articles/`（**唯一允许的写**，与 AGENTS.md "人/生成写"语义一致）；"发布"按钮只触发 `publish run --draft`，真发必须用户在 CLI 确认（遵守红线1） |
| 视频 | 只读项目列表+mp4 播放 | 触发 `cli.py gen video --date` / `video build <id>` / `publish run-video --draft` |
| 追踪 | 账号清单本地读写 | 采集器作为 `workbench/server/track_collector.py` 独立模块，复用 autopub 的浏览器登录态（profiles/）抓粉丝数——届时单独评审，本期只定文件格式 |

**全程不手编 `state.json`、不改 video/src 契约文件、不提交 data/**——红线全部继承。

## 6. 分期实施计划

### 本期目标：5 页 UI 壳 + 资讯页真数据 + 设置页数据源配置，其余留桩

| 里程碑 | 内容 | 验收标准 | 预估 |
|---|---|---|---|
| **M1 骨架** | `workbench/` 目录、FastAPI 静态托管、cli.py `workbench serve/open` 命令、hash 路由壳 + 左侧导航 + 5 个空白页可切换 | `python cli.py workbench serve` 起服务，浏览器开 5 页路由正常 | 0.5 天 |
| **M2 数据通路** | `sources_client.py` + `/wb/api/health|sources|items` 代理 + 设置页数据源配置卡片（含测试连接、保存 config.local.json） | 未启动 sources serve 时黄灯提示；启动后绿灯；lan 模式填对地址+Key 测试通过 | 1 天 |
| **M3 资讯页** | 四组标签筛选 + 搜索 + 时间窗 + 无限滚动 + 译文/原文切换 | 对本地 serve 全量筛选组合无报错；标签组合与 `/v1/items` 参数一一对应；空态/错误态有提示 | 1.5 天 |
| **M4 产物镜像页** | 图文页/视频页的只读部分（产物列表、队列、账本、mp4 播放） + 三个留桩按钮；追踪页账号清单读写 + 图表占位 | 能浏览最近一次 flows 产物与发布账本；追踪账号增删落盘 | 1 天 |
| **M5 收尾** | `workbench doctor`、doctor 主命令加检查项、README + 工作台手册（含云端接口预留清单）、AGENTS.md 增补第四板块一节 | 干净 clone 按 README 三步起工作台；`cli.py doctor` 全绿 | 0.5 天 |

**本期明确不做**（写进手册防 scope creep）：任何生成/发布的真实触发按钮、追踪数据采集器、云端登录实现、移动端适配、Web 化工作流编辑器（延续三板块方案 §6.9 "明确不做"）。

### 后续期展望（不在本期执行）

- 二期：图文页接 flows run（subprocess + exit 2 审核闭环 UI 化）、队列写入、draft 发布触发。
- 三期：视频页接 video build / run-video；追踪采集器（复用平台登录态）。
- 四期：云端服务（登录 + 配置/追踪同步），数据源 mode=cloud 解禁。

---

**核验结论**：方案全部事实点经源码核实——sources serve 的端点/鉴权/CORS/Schema 见 `global-news-sources/sources/serve.py` 与 `global-news-sources/docs/供数服务.md`；cli.py 的 argparse 分发模式见 `cli.py:390-544`；文件契约（产物/队列/账本路径）见 `AGENTS.md` 状态文件表与 `auto-publisher/` 目录实况。三板块方案 §4.5 已把 "webapp 接新 CLI、发布看板" 列为 P5 未启动项，本第四板块方案正是该预留的落地，与既有裁决（文件契约、subprocess 驱动、账本只读）无冲突。
