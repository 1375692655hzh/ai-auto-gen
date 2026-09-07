# 22-grok-contentgen — 内容生成页规划 MoA · grok 答卷(阶段一)

> 同题。grok 岗位(Grok Build CLI 无头模式), 2026-09-06。阶段一不联网。

## 一、GitHub 查阅清单（供下一阶段 grok 统一检索）

**模块1：快照抓取（行情图）**
- 关键词：`stock chart screenshot python`、`candlestick chart render`、`kline chart generator`、`tradingview chart image api`
- 候选项目：mplfinance、lightweight-charts-python、KLineChart/klinecharts（前端渲染再截图）、apache/echarts（node 端 SSR 出图）、yfinance、akshare、stooq 数据源
- 验证标准：stars>2k、近半年有提交、纯 pip 可装（排除 talib 这类 C 编译依赖）、离线可用性（渲染层必须离线；数据层允许在线但需确认 ToS 与免 key）、输出 PNG 质量足以直接发 X

**模块2：技术分析（支撑/阻力位）**
- 关键词：`support resistance levels python`、`pivot points stock`、`technical analysis library`
- 候选项目：pandas-ta、bukosabino/ta、tradingview-ta、ppsr 类专门算支撑阻力的小库（需核实维护状态）
- 验证标准：纯规则计算零 LLM（对齐 x_surge.py 的 calc_fv 先例）、输入只要求 OHLCV DataFrame、无强制 API key、能输出具体价位而非只给信号

**模块3：聚合分析（含 FactReach 核实）**
- 关键词：`FactReach github`（**首要核实**：该项目是否真实存在、实际功能是否如用户所想的"多源事实聚合/观点调查"，还是名不副实）、`mixture of agents`、`multi source news summarization llm`、`stance detection social media`
- 候选项目：togethercomputer/MoA（多智能体聚合）、FinGPT、FinRobot、OpenBB（投行观点数据面）
- 验证标准：FactReach 若存在需报 stars/最近提交/license/实际 README 定位；聚合类项目看能否只借其"多观点→共识/分歧"的 prompt 结构而非整套依赖

**模块4：X 平台风格与字数规则**
- 关键词：`X twitter character limit 280 weighted CJK`、`twitter text parsing library`、`twitter-text`（官方 twttr 文本解析/计权库，分 java/js/rb 三版）、`x post style guide finance`
- 候选项目：twitter/twitter-text（官方计权规则，验证中文按 2 字符计的具体实现）、公开的 X 推荐算法仓库（twitter/the-algorithm，看热度信号而非发帖风格）
- 验证标准：字数规则以 twitter-text 官方库或 X 官方帮助页为准（免费 280 加权字符/CJK 计 2/付费 25000）；风格学习优先用站内已有 SoPilot 热帖缓存（x_surge_rss.json）做 few-shot 样本，GitHub 只补充结构化写法约定（hook 行/分行/hashtag 数量/cashtag $TICKER 惯例）

## 二、实现方案（逐条对齐用户构想，不偏离）

**总体架构**：沿用 vstudio.py 已定型的"服务器端点零外呼 + spawn CLI 子进程干活 + 轮询 job 状态"模式。新增 CLI 命令 `python cli.py workbench gen-compose --json` 做真编排；新增 `workbench/server/gcompose.py` 管 job 状态与结果 JSON（写 data/workbench/ 自有文件，红线7合规）；app.py 注册 `/wb-api/gen-compose`（POST 启动）、`/wb-api/gen-jobs`（GET 轮询）、`/wb-api/gen-assets/<file>`（GET 出图，仿 video_file 先例）。

**逐条落地**：
1. **素材池加长**：纯前端改动，article.js 三列布局里 `.mat-pool` 的 max-height 调大或改为整列通高滚动（web/css 一处），零风险。
2. **信息检索**：已完成（retrieve.py），编排时直接 in-process 调 `retrieve.run()` 复用结果作上下文。
3. **快照抓取**：CLI 进程内执行——tagger 从素材抽 ticker（词典自带市场后缀 NVDA/600519.SH/0700.HK）→ yfinance/akshare 拉近 3 个月日线 → mplfinance 离线渲染 PNG（含成交量）→ 存 `data/workbench/gen_assets/`。**选自绘而非网页截图**：无页面结构脆弱性、无版权水印、离线可控；playwright 截图 tradingview 作备选降级。
4. **技术分析**：同一 OHLCV 数据上纯规则计算（近期摆动高低点聚类 + 枢轴点），输出"阻力位 X/Y、支撑位 Z"具体价位；LLM 只负责把数字写成一句话，不做判断。
5. **聚合分析**：数据面全用站内只读能力——retrieve 三路回查拿同事件条目 + 数据站 X 池按"定位=大V"过滤 + 机构/官方源条目，分两组（X 大V 观点 / 投行机构观点）各做 LLM 摘要，第三次 LLM 调用汇总共识与分歧。LLM 走 `generator/common.py gen_llm()`（默认 ark:kimi-k3，密钥链已有），workbench 不另建密钥。FactReach 待核实后若可用，仅借鉴其检索-验证 prompt 结构。
6. **平台风格/语种/免费付费/模板**：生成页中部新增四个 select（平台默认 X、语种 en/简中/繁中/ja/粤语、免费=280 加权字符硬截断·付费=25000、模板=短文/长文×早报/精华资讯，早报模板映射已有 flows builtin morning-paper/morning-digest 的 prompt 资产）。字数用 X 计权规则（CJK=2）在前端实时计数 + 服务端硬约束。风格 few-shot 样本取自 x_surge_rss.json 高 prob 热帖。
7. **开始生成→成稿→复制**：按钮点亮后 POST 启动 → 轮询 → 实时编辑区下方渲染成稿卡（文字+图片+标签）。复制用 `navigator.clipboard.write()` 写 ClipboardItem 双 MIME（text/plain + image/png），Chrome 下粘贴进 X 发帖框可文图同入；失败降级为"复制文字 + 自动下载 PNG 待手动拖入"。草稿 schema 扩展 platform/lang/tier/assets 字段，仍只写 drafts.json。

**风险与依赖**：① yfinance/akshare 数据源的稳定性与 ToS（需 grok 检索确认，必要时 stooq 兜底）；② FactReach 名实不符风险——先核实再决定是否采用；③ X 粘贴文图同入依赖浏览器 Clipboard API 行为，需实测 Chrome/Edge；④ 粤语/繁中长文质量依赖 kimi-k3，建议首版只对免费短文做全语种，长文付费档第二期开。
