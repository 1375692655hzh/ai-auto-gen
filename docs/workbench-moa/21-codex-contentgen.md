# 21-codex-contentgen — 内容生成页规划 MoA · codex 答卷(阶段一)

> 任务: 内容生成页构想落地规划(素材池加长/快照抓取行情图/技术分析支撑阻力/聚合分析含FactReach核实/X平台风格与字数/模板与复制)。
> 阶段一约束: 不联网、不改文件, 只出「查阅清单 + 实现方案」。codex exec -m gpt-6-astra -s read-only, 2026-09-06。

**一、GitHub 查阅清单**

已只读核对指定文件；未联网、未改文件。以下为候选，维护状态、功能及平台规则均待后续核实。

通用验收标准逐项适用：通用库优先≥1000 stars，专项库≥100；近12个月有维护，稳定归档库须验证兼容性；记录许可证、依赖体积、Windows安装、自托管/离线能力、API key及数据费用。

1. **快照抓取**：关键词：股票K线截图／stock candlestick chart、TradingView screenshot、stock-chart export。候选：mplfinance、yfinance+matplotlib、TradingView/lightweight-charts、Playwright。分别验证：离线OHLCV出PNG；Yahoo行情覆盖与复权；自托管图表及导出；浏览器依赖、登录与截图授权。图表库本身不提供行情。
2. **技术分析**：关键词：支撑阻力／support resistance、pivot clustering、zigzag。候选：pandas-ta、TA-Lib、stockstats、day0market/support_resistance。前三者核实指标覆盖及Python/C依赖，不能把指标库当成完整支撑阻力算法；专项库核实聚类方法、参数、未来数据泄漏及离线复现能力。行情费用另计。
3. **聚合分析**：关键词：多源观点／multi-source opinion aggregation、X sentiment、analyst research、FactReach。FactReach须先核实存在性、仓库归属和定位，再验引用追踪能力；Tweepy验X官方接口权限、key及费用；snscrape验当前可用性、自托管和登录限制；GPT Researcher验搜索/LLM依赖、费用、引用与去重。均须验证能否取得投行原始观点，而非仅新闻转述。
4. **X风格与计数**：关键词：推文写作／Twitter writing best practices、awesome-twitter、weighted tweet length、CJK。候选：twitter/twitter-text、sindresorhus/awesome（沿索引找风格仓库）。前者验离线JS、加权长度、URL、emoji、组合字符测试；后者仅作导航，风格仓库另按通用门槛筛选，核查案例与广告倾向。付费长帖规则另核对官方说明，不能直接套短帖校验器。

**二、实现方案**

- **UI**：改 `workbench/web/js/pages/article.js` 及对应CSS，使 `.mat-pool` 随视口加高、内部滚动。保留四模块；快照文案由"原文页面快照"改为"股票行情图"。模块下设默认X、默认英语及简中/繁中/日语/粤语；免费/付费；短文/长文模板，复用早报、精华资讯结构。暂按需求配置免费280加权字符、汉字约140；付费Basic/Premium/Premium+上限25000，计量及权益待核实后定版。替换现有 `.length` 计数。
- **入口**：建议新增 `workbench/server/article_gen.py`、`snapshot.py`、`technical.py`、`aggregate.py`，扩展CLI命令 `workbench gen-article`。`app.py` 新增POST `/wb-api/article-generate`，只校验并静默spawn CLI；GET `/wb-api/article-jobs/{id}` 读进度与结果。独立预览可加POST `/wb-api/snapshot`，同走CLI。任务锁、超时和幂等键防重复；退出码2提示人工介入并停。
- **数据流**：选中素材→复用 `retrieve.py` 补全文→tagger抽标的，允许纠正市场及周期→行情OHLCV→PNG与支撑阻力区间→聚合X大V、投行观点→LLM成稿。技术计算借鉴FV纯规则方式，记录算法、复权、时间窗；观点保留作者、时间、链接，区分原文/转述及分歧，缺证据明确留空。
- **生成**：CLI复用 `generator/common.py` 模型分发，沿用autopub配置链；模型取 `data/config.local.yaml` 的 `gen_model`，缺省 `ark:kimi-k3`。不误用translate/gemini配置。密钥仅服务端读取。风格初版采用结论开头、短段、明确数据、少量标签，再以查阅结果修订。
- **成稿与合规**：条件满足启用按钮，轮询展示阶段及成稿，支持文字、图片、标签编辑。任务及草稿只写 `data/workbench/` 自有JSON；严格JSON边界下PNG以base64保存，由GET解码返回。行情、LLM及落盘仅CLI执行；前三板块只读，模板不直接运行会写旧目录的流程。
- **复制与风险**：用户点击时尝试ClipboardItem提供文本、HTML、PNG；不能保证X同时接收图文，降级为复制正文、单独复制/下载图片。验收覆盖CJK/URL/emoji计数、缺行情及复制降级。依赖风险包括行情key/费用、Yahoo和TradingView可用性、X采集合规、投研版权及浏览器剪贴板支持。

**补充提示（codex 岗位核验说明）**：本答卷为规划文本，未涉及代码变更；清单中全部候选项目（尤其 FactReach 存在性、snscrape 当前可用性、twitter-text 的 CJK 加权口径）是按阶段约束「凭知识列出、未联网验证」的，已在阶段二交 grok 统一联网核实。一处主控采纳的修正：成稿 PNG 不走 base64 存 JSON，改落盘文件 + FileResponse（/wb-api/gen-assets/ 先例对齐视频模块）。
