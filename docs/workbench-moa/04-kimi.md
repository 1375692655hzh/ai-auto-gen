# MoA 答卷 ④ — kimi（第四板块·前端工作台 执行方案）

> 2026-09-03 同题并行任务原文：「制定执行方案并且汇总出最优先的plan，执行」。以下为 kimi 答卷原文（模型 kimi-code/k3）。

---

以下方案来自 Kimi（模型 kimi-code/k3，1M 上下文），它已实际通读 `AGENTS.md`、`docs\三大板块实施方案.md`、`cli.py`、`global-news-sources\sources\serve.py`、`global-news-sources\docs\供数服务.md` 及板块二/三目录结构后产出。全程只读，未改动仓库任何文件。以下为方案原文：

---

# 第四板块【前端工作台】执行方案

## 现状摸底结论（实际读到的关键事实）

- **cli.py 挂板机制**：根目录 `cli.py`（548 行）用 argparse 两级子命令；每板块通过 `sys.path.insert(0, 板块目录)` 挂板——`GNS=global-news-sources/`、`AIWF=ai-workflow/`、`PUB=auto-publisher/`。原生命令（`sources`/`flows`/`doctor`/`publish status`）在 cli.py 内 import 板块模块实现；透传命令（`gen`/`publish login|run|run-video`/`video build`）走 `_passthrough()` 子进程并透传退出码。退出码语义：`0 成功 / 2 需人工 / 3 业务失败 / 4 配置缺失`，`doctor --json` 输出 `{overall, checks[]}`。
- **sources serve 端点**（实现于 `global-news-sources/sources/serve.py`，208 行，FastAPI+uvicorn，默认 127.0.0.1:8787）：全 GET 零写——`GET /v1/health`、`GET /v1/sources?markets=&channels=&forms=&kinds=`（返回 `{total, sources[]}`）、`GET /v1/sources/{id}`、`GET /v1/items`（11 个过滤参数：markets/kinds/info_types/event_types/channels/forms/sources/tickers/sentiments/q/since + limit≤1000/cursor/dedup/display，返回 `{total, next_cursor, items[]}`）、`GET /v1/snapshot/latest`（gzip，单独限流）、`GET /v1/status`（refresh 账本+库统计+dead 源）。鉴权：`Authorization: Bearer <key>`（或 `X-API-Key`），键在 `global-news-sources/config/api_keys.local.json`；**文件无键且 localhost 时免密**；超限 429+Retry-After。条目 Schema v2：必有 `id/source_id/source/time/text`，可选 `title/url/media`；源四标签打平进每条（`kind/form/channel/markets[]/lang`），另有规则/LLM 打标 `tickers[]/event_type/sentiment/sectors[]`、中译字段（display=1 时 text/title 直接给中文，原文在 text_src/title_src）、时效 `time/fetched_at`、去重 `cluster_id/dup_count`。channel 枚举见 `sources/tags.py`（exchange/media_official/media_finance/data_vendor/broker_research/kol/social_official/aggregator 八类）。
- **产物目录约定**：图文产物在 `ai-workflow/generator/output/`（`daily/daily-<date>.json` 结构化条目 + `早报长图-<date>.png` + `口播/`）；flows 引擎产物在 `data/runs/<流>/<日期>/run.json`（status: done/waiting_review + artifacts 清单）；视频产物在 `ai-workflow/video/videos/<id>/`（`story.json`、`project.json` 门禁 draft→reviewed→built、`out/final.mp4` + `cover.png` + `preview-silent.mp4`）；待发队列 = `auto-publisher/autopub/articles/*.md|*.docx`（发完全平台自动归档 `_done/`）；发布账本 `auto-publisher/autopub/state.json`（原子写+损坏熔断，agent 只读）。
- **发布门面**：`auto-publisher/publish/facade.py` 提供 `platform_status()`（读 targets.yaml×autopub config.yaml 得 14 平台矩阵）、`ledger_view()`、`run_publish(platforms, draft)`——后者只路由 autopub 引擎、kit 平台显式拒绝，子进程调 `publish_all.py`。
- **已有先例**：`auto-publisher/autopub/webapp/app.py`（填密钥的网页）证明"本机工具 + 浏览器 UI"形态已被项目接受；doctor 已把 fastapi+uvicorn 列为 warn 级依赖检查项。

---

## ① 技术栈选型及理由

### 前端：**无构建 Vanilla SPA（单壳 HTML + ES Modules + hash 路由）**，不选 React/Vite

结论明确，理由：

1. **"下载即用"是硬约束**。三板块全部 `pip install` 后即可跑，Node 仅在视频/API 发布时才需要（doctor 里 node 是 warn 级）。若前端用 React/Vite，等于把 Node+构建链变成每个用户的必装项，直接破坏现有交付形态。仓库里 Remotion 已吃了 node_modules 的复杂度，不应再增加第二处。
2. **5 个页面的交互复杂度可控**。资讯页=列表+筛选+分页，图文/视频页=产物浏览+按钮触发命令，追踪页=表格/图表，设置页=表单。Vanilla JS + 少量自写组件（筛选条、分页、Toast）完全够用，不需要框架的状态管理。
3. **ES Modules 原生支持**：`workbench/static/` 下 `app.js` + 每页一个模块（`pages/feed.js` 等），`<script type="module">` 直接加载，零打包。样式用一份手写 CSS（CSS 变量做主题，对齐现有终端工具的简洁风），不引 UI 框架。
4. **演进缝**：若未来页面复杂度爆炸（如在线编辑器），可平滑迁到"预构建产物直接入 git"的 htmx/alpine 轻量方案，或把 React 构建产物 commit 进 static/——后端契约不变，前端整目录替换即可。

### 后端：**新增独立 FastAPI 服务（复用 fastapi+uvicorn 依赖），不扩展 sources serve，不用裸 http.server**

理由：

1. **复用现有依赖零增量**：fastapi+uvicorn 已是 sources serve 的依赖，doctor 已有检查项，用户大概率已装。
2. **职责分离（对齐供数服务的"读写分离"哲学）**：`sources serve`（8787）是**数据站读侧**，契约是"只读供数、零写、Bearer 配额"（`global-news-sources/docs/供数服务.md`），往里塞页面托管/命令触发会污染其边界；工作台有自己的横切需求（静态文件托管、子进程触发 cli 命令、读本地产物目录），独立服务更干净。
3. **不选 http.server/Flask**：工作台后端要做 SSE/轮询推送长任务进度（flows run / publish run 是分钟级任务），FastAPI 原生支持；且与 `sources/serve.py` 同构（`create_app()` 工厂 + `run(host, port)`），代码风格直接对齐，降低维护成本。
4. **默认绑 127.0.0.1:8765**，遵守同一网络红线（对外须显式 --bind，禁裸开公网）；本机使用免鉴权（与 sources serve 的 localhost 免密语义一致）。

---

## ② 新板块目录结构与 CLI 挂载

与三板块平级新增 `workbench/`（第四板块，可单独下载的承诺保留——但数据消费依赖 sources，故 README 注明依赖关系）：

```
workbench/
├── README.md                  # 板块说明+依赖矩阵(数据依赖板块一, 动作依赖二三)
├── __init__.py
├── server.py                  # create_app() 工厂 + run(host,port) —— 对齐 sources/serve.py 结构
├── config.py                  # 读写 data/workbench/config.local.json(信息源地址/Key/云端预留)
├── proxy.py                   # /api/v1/* → 信息源(base_url+key 注入), httpx/urllib 服务端转发
├── actions.py                 # 子进程桥: 只调 `python cli.py ...`, 幂等+并发互斥锁(防双触发发布)
├── views.py                   # 只读视图: generator/output 列表 / articles 队列 / video/videos / publish status
└── static/
    ├── index.html             # 单壳: 顶栏+侧栏+<main id=page>, hash 路由
    ├── app.js                 # 路由器 + api client(fetch 封装, 统一错误/429处理)
    ├── style.css              # 全局样式+CSS变量主题
    ├── components.js          # 筛选条/卡片列表/分页/Toast/状态徽章
    └── pages/
        ├── feed.js            # 资讯页
        ├── article.js         # 图文页
        ├── video.js           # 视频页
        ├── track.js           # 追踪页
        └── settings.js        # 设置页
```

运行时数据：`data/workbench/config.local.json`（gitignored，对齐 `data/config.local.yaml` 语义）。

**CLI 挂载**（参照现有挂板方式，改 `cli.py` 三处）：

```python
WB = ROOT / "workbench"                    # 第四板块常量
# main() 里:
p_wb = sub.add_parser("workbench", help="前端工作台(板块四)")
wsub = p_wb.add_subparsers(dest="sub", required=True)
wv = wsub.add_parser("serve", help="启动工作台(默认 127.0.0.1:8765)")
wv.add_argument("--host", default="127.0.0.1"); wv.add_argument("--port", type=int, default=8765)
wv.add_argument("--bind", default=None)      # 与 sources serve 同语义
# 分发:
if args.cmd == "workbench":
    sys.path.insert(0, str(WB))
    from workbench import server
    return server.run(host=args.bind or args.host, port=args.port)
```

即 `python cli.py workbench serve [--bind/--port]`；`bin/aag.cmd` 是 wrapper 无需改。

**doctor 纳入**：`doctor()` 中追加一项检查——工作台端口 8765 可达性 + fastapi 依赖已查则复用，新增 `_check("工作台配置", config 文件存在或可创建)`；`workbench serve` 自身支持 `--json` 不需要（它是常驻进程），但 doctor 的 `checks[]` 加 `workbench` 条目即可被 agent 消费。AGENTS.md 的命令速查表与目录地图届时同步加一行（实施期任务，本轮不动）。

---

## ③ 五个页面 UI 布局设计

**全局骨架**（index.html）：顶栏（左：产品名+当前页标题；右：信息源连接状态徽章——轮询 `/api/v1/health`，绿/红）+ 左侧栏（5 个导航项，当前项高亮）+ 主区。hash 路由：`#/feed | #/article | #/video | #/track | #/settings`。

### 1. 资讯页（#/feed）——本期核心页

- **布局**：主区顶部=筛选条，下方=条目卡片流，底部=分页。
- **筛选条设计（对齐四标签体系）**：
  - 第一行：**市场** chips（多选，取值来自 `/v1/sources` 返回的 markets 聚合，如 A股/港股/美股/台湾/全球）+ **kind** chips（flash 快讯/peer_article 文章/calendar/market/announcement/evidence）。
  - 第二行：**渠道**下拉（八枚举：exchange 官方/media_official 官媒/media_finance 财经媒体/data_vendor 数据商/broker_research 券商研究/kol 个人/social_official 机构号/aggregator 聚合）+ **形态** forms chips + **event_type/sentiment** 下拉 + 搜索框（`q` 拆词 AND，中英同检）。
  - 筛选状态映射 URL hash query（`#/feed?markets=美股&sentiments=利空`），可刷新可分享；每次变更重新请求 `/v1/items`。
- **卡片**：标题（display=1 已是中文，原文悬停 title 提示 text_src）、来源徽章（source+channel）、时间、情感/事件类型标签色点、正文摘要、`url` 外链按钮。簇条目显示 `dup_count` 角标（dedup=1 默认折叠，提供"展开同事件 N 条"交互切 dedup=0）。
- **分页**：游标式（next_cursor），"加载更多"按钮 + limit=100 默认。
- **组件清单**：FilterBar、Chip、Card、CardList、LoadMore、HealthBadge、Empty/Error 态。

### 2. 图文页（#/article）

- **布局**：左侧栏二级列表（生成产物清单），右侧预览+操作区。
- **数据源**（本期只读）：`/api/artifacts/articles` → 后端扫 `ai-workflow/generator/output/daily/`（daily-\*.json 渲染成条目列表预览）+ `data/runs/<flow>/<date>/run.json` 的 artifacts；**待发队列** `/api/queue` → 后端扫 `auto-publisher/autopub/articles/*.md|*.docx`（与 `publish status --json` 的 queue 字段同源）。
- **组件清单**：ArtifactList（按日期分组）、MarkdownPreview（自写极简 md→html，防 XSS 白名单）、ImagePreview（长图 png）、QueuePanel、ActionBar。
- **交互要点**：选产物→"放入待发队列"按钮（留桩，P2 才实做=复制文件到 articles/）；队列项显示发布覆盖状态（对照 state.json 账本中该文章各平台 status，只读）。

### 3. 视频页（#/video）

- **布局**：左=视频项目列表（扫 `ai-workflow/video/videos/*/project.json`：id/title/status/builtAt/output），右=预览+操作。
- **组件清单**：ProjectList（状态徽章 draft→reviewed→built 着色）、VideoPlayer（`<video>` 指向 `/api/video/<id>/out/final.mp4`，后端静态映射只读）、CoverThumb（cover.png）、ActionBar（"构建"→ 桩，实做=`python cli.py video build <id>` 子进程+轮询 project.json；"投稿 B站/抖音"→ 桩，实做=`publish run-video --video ... --draft`）。
- **交互要点**：未 built 的项目禁用投稿按钮；构建中显示旋转态（轮询 project.json status 变化）。

### 4. 追踪页（#/track）

- **本期=纯桩页**：布局到位——顶=账号卡片区（预留多平台账号：雪球/东财/微博/B站/抖音），下=粉丝数/阅读量趋势图区（占位 SVG 折线，不引图表库）。
- **已有可用数据**：state.json 账本里每篇已发文章的 `url`——后端 `/api/published` 只读输出"已发布清单+链接"作为该区第一块真实内容。
- 粉丝抓取接口形状预留在设置页账号配置里（见④）。

### 5. 设置页（#/settings）

- **布局**：分节表单页，顶部保存按钮（Sticky）。
- **分节**：①信息源连接（见④契约）；②平台账号（预留：每平台账号名+追踪开关，本期只存不抓）；③云端同步（预留：登录/同步端点，本期灰显"即将支持"）；④关于（版本、数据目录路径、doctor 摘要——后端代理调 `python cli.py doctor --json` 渲染体检表）。
- **组件清单**：FormSection、KeyValueInput、SecretInput（key 打码显示）、DoctorPanel。

---

## ④ 与 sources serve 的数据契约与对接方式

### 实际暴露的端点（摘录自 `global-news-sources/docs/供数服务.md` 与 `sources/serve.py`）

| 端点 | 响应 | 工作台用途 |
|---|---|---|
| `GET /v1/health` | `{status, store, snapshot, registry_import_errors}` | 顶栏连接徽章 |
| `GET /v1/sources?markets=&channels=&forms=&kinds=` | `{total, sources[]}`（含四标签/启用/健康） | 资讯页筛选条枚举值 + 设置页源清单 |
| `GET /v1/items?...`（11 过滤参数+limit≤1000/cursor/dedup/display） | `{total, next_cursor, items[]}` | 资讯页主数据 |
| `GET /v1/snapshot/latest` | gzip 文件流 | 本期不用（留给"全量导出"功能桩） |
| `GET /v1/status` | `{refresh, store, health_dead}` | 设置页"数据站状态"卡 |

item 字段消费约定：`text/title`（display=1 中文）、`text_src/title_src` 原文、`source/source_id`、`time`（北京时）、`kind/form/channel/markets[]`、`event_type/sentiment/tickers[]`、`url`、`cluster_id/dup_count`。

### 对接方式：**前端不直连 8787，一律走第四板块后端代理**

`/api/v1/*` → 后端 `proxy.py` 服务端转发到配置的信息源地址。理由：

1. **CORS**：sources serve 未声明 CORS 中间件，浏览器直连 8787 跨端口（8765→8787）会被拦；后端转发彻底绕过。〔注：kimi 此处与实际不符，serve.py 已开 CORS——主控已核实〕
2. **Bearer Key 不出后端**：有键部署下，key 只存在 `data/workbench/config.local.json`，由后端注入 `Authorization` 头，永不进浏览器 localStorage/网络面板；localhost 免密场景自动不带。
3. **统一错误语义**：代理把 429（Retry-After）/连接失败翻译成前端统一错误 JSON，资讯页显示"数据站未启动？运行 `python cli.py sources serve`"引导。
4. 同时天然支持**局域网数据站**（供数服务.md 的消费方姿势 A：别人只给地址+Key）——工作台可以是"纯消费端"，用户本机不必跑抓取。

### 本地→云端演进预留

**配置项形状**（`data/workbench/config.local.json`，GET/PUT `/api/config`）：

```json
{
  "source": {
    "mode": "local",                    // local=本机127.0.0.1:8787 | lan=局域网数据站 | cloud=未来云端
    "base_url": "http://127.0.0.1:8787",
    "api_key": "",                      // 仅本机存储, 永不回显明文
    "timeout_s": 15
  },
  "accounts": {                         // 追踪页预留
    "xueqiu": {"name": "", "track": false}
  },
  "cloud": {                            // 未来登录同步预留, 本期字段存在但后端不消费
    "endpoint": "",                     // 云端 API 根
    "account_token": "",                // 登录后签发
    "sync_enabled": false,
    "sync_scope": ["config", "accounts"],
    "last_synced_at": null
  }
}
```

**接口预留**（本期返回 501 桩，形状定死）：`POST /api/cloud/login`、`POST /api/cloud/sync`、`GET /api/cloud/status`。关键设计：`source.mode=cloud` 时 proxy.py 的转发目标换成 `cloud.endpoint`——**前端代码零改动**，云端化只是配置切换+proxy 多一个分支，这是整个演进的核心缝。供数契约（/v1/* 路径与 item Schema）即是云端 API 必须兼容的协议，未来云端服务按 `供数服务.md` 实现即可无缝接入。

---

## ⑤ 与 ai-workflow / auto-publisher 的衔接点

**总原则：工作台后端只通过两种合规通道触达三板块——（a）只读文件扫描（产物目录/状态文件），（b）子进程调 `python cli.py <板块> <命令>`。绝不 import 内部模块驱动物理操作（AGENTS.md 驱动契约），绝不手编 `state.json`/`run.json`（红线 2）。**

### 图文页 ← ai-workflow + auto-publisher

- **读产物**：后端 `views.py` 扫 `ai-workflow/generator/output/daily/`（daily-\*.json 转预览、早报长图-\*.png 静态映射）与 `data/runs/<flow>/<date>/run.json`（`artifacts` 清单 + `status`，waiting_review 流显示"待审核"徽章）；扫 `auto-publisher/autopub/articles/` 得待发队列。
- **发布动作**：ActionBar "发布（草稿）"按钮 → 后端 `actions.py` 子进程 `python cli.py publish run --draft [--platforms ...]`，返回任务 id，前端轮询 `/api/jobs/<id>`（后端读子进程 stdout + 退出码）；**"真发"按钮默认禁用，必须前端二次确认弹窗（文案明示"将真实发布到 N 个平台"）后才允许去掉 --draft**——把 AGENTS.md 红线 1 固化进 UI。发布结果刷新自 `/api/publish/status`（后端读 state.json，**只读**）；`uncertain` 状态条目前端显示"需人工到平台后台核实"且不提供重试按钮（红线语义 UI 化）。
- **generate 触发**（P2 桩）：`python cli.py flows run morning-paper --auto`，exit 2（waiting_review）时前端引导用户去编辑产物文件后点"继续"。

### 视频页 ← ai-workflow/video + auto-publisher

- **读产物**：扫 `ai-workflow/video/videos/*/project.json`（status 门禁 draft→reviewed→built）；`out/final.mp4`、`cover.png`、`preview-silent.mp4` 由后端静态映射供 `<video>` 播放。
- **出片**：`python cli.py video build <id>` 子进程（Node 依赖，前端在 doctor 未过 node 项时禁用按钮并提示）。
- **投稿**：`python cli.py publish run-video --video <mp4 路径> --title <标题> --draft`，真发同样走二次确认；B站/抖音队列防重由适配器保证，前端不重复提交（按钮提交后即锁定至任务结束）。

### 追踪页 ← 发布账本

- 本期唯一真实数据：state.json 中 `published` 条目的 `url/time/platform`，展示"已发布链接清单"。粉丝/流量抓取是全新能力（各平台无现成只读接口），属于 P3 新开发，届时在 accounts 配置驱动下实现，**不本期承诺**。

---

## ⑥ 分期实施计划与最优先 Plan

| 期 | 交付物 | 留桩点 | 验收标准 |
|---|---|---|---|
| **P0 UI 壳+资讯页（本期核心）** | `workbench/` 目录全骨架；`cli.py workbench serve`；静态服务+`/api/v1/*` 代理；资讯页完整可用（筛选/分页/搜索/簇展开）；其余 4 页路由+布局占位（图文/视频页给真实只读列表，追踪/设置页占位文案）；设置页信息源配置真实可用（改 base_url/key 即生效）；doctor 加 workbench 检查项；AGENTS.md 加板块四一行 | 所有"动作按钮"渲染但禁用或点击返回"该功能将在下一期开放" | 干净环境 `pip install fastapi uvicorn` 后 `python cli.py workbench serve` 起服；浏览器开 8765 五页可切换；资讯页从本机数据站拉到真实条目并完成市场/渠道/形态/情感组合筛选与游标分页；改设置为局域网数据站地址+Key 后正常取数；无 Node 依赖 |
| **P1 生成衔接** | 图文页"放入待发队列"（文件复制）；flows run 触发+waiting_review 引导；视频页构建触发+轮询 project.json | — | 从工作台点一次"生成早报"能跑通 flows 断点续跑闭环；构建出的 final.mp4 可在页面播放 |
| **P2 发布衔接** | publish run --draft 任务化（jobs 轮询）；真发二次确认链；uncertain 只读提示；run-video 投稿 | — | 红线 1/2 在 UI 层不可绕过；draft 全流程走通且账本正确反映 |
| **P3 追踪+云端预留落地** | 追踪页账号粉丝抓取（新能力）；cloud.login/sync 桩换实现 | — | accounts 配置驱动抓取；`source.mode=cloud` 切换后前端零改动取数 |

### 最优先 Plan（第一期先做这些，按序）

1. **`workbench/server.py + proxy.py + config.py`**：FastAPI 服务能起、静态目录能托管、`/api/v1/*` 能转发到 127.0.0.1:8787 并注入 Key、配置文件读写——这是全板块地基，优先于一切 UI。
2. **cli.py 挂 `workbench serve` + doctor 检查项**：让板块四正式进入命令面与 agent 体检视野。
3. **index.html + 路由 + 全局骨架（顶栏健康徽章+侧栏五导航）**：五页空壳先立起来。
4. **资讯页全功能**：筛选条（四标签对齐）→ `/v1/sources` 取枚举；卡片流 → `/v1/items`；游标分页；搜索；簇展开。这是本板块存在价值的核心页面，唯一一期内做到"完整可用"的页面。
5. **设置页的信息源配置节**：mode/base_url/api_key 表单 + 保存即生效 + 连接测试按钮（打一次 /v1/health）。cloud/accounts 分节渲染占位。
6. **图文/视频页只读列表**（扫产物目录，纯展示，无动作按钮逻辑）：低成本高存在感，证明三板块数据已贯通。
7. **追踪页纯占位 + 已发布链接清单**（读 state.json，只读）。

原则贯穿全期：**前端永不直连 8787、永不写任何三板块状态文件、发布链路永远 draft 先行**——三条红线从 P0 第一天就写进代码结构（views.py 只读、actions.py 强制 draft 参数、proxy 单点收口），而不是靠约定。
