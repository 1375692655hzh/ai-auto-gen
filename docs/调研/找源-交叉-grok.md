# 找源交叉调研（grok 独立轮）：日报 / 新闻 / 分析

- 调研日期：2026-08-30（周日）实测；样本窗口 8/24～8/30
- 调研方式：Grok Build CLI 联网提名（--max-turns 15 防跑偏）→ 全部候选由主流程 curl（Chrome UA、免登录、无 cookie）逐个复验；解析点用 python 解析确认。本轮为交叉轮：上一轮已接/待接/落选清单（ii.co.uk、PANews、格隆汇、界面、CNA、Euronews、The Block、华尔街见闻快讯、Reuters/Axios/CoinDesk/雪球/Investing/MarketWatch/Barchart/StockTitan/Benzinga/The Edge/Google News RSS 等）全部规避，未重复提名
- 空白市场命中：港股（etnet）、欧洲（Newsquawk/ING）、海湾中东（Vault Wealth/AGBI）、拉美（Rio Times）、大宗商品（MINING.COM/OilPrice）、债券（Bond Vigilantes）、外汇快讯（ForexLive）、央行观察（Liberty Street/BIS）

---

## 1. 日报角度（成篇晨报/市场综述）

### 推荐表

| 市场 | 源名 | 入口 | 更新规律（实测） | 反爬 | 优先级 |
|------|------|------|----------------|------|--------|
| 港股 | etnet 經濟通「開市Ｇｏ」 | 列表 `https://www.etnet.com.hk/www/tc/news/special_news_list.php?category=%E9%96%8B%E5%B8%82%EF%BC%A7%EF%BD%8F`；文章 `news-article.php?section=special&category=開市Ｇｏ&newsid=2026MMDD282` | 工作日每天一篇 08:30-08:38 HKT（8/24-28 五天全勤 08:32/08:38/08:30/08:34/08:36），周末零发布 | low | **P1** |
| 欧洲+美股 | Newsquawk「EU/US Market Open」 | 列表 `https://www.newsquawk.com/daily`；文章 `/daily/5738-us-market-open-…` | 每交易日两篇：EU Market Open 北京 ~14:38（06:38Z 实测）、US Market Open 北京 ~18:12（10:12Z 实测）；8/24-28 全勤，周末停 | low | **P1** |
| 海湾/中东 | Vault Wealth「Daily Pour」 | RSS `https://vaultwealth.com/daily-market-briefings/rss.xml`；文章 `/resources/daily-pour/{D-month}/` | **7 天连发**每日一篇（8/15-30 无一天缺失；周中 Double Espresso、周末 Cappuccino 周结版，8/29-30 同题为周末重发）；feed 时间戳仅日期粒度，具体时刻需文章页后验 | low | **P1** |
| 拉美 | Rio Times「Latin American Pulse」 | 列表 `https://www.riotimesonline.com/latam-pulse/`；文章 `/latin-american-pulse-for-{weekday}-{month}-{day}-{year}/` | 周一~周六每日一篇（8/21,22,24,25,26,27,28,29 连续，周日无）；最新一篇 8/28 07:04 UTC = 北京 15:04 | low | P2 |
| 海湾 | AGBI（Arabian Gulf Business Insight） | 首页 `https://www.agbi.com/` | 首页日期集中 8/24-28（工作日更新）；文章级未深验，接入前需补验 | low | P2 |

### 每源详情

#### 1.1 etnet 經濟通「開市Ｇｏ」（香港，P1）

港股空白（已有富途之外第一个可抓晨报）。标题即三要点式：`美無意續簽對伊備忘錄，內地展汽車品質提升行動，中芯放榜`。

**实测证据**
```
GET special_news_list.php?category=開市Ｇｏ   → 200 | 64,178 B（SSR）
GET news-article.php?…&newsid=20260828282   → 200 | 71,964 B（SSR，手机版 m.etnet.com.hk 同 200/68,887B）
```

**解析点**
- 列表行：`<a href="/www/tc/news/news-article.php?section=special&category=開市Ｇｏ&newsid=20260828282"><h2 class="h4">美無意續簽對伊備忘錄…</h2></a> … <p class="time">28/08/2026 08:36</p>`
- 文章页 `<meta name="description" content="【要聞盤點】1、美股三大指數周四…">`——**摘要即全文要点**（编号 1、2、3、4…隔夜条目），正文 SSR 同步直出（页面内「備忘錄」出现 7 次，正文位 ~153KB 处：`備忘錄條款。特朗普重申，伊朗正面臨嚴峻經濟困境…3、美國據報正與委內瑞拉臨時政府進行談判…`）
- 日期时间：列表页 `DD/MM/YYYY HH:MM`（HKT=北京，无需换算）

**作息**：工作日 08:30-08:38 HKT 一篇（五天样本无缺席）；8/29(六)、8/30(日) 零发布。北京时间 08:30 直配早班流程。
**质量**：成篇「要聞盤點」编号式隔夜回顾（美股+A股+港股+地缘），数字密度合格。无登录墙，标准 UA 直抓。

#### 1.2 Newsquawk「EU/US Market Open」（欧洲+美股，P1）

欧洲空白的英文开盘综述，专业盘前通讯形态（APAC 隔夜回顾 + 欧洲/美国开盘展望）。

**实测证据**
```
GET https://www.newsquawk.com/daily                    → 200 | 24,532 B
GET /daily/5737-eu-market-open-europe-primed-…         → 200 | 25,425 B（正文 111 段纯文本）
GET /daily/5738-us-market-open-us-equity-futures-…     → 200 | 25,839 B
```

**解析点**
- 列表：`href="/daily/5738-us-market-open-us-equity-futures-mixed-as-nvidia"` + 日期 `28 Aug 2026`（编号连续 5724→5738，可判更）
- 文章：`"datePublished":"2026-08-28T06:38:41.046Z"`（EU）/ `"2026-08-28T10:12:28.329Z"`（US）
- 正文免费全文（无 paywall 标记），段落式新闻 bullet：`US President Trump's administration has repeatedly told mediators it has no interest in going back to the terms of the MoU…`

**作息**：交易日 EU+US 各一篇（8/24-28 每天两篇全勤），周末停。北京 14:38 / 18:12 左右发布。
**质量**：标准成篇开盘综述（期货/国债/汇率/隔夜新闻bullet），标题带市场方向。

#### 1.3 Vault Wealth「Daily Pour」（海湾/中东，P1）

中东非土耳其空白。UAE 财富管理机构的每日市场简报（美股隔夜+宏观+海湾视角）。

**实测证据**
```
GET https://vaultwealth.com/daily-market-briefings/rss.xml → 200 | 31,875 B（155 items）
GET https://vaultwealth.com/resources/daily-pour/30-august/ → 200 | 65,667 B
```

**解析点**
- RSS `<item>`：`<title>Nvidia lifts, Warsh caps.</title>` + `<pubDate>Sun, 30 Aug 2026 00:00:00 GMT</pubDate>` + `<link>…/daily-pour/30-august/</link>`
- **RSS description 直出 ~800 字摘要**：`Vault Wealth Cappuccino weekly wrap for Sunday, 30 August 2026. The market rebounded… a midweek Nvidia blowout… oil eased below $90… new Fed Chair Kevin Warsh capped it: September hike bets spiked to 57%…`——素材层单靠 feed 即可用
- 文章页正文 JS 渲染（无 datePublished），但 feed 摘要已够用

**作息**：连续 155 天每天一篇（8/15-8/30 抽样无缺失，周六/周日有独立标题或周末版重发）。feed 时间戳 00:00 GMT 日期粒度，发布具体时刻未取得（UAE 早间，需接入后从社媒/页面前端后验）。
**质量**：成篇晨报（标题即当日主题句），周末版为周结——正好补早报周末班。

#### 1.4 Rio Times「Latin American Pulse」（拉美，P2）

拉美空白唯一免登录英文日更源。

**实测证据**
```
GET https://www.riotimesonline.com/latam-pulse/                                        → 200 | 37,941 B
GET /latin-american-pulse-for-friday-august-28-2026/                                   → 200 | 59,274 B
   "datePublished":"2026-08-28T07:04:51+00:00"（北京 15:04）
```

**解析点**：列表链接 `latin-american-pulse-for-{weekday}-{month}-{dd}-{yyyy}/` 自带日期；文章页 datePublished ISO 精确。
**作息**：周一~周六日更（8/21→8/29 连续 8 篇，周日空档）。
**质量减分**：形态是「图形化报告卡」（页面自述 optimized for landscape viewing），文字部分为导语+条目简讯（`Lula shrugs off Brazil's debt, Mexico exports hit a record, and Chile faces a diplomatic row`），非长文。P2 定位：拉美数据点补充源。

#### 1.5 AGBI（海湾商业，P2，首页级验证）

`https://www.agbi.com/` 200/49,749B，免登录。首页日期分布 8/24×18、8/27×13、8/26×12、8/28×24（工作日更新，周末停）。文章卡为栏目链接（Aviation/AI/Giga-projects 等），文章级解析点与作者未深验——接入前需补一次文章页验证。

### 日报落选清单

| 源 | 实测 | 落选原因 |
|----|------|---------|
| NAB Morning Call（澳） | `business.nab.com.au/nabs-morning-call` 404；`/tags/nabs-morning-call` 404；站内搜索 404；首页 13KB JS 壳 | 入口消失/改版，无稳定可抓页 |
| DW Business（欧） | `/en/business/s-1431` 200/46.8KB | 专题特稿流非晨报形态；页面无 `<time>` 标记，抓到的日期混杂（最旧 2026-08-01） |
| Kitco News（大宗） | `/news/` 200/47.2KB | 纯 JS 列表，0 个日期/作者标记可解析；公共 RSS 已关停（Grok 调研结论，与实测 JS 壳互证） |
| Business Times SG（东南亚） | `/` 200/38KB | React Router 壳 + 付费墙（正文订阅） |
| The Straits Times（东南亚） | `/business` 200/33KB | premium/subscribe 标记 6 处，付费墙 |
| RTHK 财经 RSS（港） | `rthk.hk/…e_expressnews_efinance.xml` 两次 curl 000；`news.rthk.hk/rthk/en/rss.htm` 页 200 但页内无 finance feed 直链 | TLS/网络层连不通（本环境），不可稳定依赖 |
| FNArena（澳） | `/` 200/316KB | 会员制混杂，时间盒内未完成文章级验证（未证伪，留档待查） |

---

## 2. 新闻角度（滚动快讯流，精确时间戳，≥30条/次）

### 推荐表

| 市场 | 源名 | 入口 | 条目密度 | 时间戳质量 | 反爬 | 优先级 |
|------|------|------|---------|-----------|------|--------|
| 外汇/全球宏观 | ForexLive | RSS `https://www.forexlive.com/feed/`（`/feed/news/` 同） | 25 条/次（**略低于30门槛⚠**）；交易时段分钟级 | `pubDate` 秒级 GMT（`Fri, 28 Aug 2026 20:41:11 GMT`） | low | **P1** |
| 大宗商品 | MINING.COM | RSS `https://www.mining.com/feed/` | **36 条/次 ✓**；工作日每小时级 | `pubDate` 秒级 +0000（`Fri, 28 Aug 2026 22:49:46 +0000`） | low | **P1** |
| 能源 | OilPrice.com | RSS `https://oilprice.com/rss/main` | 15 条/次（不足30⚠） | 小时粒度（`Sat, 29 Aug 2026 18:00:00 -0500`），**周末有更新** | low（RSS 层） | P2 |

### 每源详情

#### 2.1 ForexLive（P1）

外汇+全球宏观快讯流，英文，免登录。覆盖金十/见闻之外的英文盘面流。

**实测证据**
```
GET https://www.forexlive.com/            → 200 | 111,836 B
GET https://www.forexlive.com/feed/       → 200 | 22,911 B（25 items）
GET https://www.forexlive.com/feed/news/  → 200 | 25,525 B（25 items）
```

**解析点**：标准 RSS 2.0，`<pubDate>` 秒级 GMT。
**作息**：25 条样本全落在周五一天（07:57→20:41 GMT），交易时段分钟级；周末停（最新一条为周五，FX 闭市）——早班 08:30 北京抓到的恰是隔夜欧洲+美洲时段条目。
**注**：Grok 调研称已品牌迁移 investingLive.com（实测该域独立 200）；forexlive.com 域名与 feed 当前均正常，双域任一可用，接入时做域名存活监测即可。
**减分**：单次 25 条，低于 30 门槛 5 条——接 `latest-news` 页面列表或两次拉取可补足，接入前验证。

#### 2.2 MINING.COM（P1，大宗商品空白）

金属/矿业/黄金快讯，WordPress 标准 feed。

**实测证据**
```
GET https://www.mining.com/feed/  → 200 | 64,216 B（36 items）
   Fri, 28 Aug 2026 22:49:46 +0000 … Mon, 24 Aug 2026 14:53 +0000
```

**解析点**：RSS `<pubDate>` 秒级；`<category>` 带 topic（gold/copper/coal 等，可按金属过滤）。
**作息**：工作日高频（36 条覆盖 Mon-Fr 一周）；周末基本停（feed 无 8/29-30 条目）。
**质量**：短讯带精确时间戳，铜铁矿金锂全谱——正好补大宗商品空白（现有源无商品英文流）。

#### 2.3 OilPrice.com（P2，能源）

```
GET https://oilprice.com/rss/main  → 200 | 15,882 B（15 items）
   Sat, 29 Aug 2026 18:00:00 -0500 / 16:00 / 14:00 / 12:00 / 11:00 …
```

- 时间戳小时粒度（整点），条目 15/次——**两项均低于门槛**，定位为能源补充源
- 亮点：**周末照常更新**（周六 4 条样本），可补快讯源的周末空档
- 网页层业界常见 Cloudflare，建议只走 RSS

### 新闻落选清单

| 源 | 实测 | 落选原因 |
|----|------|---------|
| RTTNews | `/` 200/50.2KB | 首页纯 JS：0 个时间戳标记、仅 32 个链接，无解析点 |
| Gulf News business（迪拜） | `/business` 200/2.6MB | 巨型 JS 页，无 datePublished/时间标记可解析 |
| Zawya（中东） | `/en/` 200/30KB（展开 242KB） | 只有导航/账户链接，新闻流为 JS 壳，无绝对文章链接无 ISO 时间 |
| Argaam EN（沙特） | `/en` 200/197KB；`/en/news` 404 | 页面无任何日期标记（日期为 JS/阿语本地化渲染），新闻频道路径失效 |
| Al Jazeera economy | `/economy/` 200/88.4KB | 文章 URL 自带日期（`/economy/2026/8/28/slug`）但列表无 HH:MM——文章流非快讯流，不符 flash 形态 |
| RNZ business（新西兰） | `/news/business` 200/21KB | 列表无日期时间标记、文章页 datetime 提取不到；量小（business 类低频） |
| Anue 钜亨 cnyes | `news.cnyes.com/news/cat/all` 200/28.7KB | SSR 时间戳陈旧（2026-08-19），`api.cnyes.com/media/api/v1/news/list` 与 `/media/news/list` 均 404——需前端逆向，成本 medium |
| Boursorama（法国） | `/actualites-economiques/` 404 | 路径失效（未再探） |
| BBC/Guardian business RSS | 未提名 | 综合媒体非财经专注；英国已由 ii.co.uk 覆盖，增量低 |

---

## 3. 分析角度（机构观点/署名分析师，作者可辨识）

### 推荐表

| 市场 | 源名 | 入口 | 作者可辨识 | 更新规律（实测） | 反爬 | 优先级 |
|------|------|------|-----------|----------------|------|--------|
| 欧洲/全球 | ING Think | RSS `https://think.ing.com/rss/` | 文章页 byline 角色署名（`Head of Research, Americas` 等，ING 经济学家团队） | 交易日滚动多发（同日 13:00Z/14:40Z/14:46Z 三篇），北京 21-23 点密集 | low | **P1** |
| 央行观察/美国 | Liberty Street Economics（纽约联储） | RSS `https://libertystreeteconomics.newyorkfed.org/feed/` | `dc:creator` 直接署名（Nina Boyarchenko / Asani Sarkar 等联储经济学家） | ~1-2 篇/周（100 条样本，最新 8/19） | low | **P1** |
| 债券/欧洲 | Bond Vigilantes（M&G 固收团队） | RSS `https://bondvigilantes.com/feed/` | `dc:creator` 署名（Richard Ryan / Stefan Isaacs / Nick Smallwood） | ~1 篇/周（7/7→8/24，10 条跨 11 周） | low | **P1** |
| 策略/全球 | Klement on Investing（Joachim Klement，Liberum） | RSS `https://klementoninvesting.substack.com/feed` | 全部署名 Joachim Klement | 工作日隔天级（7/21→8/28，20 条） | low | P2 |
| 宏观/大V | Noahpinion（Noah Smith）+ Chartbook（Adam Tooze） | `noahpinion.substack.com/feed`；`adamtooze.substack.com/feed` | 署名 Noah Smith / Adam Tooze | 高频且**周末活跃**（两者 8/30 周日均有更新） | low | P2 |

### 每源详情

#### 3.1 ING Think（P1，欧洲机构观点空白）

荷兰 ING 的研究站，Carsten Brzeski 等经济学家观点主阵地，免登录。

**实测证据**
```
GET https://think.ing.com/                                    → 200 | 17,597 B
GET https://think.ing.com/rss/                                → 200 | 2,959 B（10 items）
GET https://think.ing.com/snaps/warshs-hawkish-words-…       → 200 | 16,449 B
```

**解析点**
- RSS item：`<title>Warsh guides forward without forward guidance</title>` + `<link>…/snaps/warshs-hawkish-words-pivots-the-curve-flatter/</link>` + guid 尾缀 `#When:14:46:00Z`（**精确发布时刻藏在 guid**）+ `<description>` 直出观点全文：
  `NORTH AMERICA: We got far more here from Chair Warsh then we were getting from his two FOMC meetings to date… front end rates are higher and back end rates are lower as a reaction.`
- 作者：RSS 无 creator 字段，文章页 byline 有角色署名（`Head of Research, Americas`）
- 注意 `/feed/` 是 404，正确地址是 `/rss/`

**作息**：交易日多篇滚动（RBNZ 预览、波兰预算、Warsh 点评同日三篇），北京 21-23 点为主。
**质量**：观点密度极高（每条 snap = 一个明确机构判断+市场反应），欧洲/央行/Rates/FX/商品全覆盖。

#### 3.2 Liberty Street Economics（P1，央行观察空白）

纽约联储官方博客，联储经济学家署名研究短文——「央行观察+机构观点」双重命中，权威性顶级。

**实测证据**
```
GET https://libertystreeteconomics.newyorkfed.org/feed/  → 200 | 480,568 B（100 items）
```

**解析点**：RSS `<dc:creator>` 直接给作者名（`Nina Boyarchenko, Lars C. Larsen, and Paul Whelan`、`Will Aarons and Asani Sarkar`）；`<category>` 给主题（Banks×18 / Household Finance×14 / Labor Market×13 / Financial Markets×10）。
**作息**：100 条样本跨度约一年，~1-2 篇/周，工作日 ET 白天；最新 8/19。
**质量**：数据驱动的机构研究短文，作者+职务全部可辨识（页面附作者栏）。

#### 3.3 Bond Vigilantes（P1，债券空白）

M&G Investments 固收团队博客——现有源池里没有英文债券专门源。

**实测证据**
```
GET https://bondvigilantes.com/feed/  → 200 | 35,787 B（10 items）
   dc:creator: Richard Ryan / Stefan Isaacs / Nick Smallwood
   category: Inflation / ECB / Emerging markets / Energy
```

**作息**：约每周一篇（7/7→8/24 连续 10 篇/11 周），工作日伦敦时间早间（07-08Z）。
**质量**：署名固收基金经理/分析师观点文，欧洲债市+全球信用视角，正好补债券/欧洲双空白。

#### 3.4 Klement on Investing（P2）

Liberum 策略师 Joachim Klement 的 Substack（免费层完整），量化+行为金融视角。

```
GET https://klementoninvesting.substack.com/feed  → 200 | 32,868 B（20 items，全部 dc:creator=Joachim Klement）
   Tue, 21 Jul 2026 06:xx → Fri, 28 Aug 2026 06:xx GMT（北京 14 点前后发布）
```

工作日隔天一篇级别，Substack `/feed` 免登录直取。

#### 3.5 Noahpinion / Chartbook（P2，周末活跃的大V观点）

```
noahpinion.substack.com/feed   → 200 | 251,332 B（20 items，Noah Smith 18 + Tim Fist 2）
   7/24 → 8/30（最新一篇周日 00:xx GMT，周末照发）
adamtooze.substack.com/feed    → 200 | 57,159 B（20 items，全部 Adam Tooze）
   8/16 → 8/30（周日有更新）
```

**注意（同站陷阱）**：`chartbook.substack.com/feed` 是 200 但内容为 2019-2022 年的旧同名 newsletter（3 items，Matthew Zeitlin）——**Chartbook 正确入口是 adamtooze 子域**。
两源宏观叙事/地缘经济长文，作者声量大；Noahpinion 更高频，Chartbook 更深度。作为 peer_article 的周末补位（多数机构源周末停更，这两个周日实测仍在发）。

### 分析角度补充（详情级，未入推荐表）

- A Wealth of Common Sense（Ben Carlson）：`awealthofcommonsense.com/feed/` 200/25KB，10 items，8/18→8/28 约 2 篇/周——备选
- The Grumpy Economist（John H. Cochrane）：`grumpy-economist.com/feed` 200/86.9KB，20 items 但 6/2→8/24 仅 ~1-2 篇/月——频率偏低
- The Overshoot（Matthew C. Klein）：`theovershoot.co/feed` 200/66KB，20 items 跨 1/20→8/18 约**双周一篇**——频率偏低
- ECB Blog：`ecb.europa.eu/press/blog/html/index.en.html` 200/71.8KB，行长/经济学家署名，月更级——央行观察补充
- 央行观察官方 RSS（primary source，非观点文章）：BIS 央行行长演讲库 `bis.org/doclist/cbspeeches.rss` 200/8.8KB；Fed 全稿 `federalreserve.gov/feeds/press_all.xml` 200/1.6KB（20 items）——若做「央行观察」栏目可直接用

### 分析落选清单

| 源 | 实测 | 落选原因 |
|----|------|---------|
| CF40 中国首席经济学家论坛 | `www.cf40.org.cn` 200 但仅 1,125B | Vue SPA 壳，无 SSR 内容 |
| Hussman Funds | `/category/comment/feed/` 200/131.6KB | 最新一篇 2026-07-14（6 周前），近月已放缓至约月更，更新不稳 |
| IMF Blog | `/en/Blogs` 403（375B） | 反爬拒绝 |
| Wells Fargo Economics | curl 000（连接失败） | 网络层不通（可能 TLS/地域限制） |
| First Trust Economic Commentary | `/Commentary/Economic` 404 | 路径失效 |
| ARK Invest research / Allianz economic-research | 均 404 | 路径失效/改版 |
| RBA 官方 RSS | `rba.gov.au/rss/…` 403 | 官方站拦截 curl（或需浏览器指纹） |
| PIMCO / UBS CIO | 未深验 | 企业 WAF + 完整研报需客户登录（预期 medium-high，低性价比） |
| chartbook.substack.com | 200 但是 2019-22 旧同名 newsletter | 假地址，真身在 adamtooze 子域（已转推荐） |

---

## 4. 三角度 Top 汇总（供交叉对比）

| 角度 | P1 | P2 |
|------|----|----|
| 日报 | etnet 開市Ｇｏ（港/08:30 北京）、Newsquawk Market Open（欧+美/14:38+18:12 北京）、Vault Wealth Daily Pour（海湾/日更含周末） | Rio Times Pulse（拉美/周六也发）、AGBI（海湾/待补验） |
| 新闻 | ForexLive（外汇宏观/秒级/25条⚠）、MINING.COM（大宗/秒级/36条✓） | OilPrice（能源/小时粒度/15条/周末活跃） |
| 分析 | ING Think（欧/日更多篇）、Liberty Street（美联储署名/周更）、Bond Vigilantes（债券/周更） | Klement（策略/隔天）、Noahpinion+Chartbook（大V/周末活跃） |

排程含义（对照 作息-汇总.md 早班 08:30）：
- 直配早班：etnet 開市Ｇｏ（北京 08:30-08:38 发布，抓取宜 08:40 后）
- 午后班：Newsquawk EU（14:38）、Klement（~14:00）、Rio Times（15:04）
- 晚班/夜班：Newsquawk US（18:12）、ING Think（21-23 点密集）
- 周末班：Vault Wealth（7 天连发）、OilPrice（周六更新）、Noahpinion/Chartbook（周日实测在发）；其余机构源周末停

## 附：复现性说明

全部实测为 2026-08-30（周日）单日快照：curl 标准 Chrome UA、免登录、无 cookie；`--compressed`；超时 25s。RSS 作息统计基于 feed 内 pubDate 分布（各 feed 条数见正文）；HTML 作息基于列表页日期标记逐条抽取。反爬等级为「免登录 curl 直抓成功率」口径：low=直接可用；medium=需逆向（cnyes/格隆汇型）；high=WAF/JS 挑战（本轮落选源多属此类）。
