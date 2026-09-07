# 23-gemini-contentgen — 内容生成页规划 MoA · gemini 答卷(阶段一)

> 同题。gemini 岗位说明: agy CLI 两路不可用(OAuth 过期需交互登录; claude 路 eligibility EOF), 该岗 agent 按 MoA 纪律直读代码库独立产出, 2026-09-06。

## 一、GitHub 查阅清单（交 grok 统一执行）

**模块1 快照抓取·行情图**
- 关键词：`mplfinance candlestick`、`akshare K线`、`yfinance chart API`、`stock chart image generator python`、`lightweight-charts screenshot`；中文：`股票行情图 生成 python`、`K线图 绘制`
- 候选（待核实）：mplfinance（纯 matplotlib 画 K 线，离线可用）、akshare（A/港/美行情接口集，无 key）、yfinance（美股历史，无 key 但限流）、TradingView lightweight-charts（JS 渲染+headless 截图路线，项目已装 playwright）
- 验证标准：stars >3k；近 6 个月有提交；纯 Python 无 C 编译（排除 TA-Lib 路线）；Windows+Py3.11 兼容；离线可用性区分"画图库（离线）"与"数据库（需外网）"；是否需 API key

**模块2 技术分析·支撑阻力**
- 关键词：`support resistance detection python`、`pivot points algorithm`、`swing high low clustering`、`stockstats`、`pandas-ta`
- 候选（待核实）：pandas-ta、stockstats（含 pivot/fibonacci）；专门小仓库如 support-resistance 类（需 grok 验质量）；备选零依赖自实现：scipy.signal.argrelextrema 局部极值+价格带聚类
- 验证标准：纯计算离线（数据由模块1供给）；结果可经 mplfinance addplot 叠画水平线；依赖栈轻

**模块3 聚合分析（含 FactReach 核实）**
- FactReach 核实要点：真实 owner/全名、是否"事实核查 pipeline"而非"观点汇总"、stars/最后提交/license、可否拆出"多源采集→LLM 归并"子流程、LLM key 依赖
- 关键词：`FactReach github`、`multi-source news aggregation LLM`、`analyst ratings API`、`finnhub analyst recommendations`、`东财 研报 抓取`
- 判断：大 V 观点优先复用项目内已有 X 池（板块一 twitter_pool + retrieve 同簇多源），投行观点候选 finnhub（免费档有 analyst ratings，需 key）或东财研报页（结构不稳定）

**模块4 X 平台风格与字数**
- 核实点：280 字符/CJK 按 2 加权（≈140 汉字）当前政策；Premium 长文 25,000 上限；X 帖文体（首行 hook、短句换行、hashtag 1-3 个、$cashtag、emoji 节制、thread 拆分惯例）
- 候选：`twitter-text`（官方文本加权计数库及社区 fork/port）——验证维护状态与 CJK weight=2 的 config；离线纯库即可

## 二、实现方案

**总线（全按 app.py 既有先例）**：新增 `workbench/server/gen_post.py`（任务状态/产物只读视图）+ cli.py 新增 `workbench gen-post` 子命令。端点 `POST /wb-api/gen-post` 只做参数校验+begin_job+`subprocess.Popen(CREATE_NO_WINDOW)` spawn CLI（复制 video-analyze 模式）；前端轮询 `GET /wb-api/gen-jobs`；产物落 `data/workbench/gen_posts/<id>/`（chart.png + post.json），图经 `/wb-api/gen-posts/{id}/file/{name}` FileResponse 供前端（artifact_file 先例）。红线 7 合规：端点零外呼，外网/LLM 全在 CLI 进程；写口仅 data/workbench/ 自有目录。

**数据流**：勾选素材 →（已有 retrieve 补全）→ 复用 `retrieve._enrich` 只读 tagger 抽 tickers →
- **snapshot**：CLI 进程直拉东财 push2his / Yahoo chart v8 接口（无 key，裸 requests，对齐板块一"akshare 端点移植"惯例，代码放 workbench 包内）取日线序列 → mplfinance 画 K 线图存 png（新装 matplotlib+mplfinance，Windows pip 无 C 编译）
- **tech**：同一份序列纯规则算支撑/阻力（局部极值+聚类价格带），addplot 叠画水平线进同图或单独图，零 LLM（对齐 x_surge 哲学）
- **aggregate**：大 V 路=retrieve B/C 路同簇多源+X 池同标的近窗帖；投行路=finnhub（配 key 走 settings）或东财研报，一期可降级留配置口；汇总走 `generator/common.py` llm 桥（默认 ark:kimi-k3）
- **组装**：模板（早报/精华资讯沿用板块二 flows YAML 只读引用）+语种/风格/字数档进 prompt；字数闸自实现加权计数（CJK×2，免费 280/付费 25,000），成稿=正文+图路径+标签（tickers 转 $cashtag）

**UI（article.js）**：① `.mat-pool` 加高（用户明确诉求）；② 生成模块卡下新增三行选择器：平台风格（默认 X）/语种（英默认、简中、繁中、日、粤）/免费·付费；模板下拉已有；③ 点亮"开始生成"：POST→轮询→成稿卡渲染到实时编辑区下方（文字+图+标签）；④ 复制：文字走 `WB.copyText` 先例；图文一起用 `navigator.clipboard.write(ClipboardItem{image/png, text/plain})`（127.0.0.1 安全上下文满足，Chromium 支持），失败降级"复制文字+下载图片"双按钮。

**风险与依赖**：行情接口限流/结构变动（需 UA+重试+降级提示）；投行路源不稳，一期可只做"大 V+多源"；粤语/繁中 prompt 需样例校准；LLM 走 CLI 子进程为分钟级，前端需进度态；twitter-text 若用 JS 版需 vendored 引入免构建 SPA，建议后端 Python 自实现加权计数更稳。
