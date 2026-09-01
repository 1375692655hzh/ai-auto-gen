# X 账号录入规范（推特股票池接入手册）

> 2026-08-31 制定。`源录入规范.md` 的姊妹篇——那边管"机构源"，这边管"X/Twitter 账号源"。
> 数据通路: FxTwitter 免登录（RSS `fxtwitter.com/<handle>/feed.xml` 主源 + `api.fxtwitter.com/2/profile/<handle>/statuses` v2 补全），额度实测零限流（2026-08-31 压测 30 连发全 200），RSS 有 2 分钟边缘缓存。
> **参照实现**: `E:\ai-skill\turkey\turkey-x-influencer-report-skill`（已跑通的完整技能：FxTwitter v2 主源 + xAI x_search 兜底 + 逐帖中文翻译 + LLM 精选日报；其 accounts.yaml 即本规范池文件的格式基型，土耳其池 30+ 账号可整体迁入）。
> 用户提供账号池 → agent 验证身份并预分类 → 用户确认 → 写入池文件。**素材好坏不由收录环节判断**（2026-08-31 裁决沿袭），用不用由工作流运行时选取。

## 一、账号登记卡（录入前必填）

```markdown
## 账号登记卡: <显示名>
- handle:                 # @xxx，抓取键。仅接受 1-15 位 [A-Za-z0-9_]，去 @ 前缀、大小写不敏感
- 数字用户 ID:            # 身份锚点（FxTwitter v2 author.id）。防改名误关注、防 handle 被他人注册
- 显示名:                 # 接口当前拼写，仅展示用（可改可重名，不作标识）
- 市场覆盖:               # 多选标签，一律用分类体系中文全称: A股/港股/美股/日本/韩国/台湾/土耳其
                         #   + 外汇/大宗(资产类别) + 全球(全球宏观不限定单一市场)
                         #   X 财经号多为全球视角，故比机构源多一个'全球'值且允许多选
- 账号定位 role:          # 八选一（见下方定位表），决定进 flash 流还是观点 digest
- 语言:                   # en / zh / ja / ko / tr（synth 多语言支持，输出始终中文）
- 粉丝量级:               # 接口读数，备查（不设门槛，只记录）
- 活跃作息:               # 活跃时段（美股盘/亚盘/全天）× 频率量级（日更几条），依据录入时近 20 条样本
- 采集开关:               # with_replies(是否收回复, 默认否) / media(是否带媒体链接, 默认是)
- 备注:                   # 已知身份背景 / 立场倾向 / 与在册源的覆盖重叠提示
```

**快速通道**：用户随手丢 `@handle`、主页链接或任意帖子链接均可；三问必答改为**市场覆盖 / 账号定位 / 语言**，其余由 agent 调 `api.fxtwitter.com/2/profile/<handle>/statuses` 首页（含完整 author 块：数字 ID/显示名/粉丝数/bio）+ 近 20 条推文自动补全，用户只做确认。

## 二、账号定位 → 源库映射（决策表）

| role | 含义 | 典型例 | 内容形态 | 去向 |
|---|---|---|---|---|
| `media` | 财经媒体官号/突发账号 | CNBC、WSJ breaks 类 | 快讯流 | `twitter_kol_flash` → rank 精排 |
| `data_bot` | 数据/异动服务号 | unusual_whales 类 | 快讯流 | `twitter_kol_flash` |
| `analyst` | 分析师/经济学家（实名机构） | 卖方首席、独立宏观 | 深度观点 | `twitter_kol_views` |
| `trader` | 交易员/基金经理 | 仓位分享、盘面解读 | 深度观点 | `twitter_kol_views` |
| `kol` | 财经博主/观点流（匿名为多） | 推特股票池主力人群 | 深度观点 | `twitter_kol_views` |
| `company` | 上市公司官号 | IR、产品官宣 | 快讯流 | `twitter_kol_flash` |
| `insider` | 公司高管/内部人士 | CEO 个人号 | 深度观点 | `twitter_kol_views` |
| `breaks` | 爆料/内部消息号 | 老记者、线人 | 快讯流 | `twitter_kol_flash` |

- **risk 分级随定位走**：`media`/`company`/`analyst` 默认 low；`trader`/`insider` 默认 medium；`kol`/`breaks`/`data_bot` 默认 medium（匿名或立场强），账号卡可手工覆盖。风险标只影响展示与选用判断，**不构成收录门槛**（观点情绪流一律入库，2026-08-31 裁决）。
- 与机构源的重叠提示：`media` 类账号若与在册源同稿率高（如 CNBC 官号 vs cnbc_morning），登记卡备注里注明，选用时由用户取舍。

## 三、池文件格式

池独立成文件（不塞 config.yaml 主文件），路径默认 `global-news-sources/config/twitter_pool.yaml`，源 conf 可覆盖。**格式为 ai-skill accounts.yaml 的超集**——直接复制 ai-skill 侧池子过来即兼容（缺的字段按默认值补）：

```yaml
# twitter_pool.yaml —— X 账号池（登记卡的结构化形态）
# ai-skill 兼容字段: handle/name/homepage/priority/tier/rank/enabled/notes
# 本规范新增字段:  uid/markets/role/lang/risk/replies/daily_cap
defaults:                      # 池级默认（fetcher 侧已验证的参数, 来自 turkey 技能实跑值）
  per_account_limit: 50        # 每账号单轮上限
  account_delay_seconds: 1     # 账号间隔
  window: yesterday_start_to_now
  min_priority: low            # 运行时可调, 只抓 high 时提门槛

filters:                       # 关键词过滤（多语言, 沿 turkey 池现成的中/英/土词表, 按市场换词）
  include_keywords: [market, stocks, inflation, Fed, 投资, 股市, 利率, ...]
  exclude_keywords: [giveaway, birthday, 抽奖, 表情包]

accounts:
  # ═══ ★ 核心大V（tier: core, 排名 rank 注明依据: 质量×影响力×实用性×稳定性）═══
  - handle: altinhisseler      # ai-skill 侧带 @ 前缀, 录入时规范化去掉
    uid: "..."                 # 身份锚点（迁移旧池时 agent 批量补验）
    name: "ALTIN HİSSELER"
    homepage: "https://x.com/altinhisseler"
    markets: [tr]
    role: kol
    lang: tr
    tier: core                 # core 每日必抓 / 扩展池按运行时选取
    rank: 1
    priority: high             # high / medium / low
    risk: medium
    replies: false
    note: "BIST影响榜前列，财报拆解细致，常给目标价和逻辑"
  # ═══ 官方/机构 ═══ 数据/媒体 ═══ 技术/综合 ═══ ...（分节注释风格沿 turkey 池）
```

**两个源共享一个池**，fetcher 按各账号 role 映射的形态分流：

| 源 id | kind | 消费面 | 收录范围 |
|---|---|---|---|
| `twitter_kol_flash` | flash | morning-paper rank 精排 | role ∈ media/data_bot/company/breaks |
| `twitter_kol_views` | peer_article | peer_article 条目流 | role ∈ analyst/trader/kol/insider |

工作流运行时按三层粒度选取：`--set twitter_kol.markets=us`（市场过滤）、`tiers=core`（核心池）、`min_priority=high`（提门槛）——三层参数在 turkey 技能 fetch 脚本里均有实装先例。

## 四、录入七步流程

1. **收料**：用户提供账号池（handle 列表 / 帖子链接列表 / 混合均可）。帖子链接先经 `/2/status/<id>` 解析作者（候选 handle 与作者不一致时列出候选让用户选，绝不猜）。
2. **批量验证**：逐个调 v2 statuses 首页 → 记 uid/显示名/粉丝/bio；404 = 账号注销或封号，列入失败清单交用户。
3. **预分类**：agent 依据 bio + 近 20 条推文填登记卡草稿（市场/定位/语言/作息）。
4. **用户确认**：批量场景输出汇总表（handle/uid/预分类/风险级），用户一次确认或圈改。
5. **写池**：追加进 `twitter_pool.yaml`；handle 大小写不敏感去重，**uid 重复一律拒绝**（同一个人换了 handle 也要先合并再录入）。
6. **首抓回溯**：新账号默认只回溯最近 24h（对齐 x-daily-watch 约定，不导历史全量）。
7. **文档登记**：本文件末尾账号总表追加一行；health 由池级源自动覆盖（FxTwitter 故障 = 两源同标 dead，符合实际故障面）。

## 五、身份核验与状态规则（沿袭 x-daily-watch 踩坑）

- **uid 是唯一身份键**：同 uid 返回新 handle → 自动更新 handle（改名）；同 handle 返回不同 uid → **停下问用户**（原账号改名后被他人注册的风险）。
- **增量边界**：每账号 `last_success`(UTC) + `seen_ids`（推文数字 ID 去重，滚动上限）；抓取保留少量时间重叠抗缓存乱序，靠 ID 去重兜底。
- **正文完整性**：RSS 标题 141 字截断绝不当正文；`since` 参数只是 204 快速判断，本地必须按时间戳再过滤；线程/回复/Article 靠 v2 补全（`with_replies=true` 仅对开了 replies 开关的账号）。
- **异常纪律**（沿源规范三级约定）：账号 7 天没发帖 = 没数据返空；FxTwitter 403/429/超时 = 故障抛异常记健康；**单账号 404 但池整体正常 = 该账号疑似注销，报告用户但不炸整池**。

## 六、防坑清单（X 特有）

- **显示名会骗人**：bio 顶着"某某首席"的不一定是本人，`media`/`analyst` 定位尽量找黄 V/蓝标佐证并记入备注；拿不准就归 `kol`（medium 风险）。
- **超高频号会淹没 digest**：日更 50+ 条的号（马斯克型）默认全收，但账号卡可加 `daily_cap: N`（数量管理非质量门槛，用户在收录时定）。
- **转推≠原创**：默认只收原创+引述，纯转推不进 digest（除非账号卡显式开 `retweets: true`）。
- **FxTwitter 是单一供应商**：RSS 与 v2 只是接口级冗余；服务整体不可用时的**降级路径为 xAI x_search**（`from:handle since:YYYY-MM-DD`，grok 模型，turkey 技能已实跑验证，需 `XAI_API_KEY`）——失败账号逐个回落，无 key 自动跳过只记失败清单，不进自动链主路径。

## 七、账号总表（录入后追加）

| handle | uid | 市场 | role | 语言 | risk | 录入日 | 备注 |
|---|---|---|---|---|---|---|---|
||altinhisseler|1204859131590516738|土耳其|kol|tr|medium|2026-09-01|核心rank1，bilanço深度分析||
||TuncayTursucu|864765082512838657|土耳其|analyst|tr|low|2026-09-01|核心rank2，SPK持牌||
||fintables|4797162376|土耳其|data_bot|tr|medium|2026-09-01|核心rank3，BIST数据平台||
||baymucize|1959969258|土耳其|trader|tr|medium|2026-09-01|核心rank4，已改名"Borsa Takipçisi"||
||Viop_Analiz|（待补验）|土耳其|trader|tr|medium|2026-09-01|核心rank5，近期全转推无原创，首条原创后补uid||
||Borsayolundaa|2647570873|土耳其|kol|tr|medium|2026-09-01|核心rank6||
||KadirCalimbay|2383795543|土耳其|kol|tr|medium|2026-09-01|核心rank7||
||SerkannnKayaaaa|1737274573408591872|土耳其|analyst|tr|medium|2026-09-01|核心rank8，前大行分析师||
||borsaistanbul|1070609989|土耳其|media|tr|low|2026-09-01|交易所官方||
||memetsimsek|183665035|土耳其|insider|tr|low|2026-09-01|财政部长||
||InvestTurkey|1388812572|土耳其|media|tr|low|2026-09-01|官方投资办公室||
||YFinansman|555978794|土耳其|media|tr|low|2026-09-01|最老牌经纪商||
||ibrahimmturhan2|752888409824296960|土耳其|analyst|tr|low|2026-09-01|前BIST主席/央行副主席||
||AS_Akat|1285775534|土耳其|analyst|tr|low|2026-09-01|资深经济学家||
||guskuay|371894476|土耳其|analyst|tr|low|2026-09-01|投资策略师||
||elerianm|332617373|全球|analyst|en|low|2026-09-01|全球宏观参考||
||BORSAIZINDE|741553965444239360|土耳其|kol|tr|medium|2026-09-01|选股思路||
||PiyasaTturkiye|1521020097292378112|土耳其|media|tr|medium|2026-09-01|日历热点汇总||
||muratcigerciogu|1173190282952814593|土耳其|trader|tr|medium|2026-09-01|图表分析||
||borsanalist_|1053991889681158146|土耳其|kol|tr|medium|2026-09-01|风格谨慎||
||taaardu|1451911567|土耳其|kol|tr|medium|2026-09-01|聚焦IPO/Halka Arz||
||barissoydan|25826831|土耳其|kol|tr|medium|2026-09-01|市场评论||
||ridvanozturgut|497128903|土耳其|kol|tr|medium|2026-09-01|活跃观点||
||BorsaAnalyst|325644038|土耳其|trader|tr|medium|2026-09-01|技术为主||
||tahtaci_borsa|1616750979235315712|土耳其|trader|tr|medium|2026-09-01|技术派||
||analitikyatirim|1669260360287678464|土耳其|media|tr|medium|2026-09-01|订单流研究机构||
||fonanalisti|1777661280569995264|土耳其|analyst|tr|low|2026-09-01|SPK持牌基金分析师||
||data_kapital|1310538387011534848|土耳其|media|tr|medium|2026-09-01|影响分析媒体||
||arifcoskun05|3255556330|土耳其|kol|tr|medium|2026-09-01|量化风格37万粉||
||Borsaemiliano|1319609719154233347|土耳其|kol|tr|medium|2026-09-01|影响榜活跃||
||RealUncleBrent|916883323418435584|台湾|kol|zh|medium|2026-09-01|布蘭特大叔；Threads侧A档5万粉, X号本人但基本不发||
||SemiAnalysis_|1745106082790318080|全球|media|en|low|2026-09-01|半导体权威研究机构15.9万粉; handle带下划线||

> 首批土耳其池 30 账号 + 台湾分区 2 账号（2026-09-01）+ 美股分区 22 账号（用户 xlsx/对标清单录入，uid 全验）。合计 54 账号；core 层 21 个。
| unusual_whales | 1200616796295847936 | 美股 | data_bot | en | medium | 2026-09-01 | 核心·期权资金流异动527万粉 |
| StockMKTNewz | 1250830691824283648 | 美股 | media | en | medium | 2026-09-01 | 核心·极高频ticker快讯112万粉 |
| KobeissiLetter | 3316376038 | 美股,全球 | analyst | en | medium | 2026-09-01 | 核心·宏观数据→强判断258万粉 |
| litcapital | 932630991298007041 | 美股 | kol | en | medium | 2026-09-01 | 金融meme163万粉 |
| burrytracker | 1539636858170122242 | 美股 | data_bot | en | medium | 2026-09-01 | Burry持仓tracker56万粉 |
| GRDecter | 1281457267582177280 | 美股 | kol | en | medium | 2026-09-01 | CFA真人解读41万粉 |
| charliebilello | 1413027896 | 美股,全球 | analyst | en | low | 2026-09-01 | 核心P1·数据图表86万粉实名 |
| MacroAlf | 1344759366671589376 | 全球 | analyst | en | medium | 2026-09-01 | P3·宏观因果链 |
| tier10k | 2361601055 | 美股 | media | en | medium | 2026-09-01 | P2·SEC文件财报快讯104万粉 |
| 10kdiver | 1248071584713076737 | 美股 | analyst | en | medium | 2026-09-01 | 核心P1·财报拆解因果链29万粉 |
| DeItaone | 2704294333 | 美股,全球 | media | en | medium | 2026-09-01 | P3·Walter Bloomberg快讯191万粉; handle大写I |
| citrini | 1365809270034477069 | 美股 | analyst | en | medium | 2026-09-01 | P2·主题研究二阶受益 |
| KawzInvests | 1447102056481837058 | 美股 | kol | en | medium | 2026-09-01 | 核心P1·NVDA单公司跟踪12万粉 |
| burak_finance | 371876593 | 美股 | analyst | en | medium | 2026-09-01 | P3·科技产业图表 |
| PeterLBrandt | 247857712 | 全球 | trader | en | medium | 2026-09-01 | 核心P1·价格结构130万粉 |
| NorthstarCharts | 1097211439159365632 | 全球 | trader | en | medium | 2026-09-01 | 核心P1·固定图表框架17万粉 |
| BitcoinMagazine | 361289499 | 全球 | media | en | medium | 2026-09-01 | 核心P1·加密事件雷达446万粉 |
| BrianFeroldi | 61558281 | 美股 | analyst | en | low | 2026-09-01 | 核心P1·投教清单67万粉实名 |
| morganhousel | 284278132 | 美股 | kol | en | low | 2026-09-01 | 核心P1·投资心理70万粉实名 |
| mingchikuo | 267509471 | 全球,台湾 | analyst | en | low | 2026-09-01 | 核心·郭明錤供应链一手25万粉 |
| MikeFritzell | 2471879203 | 全球 | analyst | en | medium | 2026-09-01 | P2·亚洲信息差研究 |
| jyershixiong | 1644184701316534273 | 全球 | kol | zh | medium | 2026-09-01 | P3·跨市场观点 |
