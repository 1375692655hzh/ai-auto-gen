# MoA 答卷 ③ — gemini（第四板块·前端工作台 执行方案）

> 2026-09-03 同题并行任务原文：「制定执行方案并且汇总出最优先的plan，执行」。以下为 gemini 答卷原文（Antigravity CLI 双模型交叉验证：gemini-3.7-flash-high + gemini-3.1-pro，分歧已由其内部裁决）。

---

方案由 Antigravity CLI 双模型交叉验证产出。**模型可用性说明**：`claude-opus-4-6-thinking`（默认）、`claude-sonnet-4-6`、`gpt-oss-120b-medium` 当日均报执行错误（判断为厂商侧故障），交叉验证改用 gemini 双模型完成：答卷 A（gemini-3.7-flash-high，详尽版）+ 答卷 B（gemini-3.1-pro，精简版）。

**两模型完全一致的核心结论（直接采纳）**：
1. 技术栈选 **免构建 SPA（Vue 3 本地引入）+ FastAPI 轻量后端**，否决 React/Vite 工程化；
2. 顶层新建 `workbench/` 与三板块平级，`python cli.py workbench serve` 挂载第四命令；
3. **浏览器直连 `sources serve`**（`serve.py` 第 100-104 行已开 `CORSMiddleware allow_origins=["*"]` 且注释明确写着"为同事的工作台浏览器页面直连预留"，源码已核实）；
4. API Key 存浏览器 localStorage + 设置页可配；本地 127.0.0.1 无键免密自动适配；
5. 本期 UI 壳 + 留桩，发布按钮强制 disabled 并标红线提示。

**分歧点与裁决**：

| 分歧点 | A（3.7-flash-high） | B（3.1-pro） | 裁决 |
|---|---|---|---|
| 前端依赖引入方式 | vendor 目录物理内嵌 Vue ESM，**禁止 CDN** | CDN 引入 Vue/Tailwind/Axios | **采纳 A**："下载即用+纯本地数据"必须离线可跑，CDN 断网即挂；Axios 非必需，原生 `fetch` 足够 |
| 样式方案 | 自研 Design Tokens CSS（CSS 变量） | Tailwind CDN | **采纳 A**：Tailwind CDN 版是浏览器内 JIT，体积大且依赖外网；自研 tokens.css 更贴合金融终端高密排版 |
| 路由 | 手写极简 Hash 路由 | Vue Router CDN | **采纳 A**：仅 5 页，手写 hash 路由 30 行搞定，少一个依赖 |
| 后端端口 | 8501 | 5002 | **采纳 A（8501）**：避开已有 5001（autopub webapp）、8787（sources serve）、9222（Chrome CDP） |
| 直连 vs 代理 | **混合**：默认直连，`Failed to fetch` 时透明回退工作台后端代理 | 纯直连 | **采纳 A**：纯直连在未来 HTTPS/跨网段（Private Network Access 策略）会受阻，代理回退是廉价保险 |
| 目录分层 | `server/` + `static/` | `backend/` + `frontend/` | 采纳 A 命名（贴合 FastAPI StaticFiles 语义），内部结构两家等价 |
| 资讯页真实数据何时接 | 本期 Phase 1 内 | 下期 Phase 2 | **采纳 A**：`sources serve` 是纯只读 GET，资讯页"展示真实数据"本身就是 UI 壳的展示语义，零写风险；写操作（生成/发布）才全部留桩 |

以下为裁决合并后的完整方案正文。

---

# 第四板块【前端工作台 workbench】详细执行方案

## ① 技术栈选型及理由

**结论：免构建原生 ESM SPA（Vue 3 本地 vendor 引入）+ FastAPI 本地宿主服务，否决 React/Vite 工程化。**

| 评估维度 | React/Vite 工程化 | **选定：免构建 ESM SPA + Python 后端** |
|---|---|---|
| 下载即用 | 需 Node 20+ 与 `npm install/build`；`dist/` 入库则仓库膨胀 | clone 即用，`python cli.py workbench serve` 直接拉起 |
| 生态一致性 | 项目仅 Remotion 用 Node，再引一条前端构建链是割裂 | 与 `autopub/webapp`（Flask 单页）、`sources serve`（FastAPI）一脉相承 |
| 离线/内网可用 | 取决于构建产物 | 100% 离线自洽，vendor 全部入库 |
| 系统控制面 | 纯静态托管读不了 `data/runs`、发不了子进程 | 自带 Python 后端，天然胜任文件扫描与 CLI 桥接 |
| 依赖增量 | 整条 Node 工具链 | **零新增依赖**：`cli.py doctor` 已把 fastapi+uvicorn 列为体检项（serve 板块已依赖） |

**前端组织方式**：
- 模块加载：原生 `<script type="module">`，按 View/Component/Store 拆分 `.js` 文件，无编译步骤；
- 框架：Vue 3 `vue.esm-browser.prod.js` 物理存于 `workbench/static/vendor/`，版本随 git 管控；
- 路由：手写极简 Hash 路由（`#/feed`、`#/article`、`#/video`、`#/tracking`、`#/settings`），本地静态托管天然适配，无需服务端 history fallback；
- 状态：Vue 3 `reactive()` 封装分模块 Store（feed/workflow/publisher/settings）；
- 样式：自研 Design Tokens（CSS 变量，暗色金融终端风优先，高信息密度）+ 少量 utility class；
- 后端：FastAPI + Uvicorn，默认 `127.0.0.1:8501`，职责仅四件：托管静态页、只读暴露本地产物/账本、设置读写、（未来）受控触发 CLI 子进程。

## ② 新板块目录结构与 cli.py 挂载

```text
E:\ai-gen-article-publish\
├── cli.py / global-news-sources/ / ai-workflow/ / auto-publisher/   # 现有三板块不动
└── workbench/                          # 【板块四: 前端工作台】
    ├── __init__.py
    ├── config/
    │   └── default.yaml                # 出厂默认: 端口8501 / 数据源 http://127.0.0.1:8787 / UI 参数
    ├── server/                         # Python 宿主后端 (FastAPI)
    │   ├── app.py                      # App 实例 + StaticFiles 挂载 + run(host,port,open_browser)
    │   ├── config.py                   # default.yaml + data/config.local.yaml 覆盖加载
    │   ├── services/
    │   │   ├── sources_proxy.py        # /api/proxy/sources/* 透明转发(直连失败回退用) + 探活
    │   │   ├── workflow_reader.py      # 只读扫描 data/runs/<flow>/<date>/run.json + generator/output
    │   │   ├── publisher_reader.py     # 只读解析 autopub/articles 队列 + autopub/state.json 账本
    │   │   └── tracking_stub.py        # 追踪页 Mock 数据桩(按目标 Schema 返回演示数据)
    │   └── routes/
    │       ├── api_system.py           # /api/system/health, /api/system/doctor(复用 cli doctor 逻辑)
    │       ├── api_workflow.py         # /api/workflows, /api/runs/<flow>/<date>
    │       ├── api_publisher.py        # /api/publish/queue, /api/publish/ledger (全只读)
    │       ├── api_settings.py         # /api/settings GET/POST (写 data/config.local.yaml)
    │       └── api_sync.py             # 云端同步预留桩: 本期一律 HTTP 501
    └── static/                         # 免构建 SPA (全部源码入库, 无 Node)
        ├── index.html                  # 唯一 HTML 入口
        ├── css/{tokens.css, workbench.css}
        ├── vendor/{vue.esm-browser.prod.js, lucide.js}   # 内嵌, 禁 CDN
        └── js/
            ├── app.js / router.js / request.js           # request.js = fetch 封装: Bearer 注入 + 直连/代理回退
            ├── store/{feed.js, workflow.js, publisher.js, settings.js}
            ├── components/{AppHeader, TagBadge, ItemDetailDrawer, ModalDialog, StubAlert, FilterGroup, FeedItemCard ...}
            └── views/{FeedView, ArticleView, VideoView, TrackingView, SettingsView}.js
```

**cli.py 挂载**（对称现有板块，`sys.path.insert` + 延迟 import 的既有模式）：

```
python cli.py workbench serve [--host 127.0.0.1] [--port 8501] [--open]   # 启动并可选自动开浏览器
python cli.py workbench status [--json]                                    # 端口占用/配置/供数探活
```

**doctor 扩展**（挂进现有 `doctor()` 检查表）：
1. `workbench 静态资源`（fail 级）：`static/index.html` 与 `vendor/vue.esm-browser.prod.js` 存在；
2. `workbench 配置`（warn 级）：`config/default.yaml` 存在，本地覆盖缺失则用默认；
3. `供数服务探活 127.0.0.1:8787`（warn 级）：GET `/v1/health`，失败提示"请另开终端 `python cli.py sources serve`"。

## ③ 五个页面逐页 UI 设计与组件清单

全局框架：左侧竖向导航（资讯/图文/视频/追踪/设置）+ 顶栏（Logo、数据源状态灯 ●、深色开关）。设计语言 = 金融终端风：高信息密度、低饱和底色、高对比标签。

### 3.1 资讯页（核心，本期真实接数）

```text
+--------------------------------------------------------------------------------------------------+
| [筛选面板]                                       | [资讯流 共1,420条]  排序[时间▼] [自动刷新:关]  |
| 关键词: [ 降息 美联储          ] [检索]          |--------------------------------------------------|
| 市场: [全部][美股][港股][A股][宏观][台湾][加密]  | 09:42 [美股/快讯][华尔街见闻][中性] [+加入素材]  |
| 渠道: [全部][快讯][官方研报][社交][财报公告]     | 鲍威尔暗示年内降息节奏取决于通胀放缓速率...      |
| 赛道: [全部][半导体][新能源][AI][宏观流动性]     | 标的:$QQQ $SPY  同事件折叠(2条)   [查看详情]     |
| 情绪: [全部][🟢看多][🔴看空][⚪中性]            |--------------------------------------------------|
| 来源: [全部][金十][财联社][Bloomberg]...         | 09:30 [A股/深度][中金研究][看多]  [+加入素材]    |
| 时效: (•)24h ( )48h ( )7天 ( )全部              | 晶圆代工产能持续紧张,先进制程利用率破95%...      |
| [✓]折叠重复(dedup)  [✓]优先中文(display)         | 标的:688981.SH  匹配词:晶圆/扩产  [查看详情]     |
| 已选:[美股×][半导体×]            [重置筛选]      |                                                  |
+--------------------------------------------------------------------------------------------------+
| 分页: [◀上一页] [游标 cur_9482910] [下一页▶]  每页[50▼]                                          |
+--------------------------------------------------------------------------------------------------+
| 侧滑抽屉(点击条目): 中英对照原文/译文 + Schema v2 全字段 JSON + [以此为素材: 转图文 | 转视频]      |
+--------------------------------------------------------------------------------------------------+
```

**标签筛选设计（三层语义）**：
- **同组多选 = OR**（逗号拼接，如 `markets=美股,港股`）；**跨组 = AND**（多 Query 参数并联）；
- `q` 走服务端拆词 AND（同检原文+译文）；`since` 由时效 Radio 换算为北京时间 `YYYY-MM-DD HH:MM`；
- 筛选态同步写入 URL hash query，刷新/分享链接可还原。

**筛选控件 → `/v1/items` 参数映射表**（逐字段对齐 Schema v2，对照供数服务.md 核实参数名）：

| 控件 | 交互 | API 参数 | 示例值 | 默认 |
|---|---|---|---|---|
| 关键词 | 文本框+300ms 防抖 | `q` | `美联储 降息` | 空 |
| 市场 | 胶囊多选 | `markets` | `美股,港股` | 空=全部 |
| 形态 | 胶囊多选 | `forms` | `flash,article` | 空 |
| 内容类型 | 胶囊多选 | `kinds` | `flash,peer_article` | 空 |
| 信息类别 | 下拉多选 | `info_types` | `filing,research` | 空 |
| 事件类型 | 下拉多选 | `event_types` | `earnings,policy` | 空 |
| 渠道 | 下拉多选 | `channels` | `web,api` | 空 |
| 具体源 | 可搜索多选（选项来自 `/v1/sources`） | `sources` | `jin10,wscn` | 空 |
| 情绪 | 三态按钮 | `sentiments` | `positive` | 空 |
| 标的 | 标签输入框 | `tickers` | `NVDA,TSLA` | 空 |
| 时效 | Radio 单选 | `since` | `2026-09-02 09:00` | 前推 24h |
| 折叠重复 | Checkbox | `dedup` | `1`/`0` | `1` |
| 优先中文 | Checkbox | `display` | `1`/`0` | `1`（读 text_zh/title_zh） |
| 每页条数 | 下拉 | `limit` | `50`（≤1000） | 50 |
| 翻页 | 系统传递 | `cursor` | 服务端游标 | 空 |

**组件清单**：`SearchBar`（防抖检索）、`FilterGroup`（胶囊组，单/多选+计数气泡）、`FeedItemCard`（来源 Badge+情绪色标+打标词+折叠簇展收）、`ItemDetailDrawer`（中英对照+全量 JSON）、`MaterialCollectButton`（+加入素材箱）、`PaginationBar`（游标式）。

### 3.2 图文页（本期壳+留桩）

```text
+--------------------------------------------------------------------------------------------------+
| [素材暂存箱(3条)]                    | [工作流控制]                                                |
| 1.[美联储暗示降息节奏...] [移除]     | 工作流: [morning-paper(财经晨报) ▼]  日期:[2026-09-03]      |
| 2.[晶圆代工产能紧张...]   [移除]     | 模式: (•)--auto 全流程  ( )单步审核断点   参数:[--set k=v]  |
| [+从资讯页添加] [清空]               | [🚀 启动图文生成(留桩)]  [⏹ 终止(disabled)]                 |
+--------------------------------------+-------------------------------------------------------------+
| [状态机看板] 读 data/runs/morning-paper/2026-09-03/run.json (真实只读回显)                          |
| fetch done(5.4s) → synth done(42.7s) → article done → image done → review ⏸waiting_review         |
+--------------------------------------------------------------------------------------------------+
| [产物预览: article-2026-09-03.md]        | [流转发布(留桩)]                                        |
| # 9月3日 全球财经要闻早报 (md 渲染)      | [👍审核通过] [📝编辑] 目标文件:[早报-2026-09-03.md]       |
| ## 核心关注 ·宏观流动性...               | 预检: 发布必须 --draft 先行                             |
| (长图预览 output/long_image.png)         | [📥 推入待发队列(留桩·灰显)]                            |
+------------------------------------------+---------------------------------------------------------+
```

**组件清单**：`MaterialPocket`（素材篮，sessionStorage 暂存、跨页携带）、`WorkflowSelector`（扫描 flows 包清单）、`RunStateMachine`（done/running/waiting_review 步进器，数据来自后端 `workflow_reader` 只读扫描）、`MarkdownPreview`、`QueueActionStub`。

### 3.3 视频页（本期壳+留桩）

```text
+--------------------------------------------------------------------------------------------------+
| [口播/分镜素材]                        | [视频工程配置]                                            |
| 引用早报稿:[2026-09-03 ▼] 分镜5幕      | 项目ID:[morning-20260903]  画幅:(•)9:16抖音 ( )16:9 B站   |
| 幕1(0-12s): 美联储鸽派发声...          | 模板:[TechTerminal-Dark ▼]  语音:[财经男声 EdgeTTS ▼]     |
| 幕2(12-28s): 半导体产能超预期...       | 配乐:[CyberBreeze ▼] 音量15%                              |
| [分镜微调] [重新生成口播(留桩)]        | [🎬 开始合成渲染(留桩)]                                   |
+----------------------------------------+-----------------------------------------------------------+
| [渲染控制台(留桩)] 未来实时回传 cli.py video build <id> 的 stdout 日志                              |
+--------------------------------------------------------------------------------------------------+
| [产物视窗 videos/<id>/out/*.mp4]         | [流转发布 run-video(留桩)]                              |
| +------------------+  1080x1920 60fps    | 平台(读 targets.yaml):[✓]B站(--draft) [✓]抖音(--draft) |
| |  HTML5 播放器    |  01:08 / 42.5MB     | 标题:[9月3日晨间全球财经极速看]                        |
| +------------------+  [◀5s][▶][5s▶]      | [🚀 一键发布视频(强制 disabled)]                      |
+------------------------------------------+---------------------------------------------------------+
```

**组件清单**：`StoryboardEditor`（分镜折叠列表）、`VideoConfigForm`、`RemotionLogViewer`（本期占位）、`VideoPlayerModal`（HTML5 video 挂本地产物，经后端静态路由只读暴露 `videos/*/out/`）、`VideoPublishBridgeStub`。

### 3.4 追踪页（本期纯 Mock 桩）

```text
+--------------------------------------------------------------------------------------------------+
| ⚠️ 演示沙盒: 当前为本地 Mock 数据, 未来由平台采集 Agent 回传真实运营数据                           |
+--------------------------------------------------------------------------------------------------+
| [覆盖平台 14家(8活跃)] [监控账号 12] [昨日阅读 184,200(+12%)] [昨日增粉 +1,420] [互动率 4.8%]      |
+--------------------------------------------------------------------------------------------------+
| 平台     账号           验证状态   粉丝     昨日播放   互动    状态     操作                       |
| 雪球     @宏观趋势洞察  已真发     42,100   28,400     1,240   ●正常   [抓取最新(留桩)]            |
| 抖音     @极速财经快讯  草稿验证   156,000  112,000    6,800   ●需人工 [重新登录(留桩)]            |
| 知乎     @硬核财经研报  风控停用   8,300    --         --      ⛔异常   [查看日志]                 |
+--------------------------------------------------------------------------------------------------+
| [爆款归因] 标题 | 首发时间 | 最佳平台 | 总曝光 | 增粉贡献 | 关联素材源 | [归因分析(留桩)]          |
+--------------------------------------------------------------------------------------------------+
```

**组件清单**：`MetricCard`（环比箭头+sparkline）、`AccountMatrixTable`（平台矩阵，平台清单数据源复用 `publish targets`/targets.yaml，保证 14 平台不维护第二份）、`ContentAttributionList`、`AgentSyncStubNotice`（沙盒提示条）。Mock 数据由后端 `tracking_stub.py` 按目标 Schema 产出，未来只换数据源不改前端。

### 3.5 设置页（含云端演进预留）

```text
+--------------------------------------------------------------------------------------------------+
| [1. 供数连接]                                                                                     |
| 途径: (•)本机/局域网  ( )私有数据站(Tailscale)  ( )云端集中供数(未来)                             |
| 端点: [http://127.0.0.1:8787          ] [⚡测试连接]  Key:[sk-***...] (127.0.0.1 免密可留空)      |
| 诊断: ●正常(12ms) | 库内 34,291 条 | 最新快照 2026-09-02(2.4MB) | [触发一次 sources refresh(留桩)]|
+--------------------------------------------------------------------------------------------------+
| [2. 环境体检] 复用 cli.py doctor 全项卡片化 + [重新诊断]                                          |
+--------------------------------------------------------------------------------------------------+
| [3. 账号与云端同步(预留)]                                                                         |
| 当前: 个人单机纯本地版  | 云端同步:[ ]启用(规划中)  网关:[https://...(禁用)]  [登录/注册(留桩)]   |
| 同步范畴(预留勾选): [✓]工作流模板 [✓]标签偏好 [✓]追踪配置 [ ]私有API Key(永不同步,本地隔离)       |
| [💾 保存设置(写 data/config.local.yaml)]  [还原出厂]                                              |
+--------------------------------------------------------------------------------------------------+
```

**组件清单**：`EndpointConfigForm`（URL 校验+Ping 探活）、`DoctorDashboard`、`LocalTriggerButton`、`CloudSyncStubCard`。

## ④ 与 sources serve 的数据契约 + 本地→云端演进预留

**端点消费矩阵**（全部只读 GET，不向供数服务发任何写请求）：

| 端点 | 消费方 | 时机 | 用途 |
|---|---|---|---|
| `GET /v1/health` | 顶栏状态灯、设置页 | 加载+30s 轮询 | 绿/黄/红灯 |
| `GET /v1/sources` | 资讯页"来源"筛选项、设置页 | 资讯页初始化 | 动态填充源选项+健康标 |
| `GET /v1/sources/{id}` | 条目详情抽屉 | 点来源名 | 单源健康详情 |
| `GET /v1/items` | 资讯页核心 | 加载/筛选变化/翻页 | 15 参数映射见 ③ 表 |
| `GET /v1/status` | 设置页 | 进入时 | 刷新账本+dead 源告警 |
| `GET /v1/snapshot/latest` | 设置页"下载离线包" | 点击 | 浏览器原生保存 gzip |

**鉴权**：Key 在设置页录入 → 存 `localStorage` + 后端 `data/config.local.yaml`；`request.js` 统一注入 `Authorization: Bearer <key>`；检测到目标为 127.0.0.1 且无键时自动省略（对齐 serve.py 的 localhost 免密逻辑）。

**直连 vs 代理（混合架构）**：默认浏览器直连 `http://127.0.0.1:8787`（CORS 已开、零中转损耗、工作台后端挂了资讯页仍可用）；仅当直连抛 `TypeError: Failed to fetch`（未来 HTTPS mixed-content / 跨网段 Private Network Access）时透明回退 `http://127.0.0.1:8501/api/proxy/sources/*`。

**云端演进预留**：
```javascript
// store/settings.js 的配置抽象(本期即定型, 上云时前端零改动)
DataSourceConfig = {
  mode: 'local',                 // local | lan | cloud
  endpointUrl: 'http://127.0.0.1:8787',
  apiKey: '',
  cloudSync: { enabled:false, authServerUrl:'', userToken:null, userId:null,
               syncIntervalMinutes:15, lastSyncedTimestamp:null }
}
```
后端预留 `routes/api_sync.py`：`POST /api/v1/cloud/sync/push`、`GET /api/v1/cloud/sync/pull`，本期一律返回 **501 Not Implemented**；设置页第 3 区块即是其 UI 槽位。未来上云 = 填 `endpointUrl`+换 JWT 注入，接口 Schema v2 不变。

## ⑤ 与 ai-workflow / auto-publisher 的衔接点

| 目标 | 方式 | 路径/命令 | 本期形态 | 未来 |
|---|---|---|---|---|
| flows 运行状态/产物 | 纯文件只读扫描 | `data/runs/<flow>/<date>/run.json` + 步骤存档 | **真实回显**（图文页状态机看板） | 文件监听自动重载 |
| generator 历史产物 | 纯文件只读 | `ai-workflow/generator/output/` | **真实列表**+md/长图预览 | 在线对比回溯 |
| 视频产物 | 纯文件只读 | `ai-workflow/video/videos/<id>/out/*.mp4` | **真实播放**（后端静态路由暴露） | 参数重编 |
| 触发工作流 | 子进程（未来） | `python cli.py flows run <name> --auto` | **留桩**：点击弹模态框展示命令预览 + [复制命令] + [加载 Mock 产物] | 后端托管子进程+SSE 推 stdout |
| 待发队列 | 纯文件只读 | `auto-publisher/autopub/articles/*.md\|docx` | **真实列表** | 在线编辑草稿并写入 |
| 发布账本 | 严格只读（红线：禁手编） | `auto-publisher/autopub/state.json` | **真实只读列表**（追踪页发布记录） | 永远只读，仅轮询 |
| 真发布 | 子进程（未来） | `python cli.py publish run --draft` / `run-video --draft` | **强制 disabled** + Tooltip 红线提示（--draft 先行/接管 9222 Chrome/人工过验证码） | --draft 验证流，exit 2 转人工提示 |

**留桩 UX 三件套**（本期统一规范）：①生成类按钮 → 命令预览模态框（防误触真实跑批）；②流转类按钮 → 灰显+说明文案；③发布类按钮 → 硬 disabled+红线 Tooltip。所有"真触发"未来只能由 workbench 后端经 `subprocess` 调 `cli.py`（遵守"Python/Node 只经子进程+JSON"红线），后端绝不直接 import 三板块内部实现驱动物理操作（AGENTS.md 契约）。

## ⑥ 分期实施计划

**本期（Phase 1：UI 壳 + 资讯页真实只读 + 功能留桩）**，两个里程碑：

- **M1 骨架**：`workbench/` 目录+FastAPI 静态托管+hash 路由+5 页线框级 UI+tokens.css+cli.py 挂载+doctor 扩展。验证：`python cli.py workbench serve --open` 拉起，5 页可切换，DevTools 无 404/跨域报错。
- **M2 资讯页真实接数**：`/v1/items`+`/v1/sources` 对接，15 参数筛选映射、`dedup`/`display` 开关、游标分页、详情抽屉、素材箱（sessionStorage）；其余 4 页按 ⑤ 表回显真实只读数据（run.json/队列/账本/视频产物），写操作全留桩。验证：筛选/搜索/折叠/译文全链路行为与 `curl` 直打 serve 的结果一致。

**后续分期**：
- **Phase 2 工作流打通**：后端受控托管 `flows run`/`video build` 子进程，SSE 实时日志；图文页在线编辑+审核通过写队列（仍人工终稿）。
- **Phase 3 发布控制台+真实追踪**：合流并取代 `autopub/webapp`（5001）旧控制台；平台矩阵勾选+9222 状态反馈；追踪页接真实采集 Agent。
- **Phase 4 云端协同**：账号登录、`api_sync.py` 实装、远程数据站/云端网关接入。

**干净 clone 冒烟验收（本期交付判据）**：全新机器不装任何 Node 前端工具 → `git clone` → 装 Python 依赖 → `python cli.py doctor`（新增 workbench 项通过）→ 终端 A `python cli.py sources serve` → 终端 B `python cli.py workbench serve --open` → 浏览器自动开 `#/feed`，筛选/搜索/折叠/译文/分页全通 → 其余 4 页壳完整、桩按钮行为符合 ⑤ 规范 → `git status` 无 `data/` 脏跟踪、`state.json` mtime 全程未变（零写红线）。

**待用户拍板的开放点**：①本期是否接受"资讯页直接接真实只读数据"（建议接受，零写风险；若严格只要纯壳，M2 降级为 Mock 数据即可，结构不变）；②工作台端口 8501 是否认可；③追踪页目标 Schema 需要用户后续提供各平台粉丝/流量字段口径，本期先按演示 Schema 留桩。
