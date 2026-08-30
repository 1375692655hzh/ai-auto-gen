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
