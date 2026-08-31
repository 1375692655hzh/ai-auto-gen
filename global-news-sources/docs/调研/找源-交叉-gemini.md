# 找源调研·交叉独立版（gemini 视角）

- **调研日期**：2026-08-30（周日），北京时间；实测时段当日 19:00–19:45
- **调研方式**：全部 curl 直连实测（标准 UA `Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/126.0.0.0 Safari/537.36`，无 cookie，跟随重定向），辅以 web 检索定位入口。所有状态码/体积/时间戳为真实抓取记录。
- **独立性声明**：按任务书独立选源判断，未参考本轮另一代理的结果；已有源/已知待接/已知落选全部严格排除。
- **角度定义**：日报=成篇晨报/综述；新闻=带精确时间戳的滚动快讯（批量 ≥30 条/次）；分析=作者可辨识（机构名/人名）的观点内容。
- **本轮实测环境注意**：`/tmp` 在并行 Bash 调用间不共享，且 Windows Python 不识别 Git Bash 的 `/tmp` 虚拟路径——复现时请在同一 shell 内完成"抓取+解析"，或用 `cat file | python -c` 走 stdin。

---

## 一、日报角度（成篇晨报/市场综述）

### 1.1 推荐表

| 市场 | 源名 | 发现通道 | 更新规律（实测） | 反爬 | 优先级 |
|------|------|---------|----------------|------|--------|
| 大宗商品（中文空白） | **SMM 上海有色网**「隔夜行情 / SMM日评 / SMM午评 / LME收盘」系列 | 栏目页 `https://news.smm.cn/l/21`（金属金融市场，SSR 直出文章卡）；首页 25 条 `/news/{id}` 链接；官方 sitemap | 三班倒系列：隔夜行情（晨间/周日晚）+ 午评（午后）+ 日评（收盘后）；同站快讯流工作日 160–233 条/天、周末约 10%（sitemap-live lastmod 统计）；**周日 18:57 实测有隔夜行情** | low（robots `Allow: /`） | **P1** |
| 外汇/宏观（英文空白） | **investingLive**（原 ForexLive）「What are the main events for today」每日版 + 区域 FX news wrap | `https://investinglive.com/sitemap.xml` → `latest.xml`（Google news sitemap，秒级时间戳）；RSS `https://www.forexlive.com/feed/news` 301 → `https://investinglive.com/feed/news`（25 条） | 每日前瞻版工作日 ~06:19–06:31 UTC（北京 14:19–14:31）；美盘 wrap ~20:41 UTC（北京次日 04:41）；**周末自有内容零**（周日 19:20 实测，今日版=周五发布） | low | P2 |

### 1.2 每源详情

#### 1.2.1 SMM 上海有色网 —— 大宗商品日报 P1 ★

**定位**：全球最大有色金属资讯商（LME/沪市金属现货+期货），「隔夜行情/SMM日评/SMM午评」是标准的金属市场成篇日报，填大宗商品空白（现有源零商品视角）。

**实测证据**
```
GET https://news.smm.cn/l/21                     → 200（栏目页 SSR，/news/{id} 文章卡列表）
GET https://news.smm.cn/news/104086512           → 200 | 31,100 B（【隔夜行情】全文 SSR）
GET https://news.smm.cn/robots.txt               → User-agent: * / Allow: /（仅禁 /search /api）
GET https://news.smm.cn/sitemap/sitemap-list.xml → 200（栏目页清单，/l/21 lastmod=2026-08-29 周六仍在更新）
GET https://news.smm.cn/sitemap/sitemap-live.xml → 200 | 4,809,511 B（live 快讯全量索引）
```

**系列家族**（/l/21 栏目页实测标题样本）
- `沃什放鹰 金银跳水 基本金属普跌 伦锡、沪镍跌幅居前 氧化铝涨超2%【隔夜行情】`
- `期锌自四年高位回落，因美联储主席沃什讲话后加息预期升温【8月28日LME收盘】`
- `金属涨跌互现 伦锌纽银涨逾1% 碳酸锂钯涨超4% 沪银涨超3%【SMM日评】`
- `缺乏明显驱动 沪镍低位徘徊【沪镍收盘评论】`

**解析点**
- 正文：`<p>` SSR 直出（实测隔夜行情文 17 段，数字密度极高：`隔夜外盘金属方面，LME基本金属普跌。伦铜跌0.15%，伦铝涨0.56%…伦锡跌1.86%`）
- 时间：可见层 `<span>来源：SMM</span><time>2026-08-30 18:57</time>`；`__NEXT_DATA__` 内 `"date":"2026-08-30"`、`"author":"李丹（资讯）"`（编辑署名）
- 发现：/l/21 分页（`/l/21/pid/100` 形态，sitemap-list 已列分页 URL）；按标题后缀【隔夜行情】【SMM日评】【SMM午评】【LME收盘】白名单过滤

**作息统计（实测）**
- sitemap-live.xml lastmod 按日统计（近 12 天）：工作日 161–233 条/天（8/28 周五 334 峰值），周六 8/22=21、8/29=17，周日 8/23=14、8/30=21 → **周末约 10% 但不断更**
- 隔夜行情实测样本：8/30（周日）18:57 发布（内容为沃什杰克逊霍尔讲话后的金属市场隔夜综述）；周一至周五的发布时刻未逐篇取样，接入后从 `<time>` 后验
- 周末行为：周日有隔夜行情（覆盖周五夜盘+周一开盘前瞻）；午评/日评随交易时段

**质量评语**：成篇、带具体涨跌幅与品种逻辑，中文；隔夜行情/日评结构与美国金属周报同级。缺点：标题流与日报混在同一栏目流，需按标题后缀过滤；部分深度报告（SMM专题）需登录，但三大日报系列免登录全文可抓。

#### 1.2.2 investingLive（原 ForexLive）—— 外汇/宏观英文日报 P2

**定位**：ForexLive 品牌迁移至 investinglive.com（`forexlive.com/feed/news` 301 实证），保留原班外汇快讯/晨报人马。与 403 落选的 investing.com **不同域不同站**，直连 200。

**实测证据**
```
GET https://www.forexlive.com/feed/news           → 301 → https://investinglive.com/feed/news（200 | 25,543 B，25 条）
GET https://investinglive.com/sitemap.xml         → 200（index：latest.xml + articles-sitemap-index.xml，lastmod 2026-08-30T12:00 实时）
GET https://investinglive.com/latest.xml          → 200 | Google news sitemap，19 URL，<news:publication_date>2026-08-28T20:41:11+00:00（秒级）
GET https://investinglive.com/news/what-are-the-main-events-for-today-30/ → 200 | 96,792 B（13 段全文）
GET https://investinglive.com/news/investinglive-americas-fx-news-wrap-28-aug/ → 200（13 段）
```

**两个日报栏目**
1. **What are the main events for today?**：每日一版（URL 尾号 28/29/30 为顺序版号，非日期——today-29 实发 8/27 周四、today-30 实发 8/28 周五 06:31 UTC）。结构=欧盘议程+美盘议程+关键预期值（`Initial Claims are expected at 2...`、`the ECB is widely expected to hike interest rates by 25 bps in September`），标准"今日展望"晨报。
2. **investingLive Americas FX news wrap {date}**：美盘收盘综述（`It was a fairly straight-forward day in terms of 'what happened and why'... yields rose, USD climbed`），隔夜回顾型。

**解析点**：latest.xml 的 `news:publication_date`（秒级+00:00）；文章 `<p>` 直出；版号与日期解耦，**日期必须取自时间戳/sitemap 而非 URL**。robots 仅禁 /search-results、/signalr、/*.pdf$。

**作息统计（实测）**
- 工作日：前瞻版 06:19–06:31 UTC（北京 14:19–14:31，配午后班）；美盘 wrap 20:41 UTC（北京次日 04:41，配夜班→次日早班）
- **周末：自有内容零发布**（周日 19:20 实测今日版仍为周五版）。注意：首页上的 `2026-08-30T11:58` 时间戳是第三方 DataLab 聚合器（Bloomberg/Fortune 标题）的刷新时间，非自有内容，勿误判为周末更新
- RSS /feed/news 25 条/次，窗口止于周五

**质量评语**：前瞻+wrap 成对覆盖"今日展望+隔夜回顾"，外汇/利率视角英文成篇；与 FXStreet 同赛道（本报告新闻角度已荐 FXStreet），接入时二选一或错峰互补。缺点：无作者署名（byline 缺失，日报角度不强制）；RSS 每批 25 条 <30（作 flash 用不达标，故只进日报角度）。

### 1.3 落选清单（含实测证据）

| 源 | 实测 | 落选原因 |
|----|------|---------|
| CommSec（澳洲） | market-news.html 302→the-markets.html 200/17KB；文章 `/market-news/the-markets/2026/aug-26-*.html` 200 | "The Markets"栏目为**月度教育文章**（aug-26/jul-26/may-26 等 10 篇），非每日 wrap；每日内容只在播客/视频（CommSec Market Update）无文字稿 |
| Enterprise AM（埃及/中东） | enterprise.press 301→enterpriseam.com/egypt/ 200/53KB；sitemap.xml 为 WP Yoast 索引且**无 post-sitemap** | 公开 web 层近壳：首页最新时间戳停 8/27 周四、14 处 login/7 处 subscribe、文章列表客户端渲染；内容已订阅化，发现层断裂 |
| 期货日报 qhrb.com.cn | 首页 200/12.9KB | 老式 PHP 站，无晨报/日评固定栏目，电子报为版面图形态 |
| Moneyweb（南非） | 403/101KB | WAF 拦截 |
| Livewire Markets（澳） | 403/5.6KB | WAF 拦截 |
| nabtrade（澳） | /investment-insights 404 | 入口失效 |
| Moneycontrol RSS（印度） | /rss/latestnews.xml 200/15KB | 主 RSS 条目少且印度位已由 Livemint 填补 |

---

## 二、新闻角度（滚动快讯，≥30 条/次，精确时间戳）

### 2.1 推荐表

| 市场 | 源名 | 入口 | 批量 | 时间戳 | 周末 | 反爬 | 优先级 |
|------|------|------|------|--------|------|------|--------|
| 东南亚/越南（空白） | **VnExpress English business RSS** | `https://e.vnexpress.net/rss/business.rss` | **60 条/次** | `pubDate` 秒级 +0700 | 全周滚动（周六 8 条/周日 10 条实测在流） | low | **P1** |
| 外汇/全球宏观（空白） | **FXStreet news RSS** | `https://www.fxstreet.com/rss/news` | 恰 **30 条/次** | `pubDate` 秒级 GMT | **工作日源**：周六日零更新（周日实测） | low | **P1** |
| 加密（备选） | Cointelegraph RSS | `https://cointelegraph.com/rss` | 30 条/次 | `pubDate` 秒级 +0000 | 周末滚动（Sun 09:45、Sat 20:28 在流） | low | P3（与待接 The Block 同位互备） |

### 2.2 每源详情

#### 2.2.1 VnExpress business RSS —— 东南亚 P1 ★

**实测证据**
```
GET https://e.vnexpress.net/rss/business.rss → 200 | 54,954 B | 60 <item> | 61 <description>
```

**条目结构（实测样本）**
```xml
<item>
  <title>German CEO earns $108,000 a month running Vietnamese bank</title>
  <description><![CDATA[<a href="...5115171.html"><img ...></a></br>Techcombank chief executive Jens Lottner earned nearly VND17 billion (US$650,000) in the first half this year, a 33% increase...]]></description>
  <pubDate>Sun, 30 Aug 2026 14:34:26 +0700</pubDate>
  <link>https://e.vnexpress.net/news/business/companies/...-5115171.html</link>
</item>
```
- description 为 CDATA：链接+图片+一段完整导语摘要，LLM 可直接用
- pubDate RFC822 带越南时区，秒级

**7 天窗口统计（60 条 pubDate 按星期分布）**：Thu 15、Fri 10、Sat 8、Sun 10、Mon 9、Tue 4、Wed 5 → **周六日照常滚动**，约 8–15 条/天。

**质量评语**：越南头部媒体英文版，银行/公司/宏观占比高，正好填东南亚空白；标准 RSS 接入成本近零。注意 description 内嵌 HTML 需剥（CDATA 一层）。

#### 2.2.2 FXStreet news RSS —— 外汇/宏观 P1 ★

**实测证据**
```
GET https://www.fxstreet.com/rss/news      → 200 | 24,516 B | 恰 30 <item>
GET https://www.fxstreet.com/news          → 200（SSR 1.28MB，日期字段与 RSS 一致，交叉验证）
GET https://www.fxstreet.com/robots.txt    → 未禁 /rss（仅禁 /search /tickers /futures 等）
```

**条目结构**：标准 RSS 2.0，`<pubDate>Fri, 28 Aug 2026 23:41:00 GMT</pubDate>`（秒级）+ title/link/description。

**作息统计（实测）**
- 30 条全部落在 8/28 周五 09:33–23:41 GMT（分钟级连发，全天约 30–40 条）
- **周末：RSS 与 /news 页双双停在周五 23:41 GMT（= 北京周六 07:41）**，周日 19:15 复测无新条 → 工作日源
- 排程含义：北京周六/周日早班 08:30 抓到的是周五美盘收盘全量（末条 23:41 GMT），恰好完整覆盖隔夜美股/汇市——周末休更反而与早报节奏对齐

**质量评语**：外汇/央行/数据快讯流，英文，时间戳现成；与金十（中文）构成中英互备。同站另有 /rss/analysis（见分析角度），厂商复用。

#### 2.2.3 Cointelegraph RSS —— 加密备选 P3

```
GET https://cointelegraph.com/rss → 200 | 30 <item>
<pubDate>Sun, 30 Aug 2026 09:45:01 +0000</pubDate>（秒级，周末滚动）
```
- 前轮调研曾记"200/46KB 活跃"但按日报角度落选；本轮按 flash 角度复测：30 条/次达标、秒级时间戳、周末更新
- 加密 flash 位已有待接 The Block（19 条/次），本源与其同位互备，仅在一并接或 The Block 接入受阻时启用

### 2.3 落选清单（含实测证据）

| 源 | 实测 | 落选原因 |
|----|------|---------|
| Bangkok Post business.xml | 200/5.4KB，**10 条/次** | 密度不达标；且日期格式不一（部分条目无时区后缀） |
| Antara（印尼）en RSS | 200/7.3KB | 条目少（约 15 条），密度不达标 |
| InfoMoney（巴西） | /feed/ 200/130KB 但仅 **10 条/次** | 密度不达标；拉美位本轮无合格 flash（可后续按分类 feed 叠加再评） |
| AGBI（中东英文） | /feed/ 200/53KB 但仅 **10 条/次**，最新停在周五（ME 周末=周五六） | 密度不达标 |
| The Star（马来） | /rss/News/ 404、/rss/business/ 404 | RSS 已下线 |
| NZ Herald business | Arc outboundfeed 返回"Fusion Article"JS 壳 | feed 入口失效 |
| ABC AU business feed | 46482=3 条、46486=0；仅 Just In(51120)=25 条且为综合新闻 | business 专用 feed 已下线 |
| 证券时报快讯 | /article/list/kx.html 200/8KB，纯 JS 渲染，页内无 API 线索 | 发现层客户端渲染，时间盒内未逆向出 API |
| Zacks / MarketBeat / GuruFocus | 404 / 404 / 403 | 入口不可用 |

---

## 三、分析角度（作者可辨识的机构/分析师观点）

### 3.1 推荐表

| 市场 | 源名 | 入口 | 作者辨识 | 更新规律（实测） | 反爬 | 优先级 |
|------|------|------|---------|----------------|------|--------|
| 欧洲/全球宏观+汇率利率（英文空白） | **ING Think** | RSS `https://think.ing.com/rss`（200/8.6KB，10 条/次，articles/opinions/snaps 混流） | 文章页 JSON-LD `"author":{"@type":"Person","name":"Francesco Pesole"}`——ING 研究部经济学家实名 | feed 窗口 10 条全部为 8/28 周五（06:49–14:46 UTC）→ 单工作日可达约 10 条；**周六日零**（周日实测） | low（robots 仅禁 /sign-up） | **P1** |
| 外汇/贵金属（英文空白） | **FXStreet analysis** | RSS `https://www.fxstreet.com/rss/analysis`（200/24KB，30 条/次） | 文章页 JSON-LD `"name":"Pablo Piovano"` + 作者主页链接——驻场分析师实名 | 30 条覆盖约 6–7 天：工作日 4–10 条/天，周六偶发 2 条、周日 0 | low | P2 |

### 3.2 每源详情

#### 3.2.1 ING Think —— 欧洲机构观点 P1 ★

**定位**：ING 集团研究部对外内容站（think.ing.com），作者全部为 ING 首席经济学家/策略师（Carsten Brzeski 欧洲宏观、Francesco Pesole FX、Padhraic Garvey 利率等），恰好填"欧洲+央行+汇率利率"的英文机构观点空白（现有英文源仅 CNBC 日报）。

**实测证据**
```
GET https://think.ing.com/rss                                                   → 200 | 8,627 B | 10 <item>
  （6 条 /articles/、1 条 /opinions/、3 条 /snaps/）
GET https://think.ing.com/articles/rbnz-preview-a-25bp-hike-with-some-dovish-risks/ → 200 | 17,375 B（10 段全文 SSR）
GET https://think.ing.com/robots.txt                                            → 仅 Disallow: /sign-up
```

**条目/文章结构**
- RSS item：`<title><![CDATA[...]]>` + `<link>` + `<dc:date>2026-08-28T14:46:00+00:00</dc:date>`（分钟级 UTC）+ `<dc:subject><![CDATA[Rates, North America, United States]]></dc:subject>`（现成分类标签）
- snaps 为盘中短评（含观点句：`He was net hawkish. ... front end rates are higher and back end rates lower as a reaction`）；articles 为成篇研判（RBNZ 前瞻 10 段：`The Reserve Bank of New Zealand should hike rates by 25bp on 2 September, in line with expectations...`）
- 作者在文章页：`"author" content="Francesco Pesole">`、`"author": { "@type":"Person","name":"Francesco Pesole "`、`author/francesco-pesole`

**作息统计（实测）**
- feed 10 条全落 8/28 周五 06:49–14:46 UTC（北京 14:49–22:46）→ 单个工作日约 10 条产出，白天连续发布
- **周六/周日：零条目**（周日 19:30 实测，feed 最新仍为周五）→ 纯工作日源，配午后班/早班抓昨日+今晨
- 限制：RSS 仅存 10 条（≈1 个工作日窗口），需每个工作日定时抓，不适合回填；robots 声明的 sitemap（/sitemap/index.html）抓取无内容，历史节奏只能靠滚动窗口累计

**质量评语**：机构实名+观点密度+免费全文，欧洲宏观/央行观点的最强免登录英文入口；snaps 短评适合 flash 化、articles 适合观点素材。与东财研报（中文券商）互补成"中英双机构观点"。

#### 3.2.2 FXStreet analysis —— 外汇分析师观点 P2

**实测证据**
```
GET https://www.fxstreet.com/rss/analysis → 200 | 24,174 B | 30 <item>
GET https://www.fxstreet.com/analysis/cftc-report-cad-short-covering-leads-gold-buying-surges-202608290941 → 200 | 252,876 B
```

**解析点**
- RSS：标准 item，`<pubDate>` 秒级 GMT；文章 URL 尾部自带时间戳（`-202608290941` = 8/29 09:41 UTC）
- 文章页 JSON-LD：`author":{"@type":"Person","name":"Pablo Piovano","url":"https://ww...` + `worksfor` 机构字段——作者可辨识
- 30 条窗口按星期分布：Thu 7、Fri 10、Sat 2、Mon 3、Tue 4、Wed 3 → 工作日 4–10 条/天，周六偶发、周日零

**质量评语**：FX/贵金属/美股的技术面+基本面结合分析，作者为 FXStreet 驻场分析师实名（Pablo Piovano、Joseph Trevisani 等）；"机构"成色弱于投行研报，但节奏（日更多篇）远好于月更的买方/卖方公开研究。与新闻角度的 /rss/news 同站同解析层，边际接入成本低。

### 3.3 落选清单（含实测证据）

| 源 | 实测 | 落选原因 |
|----|------|---------|
| The Macro Compass（Substack） | `themacrocompass.substack.com/feed` 200/561KB，20 条，作者 `Alfonso Peccatiello (Alf)` 实名 | **免费层≈月更**（20 条跨 2024-11～2026-07：7/13、5/26、2/10…），频率不匹配日更管线 |
| Schroders Insights | /en/insights/ 200/37KB SSR 有日期（economics 栏目最新 8/24、此前 6/26、4/29） | 经济学栏目月更，且机构观点偏资配长文；节奏不匹配 |
| PIIE（彼得森） | piie.com 301→www.piie.com 200/17KB，/rss、/rss.xml、/publications/rss 全 404，页内无 alternate feed 声明 | 无 RSS/发现入口，时间盒内未深挖列表页 |
| CF40 中国金融四十人论坛 | cf40.org.cn 200/3.4KB | JS 壳，无 SSR 内容 |
| 智堡 wisburg.com | 200/225KB | 营销落地页壳（仅 #preview/#download 锚点），文章列表不可见，内容在 App/登录层 |
| Compound News（Weisenthal/Alloway） | 检索证实**不存在** | 二人仍在 Bloomberg「Odd Lots」（付费墙+Reuters 同级拦截预期）；本轮 web 检索多角度交叉确认 |
| Kobeissi Letter | kobeissiletter/thekobeissiletter 两 handle 均 404 | 与前轮调研结论一致，无有效 RSS 入口 |
| Zacks / MarketBeat / GuruFocus | 404 / 404 / 403 | 入口不可用 |

---

## 四、三角度汇总与排程含义（北京时刻）

| 角度 | 源 | 一句话价值 | 当日可抓时点 |
|------|----|-----------|-------------|
| 日报 | SMM（P1） | 大宗商品唯一中文成篇日报（隔夜/午评/日评三班倒，周末约 10% 供给） | 隔夜行情晨间+周日晚 18:57 实测；具体工作日时刻接入后验 |
| 日报 | investingLive（P2） | 外汇"今日前瞻+美盘 wrap"成对（英文） | 前瞻 14:19–14:31（午后班）；wrap 次日 04:41（早班） |
| 新闻 | VnExpress（P1） | 东南亚空白，60 条/次秒级时间戳，7×7 滚动 | 任意班次 |
| 新闻 | FXStreet news（P1） | 外汇/宏观英文快讯 30 条/次；**周末休更反而对齐早班**（周六晨=周五美盘全量） | 任意班次（工作日源） |
| 新闻 | Cointelegraph（P3） | 加密 flash 备选（30 条/次秒级，周末滚动），与待接 The Block 互备 | 任意班次 |
| 分析 | ING Think（P1） | 欧洲机构观点空白：ING 经济学家实名，工作日约 10 条/天 | 午后班/早班（昨日+今晨窗口） |
| 分析 | FXStreet analysis（P2） | 英文外汇分析师实名观点，日更多篇，与 news 流同站复用 | 任意班次 |

**空白市场覆盖**：大宗商品（SMM）、东南亚（VnExpress）、欧洲/汇率利率机构观点（ING Think）、英文外汇快讯（FXStreet/investingLive）、加密备选（Cointelegraph）。本轮未能填上的空白：中东（Enterprise 订阅化、AGBI 密度不足）、拉美（InfoMoney 10 条/次不达标）、澳新 flash（ABC/NZH feed 下线）——已在落选清单留证据，供后续轮次接力。

**复现要点**：所有入口免登录、无签名、无频控证据（本轮单次/低频抓取）；标准 UA 直连即可。SMM 勿碰 /api/*（robots 禁）；FXStreet robots 未禁 /rss；investingLive 版号 URL 与日期解耦，日期一律取 `news:publication_date`/`<pubDate>`。
