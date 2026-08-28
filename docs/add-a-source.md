# 加一个新信息源（来源库操作手册）

来源库（`sources/`）= 信息来源注册表 + 爬取方式 + 健康检查 + 缓存。

## 现有来源

早报四路径（2026-08-28 打通，全部实测 ok）：
- **富途《港美早报》**：列表接口 seqMark 翻页 + 文章页 WAF 破盾，正文保留段落
- **财联社有声早报**：专栏 1151，每天 07:00，48h 内最新一篇全文
- **华尔街见闻早餐FM-Radio**：搜索接口定位 + 内容 API 补全文
- **元宝·Gangtise**：Playwright 持久化登录态问元宝拿当日投研日报（gangtise 搜狗链失败时自动兜底）；登录态过期时跑 `py -3.11 generator/yuanbao_fetch.py --login` 扫码
  注意：富途/财联社/元宝走 `peer_mornings` 聚合进工作流（`cli sources fetch peer_mornings` 手动可取），不需要在 config 里单开（避免与聚合重复抓取）。

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
