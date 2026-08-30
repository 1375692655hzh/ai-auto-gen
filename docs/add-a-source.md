# 加一个新信息源（来源库操作手册）

来源库（`sources/`）= 信息来源注册表 + 爬取方式 + 健康检查 + 缓存。

## 现有来源

早报源（2026-08-30 定版：**地理市场=美/A/港/日/韩/台/土耳其** + 资产类别源外汇/大宗（同日用户许可），14 源+4快讯，全部实测 ok）：
- **富途《港美早报》**：列表接口 seqMark 翻页 + 文章页 WAF 破盾，正文保留段落
- **财联社有声早报**：专栏 1151，每天 07:00，48h 内最新一篇全文
- **华尔街见闻早餐FM-Radio**：搜索接口定位 + 内容 API 补全文
- **元宝·Gangtise**：Playwright 持久化登录态问元宝拿当日投研日报（gangtise 搜狗链失败时自动兜底）；登录态过期时跑 `py -3.11 generator/yuanbao_fetch.py --login` 扫码
- **AA安纳多卢英文晨报**（土耳其/国际，2026-08-30）：search→world RSS→world 页三级发现链，RSC payload 抽正文，48h 窗口；约北京 13:00 发布
- **BloombergHT 土耳其市场**（2026-08-30）：SON DAKİKA 快讯 + Öne Çıkan 要闻 + 当日收盘综述拼篇；周末无收盘综述属正常
- **CNBC Daily Open 美股晨报**（2026-08-30）：归档页 SSR 发现 48h 最新版 → ArticleBody 正文；每工作日两版，APAC 版约北京 09:10 发布（早于 9 点跑工作流会取到前一日版并被当日过滤记 failed，属预期）；周末停更
- **共同社日本市场精选 / 韩联社韩国市场精选**（2026-08-30）：当日 RSS 条目 × 市场/宏观关键词过滤拼篇；日本周末休市常无市场条目（None 属预期），韩国周末照常
- **东财研报中心机构观点索引**（2026-08-30）：晨会纪要+宏观+策略当日列表拼篇，机构+研究员署名；交易日作息
- **新浪意见领袖**（2026-08-30）：首席经济学家/大V当日观点（工作日 9:00-16:00 发布，早班 08:30 必空，午后班可用）
- **etnet 經濟通開市Go**（2026-08-30 交叉轮）：港股晨报，工作日 08:30 HKT 直配早班
- **鉅亨网台股精选**（2026-08-30）：tw_stock 当日条目，周末照常滚动
- **SMM 上海有色网大宗商品日报**（2026-08-30 恢复，资产类别源）：栏目页取【隔夜行情】优先的系列文全文，铜铝镍锌/库存/升贴水；周末篇目少属正常
- 快讯池(flash)：新浪7×24/东财快讯/金十数据/**investingLive**（外汇/美股/宏观，英文，2026-08-30 接入顶 FXStreet 的班；FXStreet 已注册但默认禁用——本站出口 IP 被 Cloudflare 整站 403，网络环境变化后把 default_enabled 打开即可）
- **Newsquawk 欧美开盘综述**（2026-08-30 交叉轮）：交易日北京 14:38/18:12，午后/傍晚班
356
  注意：以上各源与元宝统一走 `peer_mornings` 聚合进工作流（`cli sources fetch peer_mornings` 手动可取），不需要在 config 里单开（避免与聚合重复抓取）。防坑：feeds.a.dj.com、MarketWatch mw_marketpulse、Investing.com news_285 等旧 RSS 已冻结（仍返回 200 但数据停更），网上老资料仍在引用，勿接入。

### 备用源（public-apis 名录收录 2026-08-30，主源失效时顶班）

在册模型（2026-08-30 用户定）：**能跑通的源就在册可用**，不用"禁用"藏起来；要排除某源是在跑工作流时选取——`--set peer_sources=鉅亨台股,SMM大宗商品`（早报源按显示名）/ `--set flash_sources=jin10_flash,investinglive_flash`（快讯源按 id），空=全部。
需 key 的源：把 key 写进 `autopub/secret.local.json` 对应字段（或同名大写环境变量），再把 `sources/builtin.py` 里该源的 `default_enabled` 改为 `True`——没 key 它跑不通，所以先不翻开，这不是"禁用"是"缺钥匙"。
按你的裁决，这些只为"替代"存在——限额紧也无妨，登记时我负责写清每个源给什么。

| 源 id | 给什么信息 | 市场/形态 | 作息与限额 | 启用条件 |
|---|---|---|---|---|
| `marketaux_news` | 美股市场新闻标题流，每条带关联 ticker 标注（实测返回真实 JSON） | 美股 / 快讯(flash) | 滚动更新；免费档约 100 次/天 | `marketaux_api_key` |
| `finnhub_news` | 美股 general 类市场新闻 headline 流 | 美股 / 快讯(flash) | 滚动更新；免费档 60 次/分（最宽松） | `finnhub_api_key` |
| `alphavantage_news` | 美股新闻 + 整体情绪标签（Bullish/Bearish 等） | 美股 / 快讯(flash) | 滚动更新；免费档仅 25 次/天，只够应急 | `alphavantage_api_key` |
| `sec_edgar` | SEC 最新 8-K 重大事件申报：公司名+表单类型+申报时刻（美股公告唯一官方源；可改 form_type 换 10-K 等） | 美股 / 公告(announcement) | 交易时段滚动；官方免费，限速 10 次/秒 | 无 key，已在册可用 |
| `frankfurter_fx` | ECB 参考汇率快照：USD 基准对 CNY/HKD/JPY/KRW/TRY/EUR（**不含 TWD**） | 外汇 / 数据行情(market) | 每交易日一更（约北京 23 点），周末无新值 | 无 key，已在册可用 |
| `goldprice_metals` | 黄金现货快照：XAU 折算每克 24K~10K 金价（31 币种）。注意名录描述含银/铜，**免费端点实际只有黄金** | 大宗 / 数据行情(market) | 实时滚动 | 无 key，已在册可用 |
| `fred_macro` | 美联储宏观最新值：CPI 指数/失业率/联邦基金利率/10Y 国债收益率 | 美国宏观 / 数据行情(market) | 各序列按月/周更新；key 免费即申即得 | `fred_api_key` |

名录弃选说明：Econdb（名录标"无 key"但 2026-08-30 实测 401 需 token，无法验证返回结构，不录入）；NewsAPI/GNews/NewsData/Mediastack 等通用聚合器（无市场定向、与主源重叠、稀释质量）；Alpha Vantage/Polygon/Twelve Data 等纯行情 API（价格数据已有 sina 行情接口承担）。

### 扩展源（simonlin1212 目录项目收录 + 前两轮调研遗漏补收 2026-08-30）

收录标准只有两条（用户裁决）：在七地理市场+外汇/大宗范围内、且能给内容。全部零鉴权、逐一直调实测通过、在册即可用。

| 源 id | 给什么信息 | 市场/形态 | 作息与限额 | 启用条件 |
|---|---|---|---|---|
| `cls_telegraph` | 财联社电报 7×24 实时快讯流（签名纯本地计算零 key，实测 50 条即返） | A股+宏观 / 快讯(flash) | 7×24 滚动 | 无 key，已在册可用 |
| `eastmoney_global` | 东财全球资讯快讯（海外宏观/美港股）；与财联社电报不同域名不同风控面，互为备胎 | 全球 / 快讯(flash) | 滚动更新 | 无 key，已在册可用 |
| `cninfo_latest` | 巨潮全市场最新公告：证券简称+公告标题+类型（A股官方信披，不带 stock 参数即全市场） | A股 / 公告(announcement) | 披露时段滚动；announcementTime 是日期级时间戳，按日期归集 | 无 key，已在册可用 |
| `nbs_pmi` | 统计局月度 PMI：制造业/非制造业/综合 + 大中小型企业分档 | 中国宏观 / 数据行情(market) | 每月最后一天发布当月值；首页只放两周，发现层自动翻 4 页兜底；措辞改版 fail-fast 报警 | 无 key，已在册可用 |
| `pboc_social_financing` | 央行社融增量月度：总规模/人民币贷款/企业债/政府债/股票融资（三级跳到 xlsx，openpyxl 解析） | 中国宏观 / 数据行情(market) | 次月中旬发布 | 无 key，已在册可用 |
| `treasury_yield_curve` | 美债收益率曲线日更：3M/2Y/10Y/30Y + 10Y-2Y 利差 | 美国利率 / 数据行情(market) | 每交易日一更（美东下午） | 无 key，已在册可用 |
| `cftc_cot` | CFTC 持仓周报：金/银/铜/油/外汇/股指投机净多（多-空，官方 Socrata 接口） | 大宗+外汇+股指 / 数据行情(market) | 每周五发布当周周二持仓 | 无 key，已在册可用 |
| `nasdaq_earnings` | 当日美股财报日历：symbol+盘前/盘后+预期 EPS | 美股 / 数据行情(market) | 交易日更新；周末/假期返回空属正常 | 无 key，已在册可用 |
| `gelonghui` | 格隆汇首页精选一篇全文（港/美/A 评论与要闻） | 港美A / 同行文章(peer_article) | 滚动更新；同时入早报聚合（17 源之一） | 无 key，已在册可用 |
| `miningcom` | MINING.COM 大宗矿业当日条目机器汇总（≤8 条） | 大宗 / 同行文章(peer_article) | 工作日高频；当日无更返回空属正常 | 无 key，已在册可用 |
| `liberty_street` | 纽约联储 Liberty Street 最新一篇全文（联储经济学家分析博客） | 美国宏观分析 / 同行文章(peer_article) | 周 1-2 篇 | 无 key，已在册可用 |

### NEWS 项目移植（D:\AI项目\NEWS，2026-08-31）

该项目 11 个源里 8 个本项目已有等价物；以下 3 个为增量。它的财联社/东财走公共 RSSHub（已被 Cloudflare 墙），本项目直连版更稳，不回移植。

| 源 id | 给什么信息 | 市场/形态 | 作息与限额 | 启用条件 |
|---|---|---|---|---|
| `wscn_live` | 华尔街见闻全球快讯实时流（官方 API，code 20000 校验）；与"见闻早餐" peer 文章互补。全球频道含非财经条目，靠下游粗筛过滤 | 全球宏观 / 快讯(flash) | 7×24 滚动 | 无 key，已在册可用 |
| `longbridge_topics` | 长桥海豚要闻：港美券商话题热点（标题+链接+发布时刻） | 港美 / 快讯(flash) | 滚动更新，约 20 条/屏 | 无 key，已在册可用 |
| `jin10_calendar` | 金十财经日历：经济数据+事件+星级+三值（公布/预期/前值），与见闻日历不同口径互备 | 全球宏观 / 数据行情(market) | 周文件更新 | 无 key，**暂不启用**：官方 CDN 域名 cdn-rili.jin10.com 已 NXDOMAIN（2026-08-31 三方向 DoH 确认，金十日历官网同源故障），代码在册待恢复 |

移植修正记录：长桥页面锚点已失效（NEWS 原版 cheerio 选择器只能抓到页脚条款链接），改为解析页内 TanStack 脱水 JSON（`pages[].data.articles[]`）；金十日历按官方 app JS 现行路径实现（`web_data/{year}/week/{ISO周}/{economics|event}.json`，`event.json` 为单数）。

### 13 开源项目源收录（2026-08-31）

盘点 TradingAgents-CN / akshare / yfinance / zvt / TradingAgents / FinceptTerminal / ai-hedge-fund / daily_stock_analysis / qlib / RD-Agent / edgartools / FinanceMCP 等 13 个量化/数据项目封装的数据源。大部分是行情/K线库（与内容管线无关），新闻类接口多数与我们已有源重叠；以下 5 个为增量，全部零鉴权实测通过在册可用。

| 源 id | 给什么信息 | 市场/形态 | 作息与限额 | 启用条件 |
|---|---|---|---|---|
| `ths_flash` | 同花顺全球财经直播快讯：标题+摘要，带官方重要性标记（import 字段） | A股+全球 / 快讯(flash) | 7×24 滚动 | 无 key，已在册可用 |
| `caixin_flash` | 财新数据通快讯：标题+摘要+栏目标签（高质量中文财经） | A股+宏观 / 快讯(flash) | 每日滚动 | 无 key，已在册可用 |
| `yahoo_headlines` | Yahoo 财经大盘头条 RSS（英文，出版方署名，默认 SPY 视角可换 symbol） | 美股 / 快讯(flash) | 交易日滚动 | 无 key，已在册可用 |
| `sec_insider` | SEC Form 4 内部人交易申报：高管/大股东买卖（与 sec_edgar 同 atom 端点，type=4） | 美股 / 公告(announcement) | 交易时段滚动 | 无 key，已在册可用 |
| `cctv_xwlb` | 央视新闻联播当日文字稿（每日 19:00 后）：国常会/部委/立法等政策信号；时政民生占比高，**不进早报聚合**，供 synth 背景按需选取 | A股政策 / 成篇(peer_article) | 每日 19:00 一期 | 无 key，已在册可用 |

弃选/不接记录：
- **DBnomics**：FRED provider 已被下架（2026-08-31 实测 `providers/FRED` 404）；IMF/WB 等宏观序列对早报边际价值低，不接。FRED 仍走已注册的 `fred_macro`（待配 key）。
- **Anspire/SerpAPI/Tavily/Bocha/Brave/TickFlow/Qveris/Twingly**（daily_stock_analysis/FinanceMCP 用）：key 型通用搜索/聚合服务，是工具不是信息源，且通用聚合稀释质量（同 NewsAPI 弃选理由）。
- **qlib / RD-Agent / zvt / ai-hedge-fund**：无量新闻源（行情/因子框架或付费 key 数据），无可收。

### 情绪/观点流 + 预测市场（2026-08-31 用户裁决纠正）

用户裁决：观点/情绪流与预测市场**一律入库**，"防污染"不做接入门槛——用不用由用户在生成时 `--set` 选择，素材好坏不由收录环节判断。此前"观点流不接"的规则作废（规范文档已同步修订）。

| 源 id | 给什么信息 | 市场/形态 | 作息与限额 | 启用条件 |
|---|---|---|---|---|
| `polymarket_sentiment` | Polymarket 预测市场财经情绪：活跃财经/宏观市场的概率（Yes 价）+24h 成交量（关键词过滤剔除体育娱乐） | 外围情绪 / 数据(market) | 实时变动 | 无 key，已在册可用 |
| `stocktwits_stream` | StockTwits 美股情绪流：散户+大V观点，带官方 Bullish/Bearish 情绪标记+点赞数 | 美股 / 观点流(flash) | 交易时段高频 | 无 key，**暂不启用**：2026-08-31 出口 IP 被 Cloudflare 挑战拦截（同 FXStreet 情况），代码在册待恢复 |
| `reddit_hot` | Reddit 财经 sub 热帖（默认 r/stocks 可换）：标题+分数+评论数+flair | 美股 / 观点流(flash) | 全天滚动 | 需免费 OAuth：`reddit_client_id`/`reddit_client_secret`（reddit.com/prefs/apps 注册 script 应用即得），配好翻开 |

历史回查（同轮用户要求）：此前因"观点流/范围外"判断被排除且**跑得通却被拦下**的，只有本轮 StockTwits/Reddit/Polymarket 三个（已纠正）。分析类轮落的雪球今日话题（阿里云 WAF）、Kobeissi Letter（Substack 404）、X 分析师 RSS 桥（nitter/RSSHub 公共实例均死）都是**跑不通**而非观点流判断，维持落选。范围外冻结清单（印度/欧洲/拉美/澳新/中东其他/加密）未解冻——用户本轮只点名了预测市场与观点流。

## 其余来源

`python cli.py sources list` 查看全部（类型/启用/健康）。
`python cli.py sources check` 全量体检（更新健康标记）。
`python cli.py sources fetch <id> --fresh` 单源实抓看条目。

## 加新来源（三种方式，由简到繁）

### 方式一：纯配置（无需写代码，适合简单 HTTP/JSON 接口）

1. `generator/config.yaml` 的 `sources:` 段加开关与参数；
2. `sources/builtin.py` 里注册一个薄包装（见下）。

### 方式二：写一个抓取函数（主力方式）

```python
# sources/builtin.py 追加
@source("my_source", kind="flash", title="我的新源", ttl_min=10, default_enabled=True)
def _my(conf):
    r = requests.get("https://...", params={"size": conf.get("page_size", 50)},
                     headers={"User-Agent": UA}, timeout=15)
    r.raise_for_status()
    return [{"time": it["time"], "text": it["text"], "source": "我的新源"}
            for it in r.json()["data"]]
```

要点：
- `kind` 取值：`flash` 快讯（进 gather）/ `peer_article` 同行早报（进 gather_refs）/
  `calendar` / `market` / `announcement`（版式素材）/ 其他（手动取用）
- 条目是 dict：`{"time": "YYYY-MM-DD HH:MM", "text": "...", "source": "显示名"}`；
  文章型再加 `title/media/url`
- `ttl_min`：缓存时长（反爬源给长一点）；`risk`：`low/medium/high`（仅标注提示
  维护频率）；`default_enabled`：config 没写开关时的默认值
- 失败直接抛异常，不要自己吞——上层会记健康（连续 3 败自动 dead 并跳过）

### 方式三：带浏览器/登录态的复杂源

参考 `generator/yuanbao_fetch.py`（Playwright 持久化登录态）的模式，
函数体里自己管浏览器生命周期，对外仍返回 `list[dict]`。

## 启用/停用

`generator/config.yaml`：

```yaml
sources:
  my_source:
    enabled: true
    page_size: 50      # 传给抓取函数的 conf 参数
```

## 健康机制

- 每次抓取（gather 或 check）都会记录成功/失败到 `data/health/sources-health.json`
- 连续失败 3 次 → `dead`：gather/gather_refs 自动跳过该源（failed 列表标注）
- 修复后 `python cli.py sources check --id <id>` 成功一次即复位为 ok

## 缓存

`data/cache/sources/<id>__<参数哈希>.json`，TTL 内直接读盘。
`--fresh` 绕过。缓存只影响重复读取，不影响首次抓取。
