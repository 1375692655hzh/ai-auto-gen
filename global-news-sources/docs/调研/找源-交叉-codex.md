# 找源调研·交叉轮（codex 侧）

- 调研日期：2026-08-30（周日）北京时间，以各站点返回时间戳为准（本机 `date` 与外部站点一致：Sun Aug 30 2026）
- 调研方式：curl（标准 Chrome UA 与无 UA 双通道）+ WebSearch 交叉验证，全程免登录、无 cookie
- 与前轮《找源-日报类/新闻类/分析类.md》的关系：本轮为独立交叉轮，**不重复提名**任何已有源、已知待接源（ii.co.uk/PANews/见闻快讯流/格隆汇/界面快报/CNA/Euronews/The Block）与前轮落选源
- 排除清单核对：富途/财联社/见闻早餐/gangtise/AA英文晨报/BloombergHT/CNBC Daily Open/共同社/韩联社/东财研报中心/新浪意见领袖/Livemint/金十/新浪7×24/东财快讯/早知道/财经日历/行情/财联社公告 —— 本轮均未触碰

---

## 一、日报角度（成篇晨报/市场综述）

### 1.1 推荐表

| 市场 | 源名 | 入口 | 发现通道 | 更新规律（实测） | 反爬 | 优先级 |
|------|------|------|---------|----------------|------|--------|
| 欧洲（欧陆/巴黎视角） | **Boursorama「Marchés」欧股开收盘综述流** | 列表 `https://www.boursorama.com/bourse/actualites/marches/`；文章 `/bourse/actualites/{slug}-{hash}` | 列表页 SSR 直出 ~38 条文章卡（`<a href="/bourse/actualites/...">`） | 工作日一日多档：8/28 实测三档——欧股开盘 09:35 CEST、欧股收盘 18:30 CEST、华尔街周前瞻 22:23 CEST（=北京 15:35 / 次日 00:30 / 次日 04:23）；**周末停更**（周日抓取最新=8/28 周五） | low（无 UA 裸 curl 200） | **P1** |
| 澳新（新西兰） | **interest.co.nz「What happened {Day}」每日收评 + Weekend briefing** | RSS `https://www.interest.co.nz/rss`；文章 `/economy/{id}/{slug}` | RSS 20 条/次；Google 检索到系列连续期号（Thursday/Friday 版 ID 137709→140001 跨数月） | What happened 每工作日一篇（NZ 下午 5 点档 = 北京 13:00）；Weekend briefing 周六早；全站 RSS 20 条覆盖 8/28-8/30 三天（周五 9 条/周六 9 条/周日 2 条）→ **周末照常有产出** | low（无 UA 200） | **P1** |

### 1.2 详情

#### A. Boursorama（boursorama.com，法国）

法国头部券商平台的内容+行情站，`/bourse/actualites/marches/` 是欧股市场综述流，内容由 Zonebourse（MarketScreener 旗下）供给——**MarketScreener 主站 403 落选，但 Boursorama 免登录转载可用**，正好补欧陆股市空白（ii.co.uk 是英国视角，本源是 CAC 40/欧陆视角）。

**实测证据**
```
GET https://www.boursorama.com/bourse/actualites/marches/            → 200 | 138,550 B（SSR 文章卡）
GET .../bourses-europeennes-francfort-finit-en-hausse-londres-et-paris-en-recul-51e1c...  → 200 | 124,792 B
无 UA 裸 curl 同列表页                                                  → 200 | 1,119,311 B（未压缩全量）
```

**栏目形态（slug 实录，8/26-8/28 约 38 条）**
- 开盘综述：`l-europe-ouvre-dans-le-vert-rebond-du-cac-40-...`（8/28 09:35:35 +0200）
- 收盘综述：`l-europe-termine-dans-le-vert-assimilant-le-discours-de-warsh-...`（8/28 18:30:54 +0200）
- 英股前瞻/综述：`le-ftse-100-britannique-recule-...`（8/27 12:21:43 +0200）
- 华尔街前瞻：`la-semaine-a-venir-a-wall-street-le-rapport-sur-l-emploi-...`（8/28 22:23:08 +0200）

**解析点**
- 列表卡：`<p class="c-list-news__title"><a href="/bourse/actualites/{slug}-{md5hash}" title="...">`（注意列表行内 `<span class="c-list-news__date">jeu.</span>` 只有星期缩写，无精确时刻）
- 文章页 JSON-LD：`"datePublished":"2026-08-27T17:46:35+0200"`（精确到秒，CEST，北京 +6 夏令时）
- robots.txt 无 `/bourse/actualites/` 禁令（禁的是 /ajax/、/streaming/ 等）

**作息统计（实测）**
- 8/28 一个交易日内三档（09:35 开盘 / 18:30 收盘 / 22:23 美股前瞻），叠加英股/油价/个股综述，日均约 8-12 篇综述
- 周日抓取时列表最新条目为 8/28（周五）→ 周末确认停更（欧股周末休市，合理）
- 当日版可抓时点：开盘综述北京 ~15:35 后；收盘综述北京次日 ~00:30（配夜班/次日早班）

**质量评语**
- 标准成篇市场综述（开盘/收盘各几百字，指数+个股+宏观驱动），非标题流
- 语言为**法语**（LLM 处理无压力，但需在下游标注语种）；来源标注 Zonebourse
- 列表无秒级时间是唯一小缺口——进文章页取 datePublished 补齐（列表 38 条 → 按需抽详情）

#### B. interest.co.nz（新西兰）

NZ 独立财经站，唯一免登录可抓的澳新市场日报型源。核心栏目 **"What happened {Day}: A review of things you need to know before you sign off"**——每工作日一篇收评：NZ 零售利率/银行动态 + 华尔街 S&P 收盘 + 亚洲市场（东京/新加坡/台湾）开盘表现，是标准的"隔夜回顾+当日要点"成篇结构。

**实测证据**
```
GET https://www.interest.co.nz/rss                            → 200 | 12,934 B（20 条）
GET https://www.interest.co.nz/economy/139720/review-things-you-need-know-you-sign-friday-...
                                                              → 200 | 25,612 B
无 UA 裸 curl RSS                                             → 200 | 12,934 B
```

**RSS 条目样本**
```xml
<title>What happened Friday</title>
<link>https://www.interest.co.nz/economy/139720/review-things-you-need-know-you-sign-friday-retail-rate-echoes-mid-winter-housing</link>
<pubDate>28th Aug 26, 5:00pm</pubDate>   <!-- 非标准格式，无时区标注（NZST=UTC+12，北京+4） -->
```

**解析点**
- RSS `title`/`link`/`pubDate`；pubDate 是 PHP 风格 `jS M y, g:ia`，需自定义解析并挂 NZST 时区
- 文章页 `published-at">7th Aug 26`（日粒度文本）+ `author-name` 字段
- 发现层：RSS 按标题正则 `What happened (Monday|Tuesday|...)` / `Weekend briefing` 过滤即可

**作息统计（实测）**
- RSS 20 条分布：8/28(五) 9 条、8/29(六) 9 条、8/30(日) 2 条（截至 19:55）→ 全站 ~10 条/天，**周末照常**
- What happened 系列：Google 检索到 Thursday 版 10 期连续期号（137709→140001），周五版同系列 → 每工作日一篇
- 周末由 Weekend briefing（周六早 6:30 NZST = 北京 02:30）+ 当日文章供给

**质量评语**
- 澳新+RBNZ 视角全球独一份（RSS 内样本："Bank economists aligned on what the RBNZ will do with the OCR on Wednesday"）；另大量美国宏观评论（Rogoff/联储沟通批评），国际内容占比高
- 时间戳格式非标准是唯一接入成本；反爬 low
- NZ 下班档发布（北京 13:00），适配午后班

### 1.3 日报角度落选清单

| 源 | 实测结果 | 落选原因 |
|----|---------|---------|
| CNN Business Nightcap | WebSearch 确认 2026-05-28 最终期《good night》 | **栏目已停刊** |
| Sherwood News (sherwood.news) | 200 / 369KB，/markets/ 为文章流 | 无固定每日晨报栏目、无 RSS；美国市场与已有 CNBC Daily Open 重复 |
| InfoMoney 每日综述 | /mercados/ 页面 SSR 200/76KB | 未发现固定每日市场 wrap 栏目（内容为机构观点转述+个股新闻）→ 转入分析角度提名 |
| goldman.com/insights | 404 / 2.2KB | 入口失效，未找到新稳定入口 |
| morningstar.com/articles | 404 / 469B | 入口失效（站点改版） |

---

## 二、新闻角度（滚动快讯流，单条精确时间戳，批量 ≥30 条/次）

### 2.1 推荐表

| 市场 | 源名 | 入口 | 条目密度（实测） | 时间戳 | 反爬 | 优先级 |
|------|------|------|----------------|--------|------|--------|
| 台湾/全球（繁中） | **鉅亨网 cnyes 新闻 API** | `https://news.cnyes.com/api/v3/news/category/headline?startAt={unix秒}&endAt={unix秒}&limit=100` | 48h 窗口 total=195 → **约 98 条/天，周末滚动**（最新条目周日 19:10） | `publishAt` Unix 秒级 | low（无 UA 200） | **P1** |
| 全球外汇/央行 | **FXStreet RSS** | `https://www.fxstreet.com/rss/news` | 30 条/次覆盖 8/28 半天 → 40-60 条/工作日；**周末停更**（周日抓取最新=周五 23:41 GMT） | `pubDate` GMT 秒级 | low（无 UA 200） | **P1** |
| 巴西/拉美 | **InfoMoney RSS** | `https://www.infomoney.com.br/feed/` | 10 条/次；**周末滚动**（8/29-30 连续产出，最新周日 11:00 UTC） | `pubDate` UTC 秒级 | low | P2 |

### 2.2 详情

#### A. 鉅亨网 cnyes 新闻 API（台湾最大财经站，繁中）

**实测证据**
```
GET https://news.cnyes.com/api/v3/news/category/headline?startAt=1787904000&endAt=1788076800&limit=100
→ 200 | 103,361 B；items.total=195，返回 data 30 条（per_page=30），items.next_page_url 支持翻页
分类均可用：headline / wd_stock(国际股) / tw_stock / cn_stock / forex → 各 200
无 UA 裸 curl → 200 | 122,580 B
```

**条目结构（列表即含全文，无需二跳）**
```json
{"newsId": 6591811,
 "title": "諾獎得主克魯曼解讀華許首秀「偏鷹」！降息訊號全缺席：意外是個「正常Fed主席」",
 "summary": "諾貝爾經濟學獎得主克魯曼認為，Fed主席華許在傑克遜霍爾演說基調偏鷹…",
 "content": "&lt;p&gt;諾貝爾經濟學獎得主克魯曼（Paul Krugman）認為，…（全文HTML）",
 "keyword": ["聯準會","華許","傑克遜霍爾","克魯曼","美股"],
 "publishAt": 1788088206,           // Unix 秒 → 2026-08-30 19:10 北京
 "categoryName": "國際政經"}
```
详情 API `/api/v3/news/{id}` 实测 404——**不需要**，列表已含 content/summary/keyword。

**作息统计（实测）**
- headline 48h（8/29 六 00:00 ～ 8/30 日 20:00）total=195 条，**周六周日都在滚动**（最新周日 19:10 北京）
- 折算约 98 条/天；单次 30 条、`next_page_url` 翻页可批量 ≥30×N
- 时间粒度：publishAt 秒级，直接可标准化

**质量评语**
- 内容是台湾视角全球财经：Fed/美股/半导体/地缘+台股，标题常带机构与人物（美銀、克魯曼），中文处理零成本（繁→简下游已有能力或 LLM 直处理）
- robots.txt `User-agent: * / Allow: /`（仅禁 ?desktop=true 与 .shtm 后缀）
- 注意 `startAt/endAt` 窗口不能超过 2 个月（422 报错实测），增量轮询按 24-48h 窗口取

#### B. FXStreet RSS（全球外汇/央行快讯）

前轮日报角度曾以"快讯/分析流非成篇"落选 FXStreet——本轮从**新闻角度**以 RSS 实测重新提名，结论互补不矛盾。

**实测证据**
```
GET https://www.fxstreet.com/rss/news    → 200 | 6,758 B（30 条）
无 UA 裸 curl 同 URL                      → 200 | 24,516 B
```

**条目样本（注意 description 自带机构+分析师实名）**
```xml
<title>South Korean Won: BoK tightening supports KRW against US Dollar – Commerzbank</title>
<link>https://www.fxstreet.com/news/south-korean-won-bok-tightening-...-2026...</link>
<description>Commerzbank’s Charlie Lay reports that the Bank of Korea (BoK) delivered a second consecutive 25 bp hike to 3...</description>
<pubDate>Fri, 28 Aug 2026 23:41:00 GMT</pubDate>
```

**作息统计（实测）**
- 30 条覆盖 8/28（周五）13:33–23:41 GMT → 半天 30 条，折算 40-60 条/工作日
- 周日抓取最新条目=周五 23:41 GMT → **周末停更**（外汇市场休市，合理；周一早恢复）
- feed 每次仅 30 条（约半天窗口），需高频轮询（建议 30-60 分钟一档）防漏

**质量评语**
- 外汇/央行线快讯流，pubDate 秒级 GMT；description 是现成摘要且**大量为机构观点转述**（Commerzbank/ING/Danske + 分析师实名）——单源双用（新闻流+分析素材）
- robots 禁 `/sitemap_news.xml`（勿用该通道）；RSS 不在禁止列表
- 反爬 low

#### C. InfoMoney RSS（巴西）

**实测证据**
```
GET https://www.infomoney.com.br/feed/    → 200 | 31,833 B（10 条）
```

**条目结构**：标准 RSS 2.0，`pubDate` 秒级 UTC（如 `Sun, 30 Aug 2026 11:00:00 +0000`）。

**作息统计（实测）**
- 10 条全部落在 8/29(六) 22:00 ～ 8/30(日) 11:00 UTC → **周末滚动**；feed 窗口浅（10 条约 1-2 天）
- 工作日密度预计更高（财经+商业混合发布）

**质量评语**
- 拉美空白唯一可用 RSS；但这是**全站混合 feed**（实测样本含酒店/遗产税/医疗类软闻），财经纯度低，需下游按关键词过滤
- 分类 feed `/mercados/feed/`、`/economia/feed/` 返回 200 但 646B 空壳（WordPress 分类 feed 已禁用）→ 只有主 feed 一个通道，密度上限 10 条/次 → 定 P2

### 2.3 新闻角度落选清单

| 源 | 实测结果 | 落选原因 |
|----|---------|---------|
| Moneycontrol RSS | `rss/marketreports.xml` 200 但 lastBuildDate=2024-06-03，条目停在 2024-04 | **RSS 通道废弃两年**；页面 200 但无条目级时间戳结构 |
| TradeArabia | 首页 200/542KB，SSR `/News/{id}/{slug}` 链接可抓；文章页 200/320KB | 文章页 `<time datetime="2018-03-09...">` 为模板残留坏值，显示文本仅日粒度（"Sat, 29 Aug 2026"）→ **不满足精确时间戳门槛** |
| BNN Bloomberg (加拿大) | 200/71KB SSR 有标题（The Week Ahead 等） | 首页与频道页均无条目级时间戳，内容混 CTV 通讯社流；时间盒内未找到合格快讯结构 |
| ForexLive | `forexlive.com/feed/news` 301 → **investinglive.com**/feed/news（品牌已合并改名），200/25.5KB/25 条 | 作者字段为站点名非实名；25 条覆盖 2 天密度低（~12 条/天）；周末停更。价值被 FXStreet RSS 覆盖 → 备选不推 |
| Bangkok Post business RSS | 200 但仅 10 条，部分 pubDate 缺时区 | 密度太低 |
| Argaam English | 连接失败（curl 000）×2 次 | 传输层不可达 |
| etnet (香港经济通) | `/www/tc/news/realtime.php` 404 | 入口失效，时间盒内未找到新入口 |
| finanzen.net (德国) | 403 / 366B | WAF 拦截 |
| DailyFX feeds | `dailyfx.com/feeds/market-news` 403 / 392B | 反爬拦截（IG 旗下） |

---

## 三、分析角度（机构/分析师观点，作者可辨识）

### 3.1 推荐表

| 市场 | 源名 | 入口 | 内容形态 | 更新规律（实测） | 反爬 | 优先级 |
|------|------|------|---------|----------------|------|--------|
| 欧洲（投行） | **ING Think 每日系列**（fx-daily / rates-spark / the-commodities-feed） | RSS `https://think.ing.com/rss/`（10 条）；列表 `https://think.ing.com/latest/`（SSR 20 篇） | ING 经济学家署名每日晨评（外汇/利率/大宗三线）+ 央行前瞻 + 专题 | 一周 20 篇：fx-daily 4 篇、rates-spark 4 篇（均工作日型）；**周末停更**（8/29-30 无新文） | low（无 UA 200） | **P1** |
| 美国（智库） | **PIIE「Realtime Economics」博客** | 列表 `https://www.piie.com/blogs/realtime-economics`；文章 `/blogs/realtime-economics/2026/{slug}` | 彼得森研究所经济学家署名博客（贸易/联储/新兴市场） | 首屏 10 篇抽样 8/12-8/26 → **约每周 1-2 篇**（低频高质量） | low | P2 |
| 拉美（机构观点转述） | **InfoMoney /mercados/ 机构观点流** | 页面 `https://www.infomoney.com.br/mercados/`（SSR 38 篇）；发现+时间靠主 feed | "BBA 维持 JBS 偏好 / BBI：Raízen 债券便宜 40%空间 / Morgan Stone 更防御"——巴西投行观点转述，机构名在标题 | 主 feed 周末滚动；页面列表无时间需进文章页 | low | P2 |
| 全球外汇（双属性补充） | FXStreet RSS（同新闻角度 B） | 同上 | description 含机构+分析师实名（"Commerzbank's Charlie Lay…"） | 40-60 条/工作日，周末停 | low | P2（已在新闻角度计分，此处仅备注双用价值） |

### 3.2 详情

#### A. ING Think（think.ing.com）—— 欧洲投行观点首推

ING（荷兰国际集团）研究门户，经济学家全员实名，恰好命中项目空白方向：**债券/外汇专门源 + 央行观察 + 大宗商品日报**。

**实测证据**
```
GET https://think.ing.com/rss/                                            → 200 | 2,959 B（10 条）
GET https://think.ing.com/latest/                                         → 200 | 20,425 B（SSR 20 篇文章卡）
GET https://think.ing.com/articles/fx-daily-dollar-caught-between-many-fronts/ → 200 | 18,339 B
无 UA 裸 curl RSS                                                          → 200 | 8,627 B
```

**三大每日系列（8/24-8/28 一周 /latest/ 全 20 篇逐一实抓）**
| 系列 | 本周篇数 | 发布日 | 作者（meta author 实录） |
|------|---------|--------|------------------------|
| FX Daily | 4 | 8/24、8/25、8/27、8/28 | Chris Turner（ING 全球市场主管）、Francesco Pesole、Frantisek Taborsky |
| Rates Spark | 4 | 8/24、8/25、8/26、8/27 | Padhraic Garvey, CFA、Michiel Tukker、Benjamin Schroeder |
| The Commodities Feed | 2 | 8/25、8/28 | Warren Patterson、Ewa Manthey |
| 专题/央行前瞻 | 10 | 全周 | Carsten Brzeski（ING 首席欧元区经济学家）、Charlotte de Montpellier 等 |

**解析点**
- 文章页 SSR meta：`<meta name="date_published" content="2026-08-25">` + `<meta name="author" content="Francesco Pesole, Chris Turner">`（作者=实名列表，JSON-LD `@type Person` 同步存在）
- RSS 条目：title/link 有效，**无 pubDate**；guid 带 UTC 时刻尾巴 `.../#When:14:46:00Z`（可用作发布时刻参考，日期以文章页为准）
- 发现通道双保险：RSS 10 条（约 2 天量）+ /latest/ SSR 20 篇（一周量）

**作息统计（实测）**
- 三个日更系列均为工作日型；8/29(六)、8/30(日) 抓取无新文 → **周末停更**
- 发布节奏：fx-daily 等为法兰克福/伦敦早盘（欧洲 8-11 点 CEST = 北京 14-17 点档，与 ii.co.uk 的 Market snapshot 同档，配午后班）
- robots.txt 仅禁 /sign-up 与一批爬虫 UA 黑名单（常规 UA 不在列）

**质量评语**
- 作者辨识度满分（机构=ING + 经济学家实名+头衔公开）；每日三线（汇/利率/商品）+ 央行周前瞻，正好补齐"债券外汇专门源+大宗商品日报+央行观察"三个提示方向
- 短板：RSS 无 pubDate（两跳取时间）、单篇正文在 SSR 内完整可抓（18KB 页面直出）

#### B. PIIE Realtime Economics（piie.com）

彼得森国际经济研究所博客，作者为一线经济学家（实测样本：Karen Dynan——哈佛教授/前美国财政部助理部长；Arvind Subramanian——前印度政府首席经济顾问；Monica de Bolle；Alan Wm. Wolff/Warren Maruyama）。

**实测证据**
```
GET https://www.piie.com/blogs/realtime-economics                                  → 200 | 12,882 B（SSR 文章链接）
GET .../2026/china-squeeze-response-our-critics                                    → 200 | 14,209 B
```

**解析点**
- 文章页 JSON-LD：`"datePublished":"2026-08-26T17:41:13-04:00"`（秒级，美东，北京 +12）；`"author":{"@type":"Person","name":"Karen Dynan"}`
- 作者机构标注：`class="author-list__organization"> (PIIE)`
- 列表页 SSR 直出 `/blogs/realtime-economics/2026/{slug}` 链接（首屏 10 篇）；无 RSS（/rss 404）

**作息统计（实测）**
- 抽样三篇：8/26、8/12、8/12；首屏 10 篇全部落在 8 月 → 约每周 1-2 篇
- 低频属性决定它做"深度观点补充位"而非日常供给

**质量评语**
- 美国贸易政策/联储/新兴市场权威观点，免费免登录；与东财研报中心（卖方）形成买方/智库互补
- 频率低是主要限制；发现层靠列表页（无 RSS），接入简单

#### C. InfoMoney /mercados/（巴西机构观点转述流）

**实测证据**
```
GET https://www.infomoney.com.br/mercados/   → 200 | 76,376 B（SSR 38 篇文章卡）
GET .../mercados/bba-mantem-jbs-como-favorita-no-setor-de-proteinas-e-ve-melhora-no-ciclo-nos-eua/
                                             → 200 | 62,597 B
```

**条目标题样本（机构名即作者，标题实录）**
- 「**BBA** mantém JBS como favorita no setor de proteínas e vê melhora no ciclo nos EUA」（Itaú BBA）
- 「**BBI**: títulos da Raízen parecem baratos após reestruturação e podem subir mais de 40%」（Bradesco BBI）
- 「Eleições: **Morgan Stanley** adota postura mais defensiva para ações brasileiras」
- 「Varejo enfrenta tri difícil, mas C&A se destaca, diz **Morgan Stanley**」

**解析点**
- 文章页 JSON-LD：`"datePublished":"2026-08-26T19:01:31+00:00"`（秒级 UTC）；作者字段为记者实名（样本 `"name":"Erick Souza"`）+ 机构名在标题/正文
- 列表页无条目时间戳（38 链接需进详情页取时间）；发现+时间实用通道是主 feed（10 条/次，见新闻角度 C）

**作息统计（实测）**
- 8/26 的 BBA 文章 + 主 feed 8/29-30 连续产出 → 周末照常有内容供给（转述类周末也不停产）
- 工作日机构观点转述密度高（38 篇/页×多页）

**质量评语**
- 拉美机构观点唯一免登录入口：机构名+方向判断（"维持偏好/看涨 40%/更防御"）齐全，作者可辨识（机构名标题直出）
- 葡语；列表无时间戳+feed 窗口浅是两个接入缺口——建议 feed 发现 + 详情页补时间的两跳模式

### 3.3 分析角度落选清单

| 源 | 实测结果 | 落选原因 |
|----|---------|---------|
| FedGuy (fedguy.substack.com) | feed 200 但 **0 条目**（仅 channel 壳，copyright 已变更"Tom Nicholson"）；fedguy.org 自定义域连接失败 000 | 疑似停更/转让/迁移，无稳定内容供给 |
| Bruegel (bruegel.org/analysis) | 200/19KB SSR 正常，条目 datetime 最新 **2026-07-09** | 欧洲智库但 analysis 流频率约月度级，过低 |
| Zacks | 主站 200/38.5KB，但 `/stock/rss` 返回 HTML 壳（非 XML） | RSS 端点失效；个股研报向与中文研报已有东财重复，时间盒内放弃 |
| Kobeissi Letter | （沿用前轮 404 结论） | 与前轮一致 |
| Goldman/Morgan Stanley 公开 insights | goldman.com/insights 404 | 入口失效，未继续 |
| 慧博/发现报告/雪球/智通研究等 | （沿用前轮落选结论，本轮未重测） | 前轮已验证登录墙/WAF |

---

## 四、跨角度汇总与接入提示

**本轮净新增推荐（均不与已有/已知待接重复）**
1. **ING Think**（分析 P1）——欧洲投行经济学家日更三线（汇/利率/商品）+央行前瞻，实名署名，反爬 low。填"债券/外汇专门源+大宗商品日报+央行观察"三个空白方向。
2. **鉅亨 cnyes API**（新闻 P1）——台湾视角全球快讯 JSON API，98 条/天、周末滚动、单条含全文，免登录免 header。
3. **Boursorama Marchés**（日报 P1）——欧陆股市开收盘成篇综述流，秒级 datePublished，欧股空白（与 ii.co.uk 英国视角互补）。
4. **interest.co.nz**（日报 P1）——澳新唯一免费日报型源（What happened 系列），周末有 Weekend briefing 补位。
5. **FXStreet RSS**（新闻 P1 / 分析双用）——外汇央行线快讯+机构观点摘要，秒级 pubDate。
6. **PIIE**（分析 P2）、**InfoMoney**（新闻 P2 + 分析 P2）——智库低频补充与拉美双位。

**排班适配（北京时间）**
- 午后班：ING（14-17 点档）、interest What happened（13:00 后）、Boursorama 开盘综述（15:35 后）
- 夜班/次日早班：Boursorama 收盘综述（次日 00:30）、FXStreet 尾条（至 GMT 23:41=北京 07:41）
- 早班：cnyes 随时（7×24 滚动）、InfoMoney feed 随时
- 周末供给：cnyes / InfoMoney / interest 照常；ING / FXStreet / Boursorama 周末停更（周一早恢复）

**语言分布**：中文繁（cnyes）、英（interest/FXStreet/ING/PIIE）、法（Boursorama）、葡（InfoMoney）——法/葡两源需在下游标注语种供 LLM 翻译处理。

**与前轮结论的交叉点**
- FXStreet：前轮以"非成篇日报"在日报角度落选；本轮以 RSS 实测在**新闻角度**提名（时间戳/批量/密度均达标），两轮结论不冲突
- MarketScreener 403 落选的绕行验证：Boursorama 免登录转载 Zonebourse（MarketScreener 系）内容，欧股综述可得
- 前轮 Google News RSS 合规落选结论继续有效，本轮未用任何聚合器源

> 接入提醒（对照《源录入规范》）：Boursorama 列表页无时刻（需详情页取 datePublished）；ING RSS 无 pubDate（guid #When 时刻 + 文章页日期双保险）；interest RSS pubDate 非标准格式需自定义解析；cnyes API 时间窗口 ≤2 个月限制——以上均已在详情节写明解析方案。
