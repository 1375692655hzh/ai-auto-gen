# 13-cursor-xsurge — 工作台图文页新增子页【蹭蹭流量】(X 起爆榜·评论卡位闭环) 实施方案

> 岗位：方案设计岗（cursor）。**只出计划，不动代码。**
> 日期：2026-09-03。产出文件仅本篇。
> 目标：复刻 SoPilot「评论卡位」闭环 —— 监控 X 大V 帖子的真互动四件套（likes/retweets/replies/views）
> 时序快照 → 算起爆概率与预测浏览量 → 按"现在去评论可得 N 次曝光"排序 → 一键送进素材池蹭热点。
> 范围：新增 `workbench/server/x_surge.py`；改 `workbench/server/app.py`、`workbench/web/js/pages/article.js`、
> `workbench/web/css/app.css`、`workbench/web/index.html`、`cli.py`；唯一新写口 `data/workbench/x_engagement.json`。
> 红线：不改 `global-news-sources/` 任何文件（只读）；workbench 对三板块只读；
> 服务器运行时（app.py 进程内）**不外呼 FxTwitter**，采集只发生在 CLI（与 enrich-x-profiles 同纪律）。
> 已验证事实直接采信（FxTwitter API 形状、8787 取数口、X 池 131 账号、x_profiles.json 就绪），本文不重复验证。

---

## 0. 产品对标：SoPilot 在做什么，我们复刻哪些

SoPilot（sopilot.net/zh/hot-tweets）的产品结构拆解：

| SoPilot 环节 | 实现 | 我们的对位 |
|---|---|---|
| 监控大V列表 | 人工维护的 X 账号清单 | 已有：`twitter_pool.yaml` 131 账号池（板块一只读） |
| 周期性快照互动四件套 | 定时抓 likes/retweets/replies/views | 本方案 `x_surge.py` 采集轮 → `x_engagement.json` 时序快照 |
| 起爆概率 + 预测总浏览量 | 互动增速 / 粉丝基线的启发式 | §5 的四分量可解释公式（0~100） |
| 榜单按起爆概率排序 | 列表页 | `/wb-api/x-surge` + 前端第 5 子页 |
| "现在去评论预计 N 次曝光" | 原帖 views × 10%，黄金窗口=发布后 2h | `comment_exposure = views × 0.10`，`golden = age ≤ 2h` |
| 立即评论动作入口 | 跳转原帖回复框 | 跳 Action 两只：「原文链接 ↗」（人工去评论）+「＋加入素材」（蹭进内容生成）——**本期不做自动评论**（发帖红线，`publish run --draft` 同源风险，留桩 §11） |

一句话差异：SoPilot 的护城河是"时序快照 → 增速"，这正是我们现有 `xhot.py` 用 dup_count+粉丝量级代理时
明确标注缺失的部分（xhot.py L3-11 注释自认）。本方案补上这一环。

---

## 1. 现状审计（已读码 + 实测 DB，行号为工作区当前文件）

### 1.1 数据站条目（板块一，只读）

实测 `data/serve/items.db`（2026-09-03）：

| 事实 | 值 | 对本方案的影响 |
|---|---|---|
| X 条目 `url` 形态 | `https://x.com/<handle>/status/<19位数字>` | 正则可稳定提取 `(handle, status_id)` |
| `author_handle` | 池源条目必有（小写 handle） | 非池账号混入的口子天然很小（§8.5） |
| `id` | md5 hex 32 字符（`store.py` L236-238） | 「加入素材」复用 basket 必须带这个 id |
| `time` | `"YYYY-MM-DD HH:MM"` 本地、分钟精度 | age 兜底口径（§5.1） |
| 近 30h X 条目量 | 633 条（约 21 条/小时） | 采集轮上限、文件大小账（§3.3）的依据 |
| `RETENTION_HOURS["flash"]=48`（store.py L40） | flash 条目 48h 后被清 | 快照保留窗 72h 自持，不依赖库；join 范围 24h/48h 正好卡在库保留期内 |
| `/v1/items` 参数（serve.py L151-168） | `since/limit/dedup/display/markets` | 采集取数口；`since` 含空格必须 urlencode（xhot.py L38 教训） |

### 1.2 workbench 服务端

| 文件:行 | 现状 | 本方案用法 |
|---|---|---|
| `app.py` L21 | import 列表 | 加 `x_surge` |
| `app.py` L153-158 | `/wb-api/x-hot` 端点 + `UpstreamError` 502 模式 | 新端点 `/wb-api/x-surge` 完全同构（L30-40 样式） |
| `proxy.py` L71-93 | `fetch_json(path_qs)` 带 Key 注入 | 采集轮取条目唯一通道；`UpstreamError` 区分"未配置"(→exit 4)与"不可达"(→exit 3) |
| `x_profile_enricher.py` L51-56 | `tempfile.mkstemp` + `os.replace` 原子写范式 | `x_engagement.json` 落盘照抄 |
| `x_profile_enricher.py` L142-170 | CLI `run_cli(args)` + `--json` + 批级进度 + 失败 exit 3 | `refresh-x-surge` 的 CLI 壳同构 |
| `xaccounts.py` L61-93 | `load_accounts()` mtime 缓存，返回 `{handle_key: {name, markets, role, positioning...}}` | 采集侧白名单 + API 侧展示字段来源 |
| `x_profile_enricher.load_cache()` L40-48 | 损坏容错（坏 JSON 当空） | 快照文件读取同规则，但**更保守**：坏文件先改名留存再当空（§3.4，快照丢了基线就没了，比档案缓存金贵） |

### 1.3 前端

| 文件:行 | 现状 | 本方案用法 |
|---|---|---|
| `article.js` L72-91 | `registerSubs()`：`/article` 路由守卫 + `WB.shell.setSubs([...], this.tab)` | 追加第 5 项 `surge`；守卫逻辑零改动 |
| `article.js` L24 | `basketIds` 已加入态 | surge 列表复用，键 = store 条目 id |
| `article.js` L145-154 | `addToPool(it)` / `initBasketIds()` | surge 用 shim 对象适配（§7.5） |
| `article.js` L156-176 | `loadXHot()` + `xhot` 数据流 | 结构样板：surge 的 load/筛选/err 全套同构 |
| `article.js` L347 | `mounted()` 首屏加载清单 | 追加 `this.loadSurge()` |
| `api.js` L63-83 | `WB.basket.add()` 只读 `item.id/time/source/text/title/url` 五字段 | shim 只需凑齐这五个 |
| `css/app.css` L377-389 | `.xhot-item/.xhot-top/.rank/.xhot-fol/.xhot-text/.xhot-meta` | surge 行样式以它为基，新增类只做增量 |
| `css/app.css` L139-161 | `.badge`（green/red/yellow/blue）/`.chip`（on/dead） | 徽章/chip 全复用，仅新增 `.badge.gold` |
| `index.html` L7,54-60 | 全部资产 `?v=0904c` 同一 token | bump 规则见 §7.7 |

### 1.4 CLI

`cli.py`：`workbench_cmd` L293-330（serve/status/enrich-x-profiles 三分支，`sys.path.insert(0, str(WB))` 后延迟 import）；
parser L527-542（`pw_e` 为 enrich-x-profiles 参数组）。新增 `refresh-x-surge` 子命令在这两处各加一段，
退出码沿用 `EXIT_OK/EXIT_FAIL/EXIT_CONFIG`（0/3/4）。

---

## 2. 与 xhot.py 的关系（二选一：本期**保留**，附并入触发条件）

**决策：本期保留 xhot.py 与右栏 X 热帖榜不动，surge 作为独立子页并行。** 理由：

1. **可靠性分层不同**。xhot 零外呼、零成本，数据站一开就能出榜；surge 依赖采集轮次积累 ≥2 个快照才有增速，
   冷启动 4~6 小时内是"半残榜"（只有绝对量，无起爆概率）。把右栏绑到 surge 上，新装/清库用户体验立刻降级。
2. **排序语义不同**。xhot 是"全池多样性榜"（dup_count 事件簇 × 粉丝量级，每账号限 2 条防 nikkei 霸榜）；
   surge 是"单帖起爆榜"（同一大V两条同时起爆就该都进榜，**不做每账号限量**）。语义合并会让两边都不纯粹。
3. **失效半径不同**。FxTwitter 若限速/挂，xhot 不受影响，工作台仍有一个能看的 X 榜——天然的降级备份。

**并入触发条件（写死，到期由 agent 或人核对一次）**：surge 上线后连续 14 天里，满足
`snapshot_coverage ≥ 0.85` 且 `data_age_min ≤ 60` 的天数 ≥ 12 天 → 执行并入：右栏数据源从 `/wb-api/x-hot`
切到 `/wb-api/x-surge?limit=12`（golden 优先展示），`/wb-api/x-hot` 端点保留一个发布周期后删除，
`xhot.py` 同步删除。不满足则继续保留，每 14 天复评一次。判定数据就来自 `/wb-api/x-surge` 的 `meta` 字段，零额外埋点。

---

## 3. 数据模型（A）：`data/workbench/x_engagement.json`

### 3.1 顶层结构

```json
{
 "version": 1,
 "updated_at": "2026-09-03 21:30:00",
 "rounds": [
   {"ts": 1796472600, "ok": 142, "miss": 9, "skipped_non_pool": 0, "rate_limited": false}
 ],
 "posts": {
   "2095243222734049338": {
     "handle": "deitaone",
     "created_ts": 1796458286,
     "snapshots": [
       {"ts": 1796472600, "likes": 273, "retweets": 13, "replies": 54, "views": 180441},
       {"ts": 1796469000, "likes": 198, "retweets": 11, "replies": 47, "views": 128102}
     ]
   }
 }
}
```

字段契约（写代码必须逐条对齐）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `version` | int | 结构版本，读到更高版本时按空文件处理并在返回里带 `hint`（防旧代码写坏新数据） |
| `rounds` | list | 每轮采集的摘要，**只留最近 96 条**（2 天轮次史，供 meta 统计与排障） |
| `posts` 的键 | **字符串** | status_id。X snowflake 超出 JS `Number.MAX_SAFE_INTEGER`，全链路（Python/JSON/JS）一律字符串，任何地方 `int()` 后回写 JSON 即为 bug |
| `posts[].handle` | str | 小写 handle，采集时写入；与 items join 时做一致性校验（§8.5） |
| `posts[].created_ts` | float | 发帖时刻 epoch 秒（UTC 口径，来自 FxTwitter `created_at`）；缺失回退条目 `time` 按本地时区折算 |
| `snapshots[]` | list | 按 `ts` **升序**追加；`views` 可能为 `null`（§8.3），其余三项缺失记 0 |

### 3.2 快照追加规则（幂等核心）

每轮对每个采样成功的 status_id：

1. 读取该 post 现有 `snapshots`；
2. 若最新一条 `ts` 距本轮 `ts` **< 20 分钟**（`MIN_SNAPSHOT_INTERVAL = 1200s`）→ **跳过追加**（重复跑不膨胀）；
3. 否则 append `{"ts": 本轮ts, likes, retweets, replies, views}`；
4. 全部处理完后统一落盘（**整轮一次原子写**，不是每条一写——快照文件是单写者模型：只有 CLI 采集轮写，
   API/前端只读，无并发写冲突，整轮写最简单且崩溃时旧文件完好）。

这保证了 `refresh-x-surge` 幂等可重跑：连跑两次，第二次对刚采过的帖子零外呼、零追加（§4.4）。

### 3.3 保留窗口与文件大小控制

- **保留窗口 72h**（`RETENTION = 72 * 3600`）：落盘前双向修剪——
  ①每条 snapshot 删除 `ts < now - 72h` 的；②修剪后 `snapshots` 为空的 post 整条删除。
- **单帖快照数上限 40**（`MAX_SNAPSHOTS_PER_POST`）：超限时做**稀疏化抽稀**——保首尾，中间按等距抽到 38 条内
  （采集间隔 30min 时 72h 理论最多 144 条，上限 40 意味着 6h 后自动降采样，增速计算取最近两条即可，不受影响）。
- **文件大小账**（按实测 633 条/30h 推算）：
  - 24h 活跃帖 ≈ 500，72h 累计 distinct 帖 ≈ 1100；
  - 每条 snapshot ≈ 75 字节 JSON，稳态平均 8 条/帖（稀疏化后）；
  - 估算稳态体积 ≈ 1100 × (8 × 75 + 60) ≈ **0.7 MB**，上限情形 ≈ 1100 × (40 × 75 + 60) ≈ **3.4 MB**；
  - **硬护栏**：落盘前若序列化结果 > 5 MB（`MAX_FILE_BYTES`），强制对全部 post 抽稀到最近 6 条再写一次；
    仍超限则本轮拒绝写入并保留旧文件（打警告，exit 3）——防止病态数据撑爆盘。
- `indent=1`（与 x_profiles.json 同款，人肉可查排障）。

### 3.4 读写函数契约

```
load_engagement() -> dict        # 容错读：文件不存在/JSON坏 → {"version":1,"posts":{},"rounds":[]}
                                 # JSON坏时先把原文件改名为 x_engagement.corrupt.<ts>.json 留证再当空
save_engagement(d) -> None       # DATA_DIR.mkdir(parents=True, exist_ok=True) + mkstemp + os.replace
```

模块常量（全部集中文件顶部，调参只动这一处，见 §12 常量总表）：

```python
DATA_FILE   = Path(__file__).resolve().parents[2] / "data" / "workbench" / "x_engagement.json"
RETENTION_S = 72 * 3600          # 快照保留窗
MIN_SNAPSHOT_INTERVAL = 1200     # 20min 内重复采不追加(幂等)
MAX_SNAPSHOTS_PER_POST = 40      # 单帖快照稀疏化上限
MAX_FILE_BYTES = 5 * 1024 * 1024 # 硬护栏
GOLDEN_WINDOW_H = 2.0            # 黄金窗口(发布后2h)
```

---

## 4. 采集器（B）：`workbench/server/x_surge.py`

### 4.1 模块骨架（函数签名即契约）

```python
"""X 起爆榜采集与指标(蹭蹭流量子页)。采集只在 CLI 进程发生, 服务器只读缓存。"""

def collect(range_="24h", max_posts=150, force=False, on_progress=None) -> dict
    # 一轮采集: 取条目 → 选样 → 批调 FxTwitter → 追加快照 → 原子落盘
    # 返回 {"round_ts", "candidates", "sampled", "ok", "miss", "skipped_non_pool",
    #       "skipped_fresh"(20min内已采), "rate_limited", "elapsed_s"}

def build_view(range_="24h", markets="", golden=False, min_followers=0, limit=50) -> dict
    # 读快照文件 + 实时 join 数据站条目 → §6 的 API 形状(排序/筛选/指标在这里算)
    # 数据站不可达时抛 proxy.UpstreamError(app.py 现有模式接住转 502)

def run_cli(args) -> int          # cli.py workbench_cmd 分支调用, 风格对齐 x_profile_enricher.run_cli
```

### 4.2 第一步：从数据站拉近窗条目（经 proxy，零直连）

```python
sec = _WINDOWS[range_]                       # {"24h": 86400, "48h": 172800}
qs = {"limit": _ITEMS_LIMIT[range_],         # {"24h": 800, "48h": 1600} —— 24h 实测约500条, 300不够全量
      "dedup": 1, "display": 1,
      "since": time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - sec))}
items = proxy.fetch_json("items?" + urllib.parse.urlencode(qs)).get("items") or []
```

- `since` 含空格 → **必须 urlencode**（xhot.py L38 注释的前车之鉴，复用其 `_since_str` 写法）。
- `UpstreamError` 直接向上抛：CLI 侧接住分类（`code==0` 数据站不可达 → exit 3；配置缺失文案 → exit 4）。

### 4.3 第二步：提取候选 + 选样（并发/限速/单轮上限）

**提取**：对每条 item，`m = re.search(r"https?://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/(\d+)", it.get("url") or "")`；
命中得 `(handle.lower(), status_id字符串, item)`；`author_handle` 与正则 handle 双保险，正则不命中跳过并计数。

**池白名单**：`pool = xaccounts.load_accounts()`；`handle not in pool` → `skipped_non_pool += 1` 丢弃
（SoPilot 语义 = 监控列表内卡位；池外账号粉丝基线缺失，公式失真，见 §8.5）。

**候选表构建**：按 `(handle, status_id)` 去重（同一 status_id 在库内可能因转发变体出现多行——dedup=1 已大幅收敛，
但仍以 `(handle, status_id)` 为键、`time` 最新者胜出，保留其 `item_id` 供前端加素材用）。

**选样优先级**（`max_posts` 默认 150，`--max-posts` 可调；排序后截前 N）：

```
组1: 快照文件里最新快照 age ≤ 2h(GOLDEN_WINDOW_H) 的帖  —— 黄金窗口跟踪优先(产品核心)
组2: 其余候选按条目 time 降序                          —— 新帖先采(尽快拿到首个快照)
不采: 最新快照 age > 6h 且帖龄 > 8h 的帖               —— 曲线已过拐点, 采样价值低, 让出名额
                                                      (历史快照仍在文件里保留到72h, 指标不受影响)
```

理由：150/轮 × 每 30min 一轮 ≈ 7200 次/日 ≫ 500 帖/日，稳态下组1（2h × 21条/h ≈ 42 帖）+
组2 能让**每条新帖在发布后 ~30min 内拿到首采、~1.5h 内拿到第二个快照**——正好赶在黄金窗口关闭前算出增速。

**FxTwitter 批量调用**（外呼只在此处，仅 CLI 进程）：

| 参数 | 值 | 依据 |
|---|---|---|
| 并发 | `ThreadPoolExecutor(max_workers=4)` | 公共免费服务，压 4 并发是礼貌上限；150 条耗时约 40~90s |
| 单请求超时 | 8s | FxTwitter 正常 <1s，8s 足够宽容 |
| URL | `https://api.fxtwitter.com/{handle}/status/{status_id}` | 已验证事实① |
| 解析 | `d["tweet"]` 里取 `likes/retweets/replies/views/created_at`；**每字段独立容错**（KeyError/None → likes 等记 0，views 记 None），created_at 按 §5.1 解析失败记 None | 单字段缺失不能废整条 |
| HTTP 429 | 全局熔断：置 `rate_limited=True`，**立即中止本轮**（已成功的保留），退避 60s 后不重试（下轮调度自然续上） | 公共服务被 ban 是最大风险，宁可少采 |
| HTTP 404/5xx/超时/JSON坏 | 该帖记 `miss`，不中断 | 单点失败不废轮 |
| 每轮硬上限 | `min(max_posts, 300)` | 防手滑 `--max-posts 100000` 打爆对方 |

### 4.4 幂等与断点

- 20 分钟内已采过的帖在**选样阶段就被剔除**（读文件即可判断），重跑不产生外呼、不重复追加（§3.2）。
- 采集中途崩溃 / Ctrl+C：文件未被触碰（整轮结束才原子写），重跑即续；
  可选 `on_progress(done, total, ok)` 回调供 CLI 打进度行（对齐 enrich-x-profiles 的批次进度体验）。
- `--force`：忽略 20 分钟窗，强制重采本轮候选（排障用）。

### 4.5 CLI：`python cli.py workbench refresh-x-surge`

```
python cli.py workbench refresh-x-surge [--range 24h|48h] [--max-posts N] [--force] [--json]
```

- `cli.py` parser（L542 `pw_e` 之后）：`pw_r = wsub.add_parser("refresh-x-surge", help="X起爆榜互动快照采集(FxTwitter → data/workbench/x_engagement.json)")`，
  参数 `--range`(default "24h") / `--max-posts`(type=int, default=150) / `--force` / `--json`。
- `workbench_cmd` L297 后加分支：`if args.sub == "refresh-x-surge": sys.path.insert(0, str(WB)); from server import x_surge; return x_surge.run_cli(args)`。
- 输出（非 json 模式人读，json 模式机器读）：

```
X起爆榜快照采集: 候选 486 / 采样 150 / 成功 142 / 失败 9 / 20min内已采 108 / 非池跳过 3 · 限速否
  → data/workbench/x_engagement.json (1.2 MB, 帖 1104) · 耗时 67s
```

- 退出码：`0` 正常（含全部 miss 但部分成功）/ `3` 全军覆没（0 成功）或数据站不可达 / `4` 数据源未配置。

### 4.6 调度建议（非本期代码，运维动作）

板块一的 Windows 任务计划每 30min 跑 `sources refresh`；**同期追加一条**任务计划：
`python cli.py workbench refresh-x-surge --range 24h`（30min 对齐，黄金窗口采样密度即由此保证）。
本期先手动跑 + 文档说明，任务计划注册作为落地步骤 §9 第 7 步的可选项。

---

## 5. 指标计算（C）：全部公式（可解释，常量集中于 §12）

### 5.1 时间口径

- FxTwitter `created_at` 形如 `"Wed Sep 02 20:11:26 +0000 2026"`。
  解析主路径：`datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")`（%z 吃 `+0000`）；
  兜底路径：手写月名映射 `{"Jan":1,...}` + `timezone.utc`（防 Windows locale 把 %a/%b 解析挂掉）。
  → `created_ts`（epoch 秒，UTC）。两路都挂 → 回退条目 `time`（本地）`strptime("%Y-%m-%d %H:%M")` 折算。
- `age_h = max((now - created_ts) / 3600, 0)`；`created_ts` 也没有 → age 视为 24h（不出黄金窗口，保守）。

### 5.2 增速（最近两快照差 / 时间差）

```
取 snapshots 末两条 s1, s2（s2 更新），span_h = (s2.ts - s1.ts)/3600
span_h ≥ 5min 才计算(防抖):
  views_growth_per_h = (s2.views - s1.views) / span_h     # s1/s2 任一 views=null → null
  likes_growth_per_h  = (s2.likes - s1.likes) / span_h
归一化(粉丝基线比值, 消大号嗓门偏差):
  rate_norm = views_growth_per_h / max(followers, 1000)   # "每千粉每小时新增浏览"
  likes_rate_norm = likes_growth_per_h / max(followers, 1000)
span < 5min 或快照 <2 条 → growth 全部 null（前端显示 "—"，§8.1）
```

### 5.3 起爆概率 surge（0~100，四分量加权）

```
surge = S1(增速分位, 40) + S2(粉丝基线比, 30) + S3(发布时长衰减, 20) + S4(绝对量确认, 10), 截到 [0,100]
```

**S1 增速分位（0~40）**：对本次 build_view 参与排序的、有 growth 的帖集合，取 `rate_norm` 的百分位
（rank-1)/(n-1)，n≥10 用分位；n<10 分位不稳，退回绝对档表）：

| rate_norm（每千粉·时新增浏览） | S1 |
|---|---|
| ≥ 2.0 | 40 |
| ≥ 1.0 | 32 |
| ≥ 0.5 | 24 |
| ≥ 0.2 | 16 |
| ≥ 0.05 | 8 |
| > 0 | 3 |
| 无 growth（无基线/views缺失） | 0（整体退化规则见 §5.6） |

**S2 粉丝基线比（0~30）**：`ratio = views / max(followers, 1000)`（"破圈度"：浏览量走出粉丝圈多远）：

| ratio | S2 |
|---|---|
| ≥ 3.0 | 30 |
| ≥ 1.5 | 24 |
| ≥ 0.8 | 18 |
| ≥ 0.3 | 12 |
| ≥ 0.1 | 6 |
| > 0 | `round(ratio / 0.1 * 3)` 封顶 5 |
| views 缺失 | 0 |

**S3 发布时长衰减（0~20）**——"起爆"是新鲜事，老帖增速再高也不是卡位点：

| age_h | S3 |
|---|---|
| ≤ 1 | 20 |
| ≤ 2 | 16 |
| ≤ 4 | 10 |
| ≤ 8 | 6 |
| ≤ 16 | 3 |
| ≤ 24 | 1 |
| > 24 | 0 |

**S4 绝对量确认（0~10）**——防"小号高增速"误报：

| views | S4 |
|---|---|
| ≥ 100k | 10 |
| ≥ 30k | 7 |
| ≥ 10k | 4 |
| ≥ 2k | 2 |
| ≥ 500 | 1 |
| 其他/缺失 | 0 |

API 返回每条的 `surge_parts: {growth, baseline, decay, abs}`（透明构成，前端 tooltip 展示，与 reco 页
`score_parts` 同理念）。**排序用 surge 降序，平分按 views 降序**——无基线条目 surge 上限天然只有 60，
会自然沉底，这正是期望行为（信息少 → 排后）。

### 5.4 预测总浏览量 predicted_views

```
views 缺失 → null
predicted_views = round(views × (1 + 3 / max(age_h, 0.5)))，上限 views × 4（封顶防 early-hour 失控）
```
解释：经验上推文浏览量长尾在发布 2h 时未来增量约为存量 1~1.5 倍、6h 时约 0.5 倍、24h 后 <15%。
`k=3` 拟合该衰减形状（age=2h → ×2.5，6h → ×1.5，24h → ×1.125），常数进 §12 总表，跑两周后可用
"predicted vs 实际终值" 回测校准（§11）。

### 5.5 预计评论曝光 + 黄金窗口

```
comment_exposure = round(views × 0.10)          # SoPilot 口径: 热帖评论区≈原帖10%曝光
golden = (0 < age_h ≤ 2.0)                      # 黄金窗口=发布后2h; age 未知一律 false
comment_exposure 前端文案: "现在去评论 ≈ 1.8万 次曝光"; 非 golden 显示 "窗口已过, 预计 ≈ N"
views 缺失 → null, 前端显示 "—"
```

### 5.6 缺数据退化总表（实现必须逐行覆盖）

| 场景 | S1 | S2 | S4 | growth | predicted | comment_exposure | has_baseline |
|---|---|---|---|---|---|---|---|
| 快照 ≥2 且 views 全有 | 分位/档表 | 正常 | 正常 | 有 | 有 | 有 | true |
| 快照 =1（首轮） | 0 | 正常 | 正常 | null | 有 | 有 | **false** |
| views 缺失（任一涉及快照） | 改用 `likes_rate_norm` 套同一张 S1 档表 | 0 | 0 | likes 增速有 / views 增速 null | null | null | true |

---

## 6. API（D）：`GET /wb-api/x-surge`

`app.py` 在 `/wb-api/x-hot`（L153-158）之后加，同构写法：

```python
@app.get("/wb-api/x-surge")
def x_surge_view(range: str = "24h", markets: str = "", golden: int = 0,
                 min_followers: int = 0, limit: int = 50):
    try:
        return x_surge.build_view(range_=range, markets=markets,
                                  golden=bool(golden), min_followers=min_followers,
                                  limit=min(limit, 200))
    except proxy.UpstreamError as e:
        return JSONResponse({"error": str(e)}, status_code=e.code or 502)
```

成功响应全量形状（实现方以此为准逐字段对齐）：

```json
{
  "items": [
    {
      "status_id": "2095243222734049338",
      "item_id": "6d360d63cdac690d8c1b51e0ee41696e",
      "handle": "DeItaone",
      "name": "Walter Bloomberg",
      "followers": 1234567,
      "verified": true,
      "positioning": "快讯源",
      "markets": ["美国"],
      "text": "BREAKING: …(≤160字, 取 text_display 逻辑同 xhot)",
      "url": "https://x.com/DeItaone/status/2095243222734049338",
      "time": "2026-09-03 20:11",
      "age_h": 1.4,
      "eng": {"likes": 273, "retweets": 13, "replies": 54, "views": 180441},
      "eng_at": "2026-09-03 21:30",
      "growth": {"views_per_h": 52300.0, "likes_per_h": 61.0, "span_min": 31},
      "surge": 78,
      "surge_parts": {"growth": 34, "baseline": 22, "decay": 16, "abs": 6},
      "predicted_views": 451102,
      "comment_exposure": 18044,
      "golden": true,
      "has_baseline": true,
      "snapshots_n": 4,
      "dup_count": 1
    }
  ],
  "meta": {
    "range": "24h", "count": 50, "collected_at": "2026-09-03 21:30:00",
    "data_age_min": 12, "stale": false, "coverage": 0.83,
    "rule": "surge=增速分位40+破圈度30+时效20+绝对量10; 曝光≈原帖views×10%; 黄金窗口=发布2h内",
    "hint": ""
  }
}
```

要点：

- `followers/verified` 来自 `data/workbench/x_profiles.json`（经 `x_profile_enricher.load_cache()`），
  缺档账号 `followers=0`（公式 `max(followers,1000)` 兜底，不阻塞出榜——xhot L9 同宽容）。
- `name/positioning/markets` 优先池 yaml（`xaccounts.load_accounts()`），回退条目 `source` 去 `X·` 前缀
  （article.js `xHotName` 同规则）。
- `meta.stale = data_age_min > 90`；`coverage = 有快照的候选帖 / 候选帖总数`（前端黄条与 §2 并入判据都吃它）。
- 服务端筛选顺序：窗口 → markets（条目 markets 与池账号 markets 并集任一命中）→ golden → min_followers →
  排序 → 截 limit。全部参数可组合，缺省全关。
- 错误形状与既有端点一致：数据站不可达 → 502 `{"error": "...", "hint": "..."}`（proxy UpstreamError 文案自带提示）；
  快照文件为空/不存在 → 正常 200，`items: []` + `meta.hint = "暂无快照: 先跑 python cli.py workbench refresh-x-surge --range 24h"`。

---

## 7. 前端子页（E）：图文页第 5 子页【蹭蹭流量】

### 7.1 data 增量（article.js data() 追加）

```js
/* ── 蹭蹭流量(X起爆榜) ── */
surgeItems: [], surgeMeta: {}, surgeRange: "24h", surgeMarkets: [],
surgeGoldenOnly: false, surgeMinFol: false,
surgeLoading: false, surgeErr: "",
```

computed 增量：

```js
surgeMarketChips() { return this.xMarketChips; },          // 复用池账号市场集
surgeGoldenCount() { return this.surgeItems.filter((r) => r.golden).length; },
```

### 7.2 registerSubs 注册（插在 reco 之后、gen 之前，选题动线：荐→蹭→生成）

```js
{ id: "surge", title: "蹭蹭流量", cnt: this.surgeGoldenCount || "",
  icon: I('<path d="M4.5 16.5 3 21l4.5-1.5"/><path d="M14 4c3-1.5 6 1.5 4.5 4.5L11 16l-3-3Z"/>' +
          '<path d="M9 15 5.5 11.5c1-3 3.5-6 7-7.5"/>'),        // 火箭
  onPick: () => { this.tab = "surge"; } },
```

`/article` 前缀路由守卫天然覆盖（子页同属 article 容器），守卫代码零改动。`go(t)` 现有实现自动适配。

### 7.3 加载与筛选方法

```js
async loadSurge() {
  this.surgeLoading = true; this.surgeErr = "";
  try {
    const p = new URLSearchParams({ range: this.surgeRange });
    if (this.surgeMarkets.length) p.set("markets", this.surgeMarkets.join(","));
    if (this.surgeGoldenOnly) p.set("golden", "1");
    if (this.surgeMinFol) p.set("min_followers", "100000");
    p.set("limit", "50");
    const d = await WB.api.get("/x-surge?" + p.toString());
    this.surgeItems = d.items; this.surgeMeta = d.meta || {};
  } catch (e) { this.surgeErr = e.error || "起爆榜接口不可用"; }
  this.surgeLoading = false; this.registerSubs();
},
surgeToggle(group, val) { /* 与 recoToggle 同构 */ this.loadSurge(); },
```

`mounted()` 追加 `this.loadSurge();`（放到 `this.loadXHot()` 之后，市场 chips 已就绪不影响——chips 来自
`xAccounts`，`loadSurge` 与 `loadX` 并行无害，chips 是 computed 会响应式补齐）。

### 7.4 列表行布局（对齐 `.xhot-item` 风格，字段排布定稿）

```
┌ .surge-item ─────────────────────────────────────────────────────────────┐
│ [1]  78  黄金窗口   @DeItaone · Walter Bloomberg      粉123.4万 快讯源 美国│
│  rank surge徽章  窗口徽章   正文两行截断(.surge-text, 同.xhot-text截断)    │
│                                                                          │
│  浏览 18.0万 · 赞 273 · 转 13 · 评 54   增速 5.2万/h   预测总浏览 45.1万   │
│  ► 现在去评论 ≈ 1.8万 次曝光(黄金窗口) / 窗口已过, 预计 ≈ N                │
│  [原文链接 ↗] [＋加入素材]                      快照×4 · 12分钟前采集     │
└──────────────────────────────────────────────────────────────────────────┘
```

模板骨架（v-for 内，供实现直接搬）：

```html
<div v-show="tab==='surge'">
  <div class="feed-toolbar">
    <div class="frow" style="margin-bottom:0">
      <span class="chip" :class="{on: surgeRange==='24h'}" @click="surgeRange='24h'; loadSurge()">24h</span>
      <span class="chip" :class="{on: surgeRange==='48h'}" @click="surgeRange='48h'; loadSurge()">48h</span>
      <span class="chip" :class="{on: surgeGoldenOnly}" @click="surgeGoldenOnly=!surgeGoldenOnly; loadSurge()">黄金窗口</span>
      <span class="chip" :class="{on: surgeMinFol}" @click="surgeMinFol=!surgeMinFol; loadSurge()">粉≥10万</span>
      <span v-for="m in surgeMarketChips" class="chip" :class="{on: surgeMarkets.includes(m)}"
            @click="surgeToggle('surgeMarkets', m)">{{ m }}</span>
      <span style="flex:1"></span>
      <button class="btn" @click="loadSurge">{{ surgeLoading ? '刷新中…' : '刷新' }}</button>
    </div>
  </div>
  <p class="muted" style="margin:10px 0">{{ surgeMeta.rule }}
    <template v-if="surgeMeta.data_age_min != null"> · 快照采集于 {{ surgeMeta.data_age_min }} 分钟前
      <span v-if="surgeMeta.stale" class="badge yellow">数据较旧</span></template>
    <template v-if="surgeMeta.coverage != null"> · 快照覆盖 {{ (surgeMeta.coverage * 100).toFixed(0) }}%</template>
  </p>
  <div v-if="surgeErr" class="err-box">{{ surgeErr }}</div>
  <div v-else-if="!surgeItems.length && !surgeLoading" class="empty">
    暂无起爆数据 —— 先跑 <code>python cli.py workbench refresh-x-surge --range 24h</code>(首日建议跑2~4轮积累基线)</div>
  <div class="card">
    <div v-for="(r, i) in surgeItems" :key="r.status_id" class="surge-item">
      <div class="surge-top">
        <span class="rank">{{ i + 1 }}</span>
        <span class="surge-score" :class="r.surge >= 70 ? 'hot' : r.surge >= 40 ? 'warm' : ''"
              :title="'增速+'+r.surge_parts.growth+' 破圈+'+r.surge_parts.baseline+' 时效+'+r.surge_parts.decay+' 量能+'+r.surge_parts.abs">
          {{ r.has_baseline ? r.surge : '—' }}</span>
        <span v-if="r.golden" class="badge gold">黄金窗口</span>
        <span class="name">@{{ r.handle }} · {{ r.name }}</span>
        <span v-if="r.followers" class="xhot-fol">粉 {{ fmtFol(r.followers) }}</span>
        <span v-for="m in r.markets" class="badge">{{ m }}</span>
        <span v-if="r.positioning" class="badge blue">{{ r.positioning }}</span>
        <span class="surge-age muted">{{ r.time }} · {{ ageHours(r) < 24 ? Math.floor(ageHours(r)) + ' 小时前' : Math.floor(ageHours(r)/24) + ' 天前' }}</span>
      </div>
      <a class="surge-text" :href="r.url" target="_blank" rel="noopener">{{ r.text }}</a>
      <div class="surge-eng mono">
        浏览 {{ fmtNum(r.eng.views) }} · 赞 {{ r.eng.likes }} · 转 {{ r.eng.retweets }} · 评 {{ r.eng.replies }}
        <span class="muted">·</span> 增速 {{ r.growth ? fmtNum(Math.round(r.growth.views_per_h)) + '/h' : '—' }}
        <span class="muted">·</span> 预测总浏览 {{ r.predicted_views ? fmtNum(r.predicted_views) : '—' }}
      </div>
      <div class="surge-exposure" :class="{golden: r.golden && r.comment_exposure}">
        {{ r.comment_exposure ? (r.golden ? '现在去评论 ≈ ' : '窗口已过, 预计 ≈ ') + fmtNum(r.comment_exposure) + ' 次曝光' : '曝光预估不可用(浏览量缺失)' }}
      </div>
      <div class="news-actions">
        <a :href="r.url" target="_blank" rel="noopener">原文链接 ↗</a>
        <span v-if="basketIds[r.item_id]" class="act-done">已加入 ✓</span>
        <span v-else class="act" @click="addSurgeToPool(r)">＋加入素材</span>
        <span class="muted surge-snap" style="margin-left:auto">
          快照×{{ r.snapshots_n }}<template v-if="!r.has_baseline"> · 基线积累中(下轮起算增速)</template></span>
      </div>
    </div>
  </div>
</div>
```

### 7.5 动作：「＋加入素材」（复用 basketIds 已加入态）

```js
addSurgeToPool(r) {
  WB.basket.add({ id: r.item_id, time: r.time, source: r.name || ("X·@" + r.handle),
                  text: r.text, url: r.url });
  this.basketIds[r.item_id] = true;
  this.syncMaterials();
},
```

- `WB.basket.add` 只吃 `id/time/source/text/title/url`（api.js L66-73），shim 五字段齐全即可，
  进池后在「内容生成」素材池、「资讯页素材篮」、推荐信息页 `basketIds` 三处天然同态（同一 store id）。
- `initBasketIds()`（article.js L151）无需改：surge 与 reco 共用 `basketIds`，键都是 store 条目 id。
- `fmtNum(n)` 新增工具方法（views 类大数）：`n == null ? '—' : n >= 1e8 ? (n/1e8).toFixed(1)+'亿' : n >= 1e4 ? (n/1e4).toFixed(1).replace(/\.0$/,'')+'万' : String(n)`；`fmtFol` 沿用现有。

### 7.6 新增 CSS（app.css 末尾追加，约 40 行）

```css
/* ── 蹭蹭流量(X起爆榜) ── */
.surge-item { padding: 10px 0; border-bottom: 1px solid var(--border); }
.surge-item:last-of-type { border-bottom: none; }
.surge-top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 4px; }
.surge-top .rank { font-family: var(--mono); font-size: 11px; color: var(--accent); min-width: 18px; }
.surge-score { font-family: var(--mono); font-size: 15px; font-weight: 700; color: var(--text-dim);
               min-width: 34px; text-align: center; }
.surge-score.warm { color: var(--accent); }
.surge-score.hot  { color: var(--yellow); }
.badge.gold { color: #d48806; border-color: #d48806; }
body.light .badge.gold { color: #ad6800; border-color: #ad6800; }
.surge-top .name { font-size: 12.5px; font-weight: 600; }
.surge-age { margin-left: auto; font-size: 11px; white-space: nowrap; }
.surge-text { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
              overflow: hidden; font-size: 12.5px; line-height: 1.5; }
.surge-text:hover { color: var(--accent); }
.surge-eng { font-size: 12px; margin-top: 5px; }
.surge-exposure { font-size: 12px; margin-top: 3px; color: var(--text-dim); }
.surge-exposure.golden { color: var(--yellow); font-weight: 600; }
.surge-snap { font-size: 11px; }
```

（`.mono` 若无现成类则本次一并补 `.mono { font-family: var(--mono); }`；`--yellow/--accent/--mono` 等
token 均已存在。）

### 7.7 index.html 版本号 bump 规则

- 现状：8 处资产共用 `?v=0904c`（L7 stylesheet + L54-60 六个 script）。
- 规则：**凡是本次改动涉及 JS 或 CSS，就把全部 8 处统一 bump 到同一个新 token**，token = `MMDD+当日序号字母`
  （本次应为 `0903d` 起顺延；若同日多轮迭代取未用过的下一个字母）。与 app.py L233-238 的 `no-cache`
  中间件配合：token 不 bump 则 webview 可能新 HTML 配旧 JS/CSS 混载——这是迭代期实际发生过的事故类。
- 本次 bump 涉及 `article.js` + `app.css` 两个文件，但 8 处全改（保持"单一 token"惯例，不做按文件分版本）。

---

## 8. 边界与降级（F，逐项定案）

### 8.1 首轮无基线（快照只有 1 条）

- growth 全 null → 前端增速列显示 `—`；surge = S2+S3+S4（上限 60），`has_baseline: false`；
- 行尾显示「基线积累中(下轮起算增速)」；排序自然沉到有基线条目之后（§5.3）。
- UI 不隐藏这些行：绝对量（views/赞/转/评）与破圈度仍有参考价值，且用户需要看到"系统在积累"。

### 8.2 FxTwitter 限速 / 挂了

- 采集侧：429 全局熔断中止本轮（§4.3），**旧快照一个字节都不动**（失败轮不落盘 harmful 数据，
  已成功条目随下一轮自然补齐；本轮 `rate_limited: true` 记入 `rounds`）。
- 读侧：`meta.collected_at/data_age_min/stale` 反映数据年龄；前端 `stale`（>90min）出黄条「数据较旧」，
  提示可手动 `refresh-x-surge`。页面**永不因采集失败而清空**——build_view 只读文件，与采集解耦。
- FxTwitter 整体不可用连续 24h：数据年龄持续增长，黄条持续，属预期降级；xhot 右栏不受影响（§2 备份价值）。

### 8.3 views 字段缺失

- FxTwitter 对部分新帖/纯视频帖返回 `views: null`：快照照记（views 存 null）；
- 指标退化按 §5.6 第三行：S1 改用 likes 增速档表，S2/S4 记 0，predicted/comment_exposure = null，
  前端对应位置显示 `—`，曝光行显示「曝光预估不可用(浏览量缺失)」。

### 8.4 status_id 去重

- 采集选样以 `(handle, status_id)` 为键去重（`time` 最新者胜出，其 `item_id` 为加素材用的 id）；
- 快照文件以 status_id 单键存储（snowflake 全局唯一，handle 冲突仅做校验告警不阻断：`posts[status_id].handle`
  与本轮 handle 不一致时以文件为准并在 rounds 摘要计 `handle_mismatch`）；
- join 阶段：一个 status_id 对多条库内行（理论被 dedup=1 收敛，保底）只出一条榜项。
- 前端 `v-for :key="r.status_id"`（不是 item_id——同帖重抓后 item 行可能换 id，status 才是稳定键）。

### 8.5 非池账号混入

- 现实来源：库内 X 条目全部出自两个池源（author_handle 必有），但 local 池/池编辑切换窗口期可能出现
  "已出库条目的 handle 已不在当前池"；
- 采集侧：`handle not in xaccounts.load_accounts()` → 跳过，`skipped_non_pool` 计数进 rounds（§4.3）；
- 读侧：join 时再校验一次（池可能刚被编辑过），不通过的不出榜——**两层闸**，保证粉丝基线（公式输入）永远来自池档案或 x_profiles 缓存；
- 未来若要把榜扩到池外（如全 X 搜索），加 `expand_pool` 开关独立演进，本期不做。

### 8.6 其他

- **时钟/时区**：age 计算全用 epoch（created_ts UTC）；条目 time 仅作展示与兜底（§5.1）。
- **快照文件损坏**：改名留证 + 当空（§3.4）→ 页面回到"首轮"状态，不炸接口。
- **服务器运行时零外呼**：`/wb-api/x-surge` 只读 `x_engagement.json` + 数据站 + 本地缓存，
  FxTwitter 挂掉不影响工作台进程健康（红线自检项）。

---

## 9. 落地步骤清单（G1，文件级，按此顺序提交）

| # | 文件 | 动作 | 内容 | 预估量 |
|---|---|---|---|---|
| 1 | `workbench/server/x_surge.py` | **新建** | §3 数据层 + §4 采集器 + §5 指标 + §6 build_view + run_cli；模块 docstring 写明"外呼只在 CLI"红线 | ~340 行 |
| 2 | `cli.py` | 改 | parser L542 后加 `pw_r` 参数组（--range/--max-posts/--force/--json）；`workbench_cmd` L297 后加三分支（exit 码语义 §4.5） | ~14 行 |
| 3 | `workbench/server/app.py` | 改 | L21 import 加 `x_surge`；L158 后加 `/wb-api/x-surge` 端点（§6 代码块） | ~12 行 |
| 4 | `workbench/web/js/pages/article.js` | 改 | §7.1 data/computed、§7.2 registerSubs 插项、§7.3 方法、§7.5 addSurgeToPool/fmtNum、§7.4 模板块、mounted 加 loadSurge | ~110 行 |
| 5 | `workbench/web/css/app.css` | 改 | 末尾追加 §7.6 样式块（含 `.mono` 缺则补） | ~40 行 |
| 6 | `workbench/web/index.html` | 改 | 8 处 `?v=` 统一 bump 新 token（§7.7） | 8 处 |
| 7 | （可选，运维）Windows 任务计划 | 加 | 30min 对齐跑 `python cli.py workbench refresh-x-surge --range 24h`（§4.6） | 0 行代码 |

依赖顺序：1 → 2/3 可并行 → 4/5/6 可并行。全链不触碰 `global-news-sources/`、`state.json`、
`ai-workflow/`，不新增任何第三方依赖（标准库 urllib/concurrent/tempfile 足够）。

---

## 10. 验证清单（G2，逐条可执行）

**采集与数据层**

1. `python cli.py workbench refresh-x-surge --range 24h --max-posts 30 --json` → exit 0，
   `ok` >0，`data/workbench/x_engagement.json` 生成且 `posts` 键全为数字字符串。
2. **幂等**：紧接着原样重跑 → `skipped_fresh` ≈ 上轮 ok 数，`ok` ≈ 0（或采到新候选），文件内
   每帖 snapshots 条数不增长（20min 窗生效）。
3. `--range 48h` 重跑 → `candidates` 明显多于 24h 轮；两轮 range 互不破坏（文件同一份，窗口只影响选样）。
4. **原子写**：采集进行中 Ctrl+C → 文件 mtime/内容不变；重跑恢复。
5. 数据站未启动时跑 → exit 3，报错含 `python cli.py sources serve` 提示；`--json` 下也是合法 JSON 输出。
6. 72h 修剪：手工把某 post 的 snapshots[0].ts 改到 4 天前并跑一轮 → 该条被修剪/整条消失；文件 < 5MB。

**指标**

7. 首轮（新库）调 `curl http://127.0.0.1:8788/wb-api/x-surge` → 每条 `has_baseline=false`、`growth=null`、
   `surge ≤ 60`；跑第二轮（间隔 >20min，或临时把 MIN_SNAPSHOT_INTERVAL 调小验证）后 →
   有 growth、surge 含 growth 分量、`surge_parts` 四项和 = surge。
8. `golden` 抽查：`age_h ≤ 2` 的条目必为 true，>2h 必为 false；`comment_exposure == round(views*0.1)`。
9. views=null 的构造样本（或等真实数据）→ predicted/comment_exposure 为 null、S2=S4=0、接口不 500。

**API 与降级**

10. 数据站关掉 → `/wb-api/x-surge` 返回 502 `{"error","hint"}`（与 /x-hot 同行为）；
    数据站开着但 x_engagement.json 删掉 → 200 + `items: []` + hint 带 CLI 命令。
11. `?golden=1&min_followers=100000&markets=美国&range=24h&limit=10` 组合筛选结果单调正确；
    返回按 surge 降序、平分 views 降序。

**前端**

12. `python cli.py workbench serve --open` → 图文页左侧出现第 5 子页「蹭蹭流量」（带火箭图标与
    黄金窗口计数徽标）；在 资讯/视频/追踪 等页时左侧子菜单不串页（registerSubs 路由守卫回归）。
13. 筛选交互：黄金窗口/粉≥10万/市场 chips/24h-48h 全部即时重载；`stale` 黄条在
    `data_age_min > 90` 时出现（可临时改 meta 阈值验证）。
14. 「＋加入素材」→ toast + 按钮变「已加入 ✓」→ 切到「内容生成」素材池可见该条 →
    回「推荐信息」对应条目同显已加入（同 store id 三处同态）；刷新页面后状态保持（localStorage）。
15. 空态：未跑采集时子页显示空态卡 + CLI 提示，不白屏。
16. 缓存：bump `?v=` 后强刷/普通刷新均加载新版 JS/CSS（DevTools Network 无 0904c 旧请求）。

**回归**

17. 推荐信息子页右栏 X 热帖榜与 `/wb-api/x-hot` 行为零变化（xhot.py 未动）。
18. `python cli.py workbench status --json` 与 `python cli.py doctor` 全绿；`data/` 新增文件仅
    `x_engagement.json`（及其 .corrupt 留证文件，若触发）。

---

## 11. 后续演进（非本期，防 scope 蔓延只登记）

1. **自动评论/回复入口**：SoPilot 的"立即评论"我们对应为跳转原帖人工评论；真自动回复涉及平台风控
   与发布红线（对齐 `publish run --draft` 纪律），本期明确不做。
2. **predicted_views 回测校准**：快照文件里 72h 内的末段快照就是"实际终值"，积累两周后可离线回归 k 值（§5.4）。
3. **起爆推送**：surge ≥ 70 且 golden 的条目接 `automation.json` 通知桩（工作台调度器仍是留桩，届时一起做）。
4. **并入 xhot**（触发条件见 §2）：右栏换源 + 删 xhot.py，一个发布周期收尾。
5. **任务计划注册**：§9 第 7 步，若用户接受常驻采集再挂。

---

## 12. 附录：常量总表（调参只动这一处）

| 常量 | 值 | 位置 | 语义 |
|---|---|---|---|
| `RETENTION_S` | 72×3600 | x_surge.py | 快照保留窗 |
| `MIN_SNAPSHOT_INTERVAL` | 1200s | x_surge.py | 幂等窗（20min 内重采不追加） |
| `MAX_SNAPSHOTS_PER_POST` | 40 | x_surge.py | 单帖快照稀疏化上限 |
| `MAX_FILE_BYTES` | 5 MB | x_surge.py | 落盘硬护栏 |
| `DEFAULT_MAX_POSTS` | 150 | x_surge.py | 单轮采样上限（CLI 默认，硬顶 300） |
| `FX_WORKERS` / `FX_TIMEOUT_S` | 4 / 8 | x_surge.py | FxTwitter 并发与超时 |
| `ITEMS_LIMIT` | 24h→800, 48h→1600 | x_surge.py | 数据站 items 拉取上限 |
| `GOLDEN_WINDOW_H` | 2.0 | x_surge.py | 黄金窗口 |
| `EXPOSURE_RATE` | 0.10 | x_surge.py | 评论曝光 ≈ views×10% |
| `PREDICT_K` / `PREDICT_CAP` | 3.0 / ×4 | x_surge.py | 预测浏览量形状常数与封顶 |
| `STALE_MIN` | 90 | x_surge.py | meta.stale 阈值（分钟） |
| S1~S4 权重与档表 | §5.3 各表 | x_surge.py | 起爆概率构成 |

—— 以上。另一 agent 按本文 §9 顺序实现，验收以 §10 清单逐条打勾为准。
