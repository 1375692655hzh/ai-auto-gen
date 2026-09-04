# 工作台「蹭蹭流量」子页方案 —— X 热帖起爆榜 + 评论卡位闭环

> 文档性质：实施级方案，不含任何代码改动。审计基线为 2026-09-03 当前工作区，文中行号均指该时点的文件内容（实现时如有 ±几行漂移以符号名为准）。
> 目标读者：拿着本文档直接写代码的下一个 agent。所有事实已经过验证并标注出处，**不需要再验证**。
> 红线复述：workbench 对板块一(global-news-sources)只读；本功能自有数据只写 `data/workbench/x_engagement.json`；CLI 入口统一 `python cli.py workbench <子命令>`；前端永不直连数据站 8787 与外网（外呼只发生在服务端 CLI 进程）。

---

## 0. TL;DR

- 图文页(article)新增第 5 个子页**「蹭蹭流量」**（tab=`surge`，注册在「推荐信息」之后）。
- 数据闭环：CLI `python cli.py workbench refresh-x-surge --range 24h` 从数据站 8787 `/v1/items` 拉近窗 X 条目 → 提取 `(handle, status_id)` → 并发调 FxTwitter 单帖接口抓 likes/retweets/replies/views 四件套 → **每次采集追加一条时序快照**到 `data/workbench/x_engagement.json`（status_id 为键，保留 72h）。
- 展示闭环：新增只读接口 `GET /wb-api/x-surge`，用**可解释启发式公式**给每条帖子算「起爆概率 0~100」「预测总浏览量」「预计评论曝光（views×10%）」，发布 <2h 的帖子标注**黄金窗口**；列表按起爆概率排序。
- 动作闭环：每条提供「去评论 ↗」（x.com intent 回复深链，人工点击，无自动化发布）与「＋加入素材」（复用 WB.basket/basketIds 既有机制，把高价值帖送进素材池供内容生成蹭热点）。
- 与 `xhot.py` 的关系：**保留 xhot 不删**，但把它的"簇热度 dup_count"信号吸收为起爆公式的一个因子；xhot 继续充当推荐页右栏的零外呼兜底榜（详见 §4）。

---

## 1. 对标拆解：SoPilot「评论卡位」 → 我们的版本

### 1.1 SoPilot (sopilot.net/zh/hot-tweets) 产品结构（已验证，直接采信）

1. 监控一批 X 大 V 列表，周期性快照每条推文的 `likes / retweets / replies / views` 四件套；
2. 用「互动增速 / 粉丝基线」算出每条帖子的**起爆概率(%)**与**预测总浏览量**；
3. 列表按起爆概率排序，每条给出「现在去评论预计可获得 N 次曝光」（≈ 原帖 views×10%，黄金窗口 = 发布后 2h）；
4. 配「立即评论」动作入口。

### 1.2 我们的差异决策（实现时按此执行，不要自行加码）

| SoPilot 行为 | 我们的版本 | 理由 |
|---|---|---|
| 监控自建大V列表 | 直接复用数据站里已有的 X 池条目流（131 账号，板块一 twitter_kol_flash/views 已在持续入库） | 零新增抓取面；帖子的发现交给板块一，我们只补"互动时序"这一层 |
| 周期快照 | CLI 手动/任务计划触发 `refresh-x-surge`，同一帖子每次采集追加一条快照 | 本期不做常驻调度器（对齐"自动化任务调度留桩"的现状），幂等可重跑即可 |
| 起爆概率 | 可解释加权公式（§6），每条在 API 里带 `surge_parts` 构成明细（对齐 reco 的 `score_parts` 透明风格） | 工作台一贯原则：服务端规则透明、前端展示构成 |
| 「立即评论」代开回复框 | 行内「去评论 ↗」= `https://x.com/intent/tweet?in_reply_to=<status_id>` 深链，用户人工点击 | 红线：任何自动发布/自动互动都不进工作台；intent 链接只是快捷入口，零自动化风险 |
| 送素材 | 「＋加入素材」复用 WB.basket（localStorage），素材进图文页「内容生成」的素材池 | 与资讯页/推荐页同一跨页通道，无新增存储 |

**明确不做**（本期砍掉，留演进缝）：自动定时调度、多账号评论矩阵、评论后效果回收统计。

---

## 2. 现状审计（可复用资产与关键事实，全部已验证）

### 2.1 数据取数通道

- 数据站唯一取数口：`GET {base_url}/v1/items`，参数见 `global-news-sources/sources/serve.py:150-157`（markets/kinds/q/since/limit/cursor/dedup/display 等），返回 `{total, next_cursor, items:[...]}`（serve.py:179）。
- 服务端内部取数用 `workbench/server/proxy.py:71-93` 的 `fetch_json(path_qs)`（自动注入 `data/workbench/settings.json` 里存的 Bearer Key）；xhot.py 已示范用法（xhot.py:36-42，注意 `since` 含空格必须 `urllib.parse.urlencode`）。
- 条目 `id` 是 `md5(source_id|canon_url或text前缀)`（`global-news-sources/sources/store.py:236-238`），**不是 status_id**；status_id 必须从 `url` 里提取（§5.3）。
- X 池条目字段（`global-news-sources/fetchers/basic.py:439-448` 产出）：`time`（北京时间 `"%Y-%m-%d %H:%M"`）、`text`（`@handle: 正文`）、`source`（`X·<账号名>`）、`url`（`https://x.com/<handle>/status/<sid>` 或 fxtwitter 返回的 url）、`author_role`、`author_handle`、`markets`、`lang`。入库后 `store.put` 还会补 `item_type/sectors/sentiment/dup_count/positioning` 等（store.py:257-292）。

### 2.2 FxTwitter 单帖接口（已验证，直接采信）

```
GET https://api.fxtwitter.com/<handle>/status/<id>
→ 200 {"tweet": {"likes": 273, "retweets": 13, "replies": 54, "views": 180441,
                 "created_at": "Wed Sep 02 20:11:26 +0000 2026", ...}}
```

- 免登录、无 Key。实现时注意三点：①响应外层键是 `tweet`，缺失视为该帖失败；②`views` 实测可能缺失（§9.3）；③用 stdlib `urllib.request`（workbench 全家统一 urllib，proxy.py/app.py 皆是），带 `User-Agent` 与 `Accept: application/json`、`Accept-Encoding: identity`（urllib 不自动解压 gzip）。

### 2.3 workbench 后端既有模块（范式来源）

| 模块 | 复用点 | 位置 |
|---|---|---|
| `x_profile_enricher.py` | 批量外呼 + 每批容错 + 原子写缓存 + CLI `run_cli` + 退出码语义（失败返 3） | 全文件 171 行；`DATA_DIR/CACHE_FILE` 定义在 26-27 行；`load_cache` 40-48；`save_cache`(mkstemp+os.replace 原子写) 51-56；`run_cli` 142-170 |
| `xaccounts.py` | 读池 yaml（只读红线）、mtime 缓存、`load_accounts() → {handle_key: account}` | `POOL_FILE` 22 行；`load_accounts` 61-93；key 规范 `handle.lower().lstrip('@')` |
| `xhot.py` | 从数据站拉近窗 X 条目的完整姿势（since/urlencode/limit=300/dedup/display、author_handle 过滤、per-handle 限 2 条） | `_WINDOWS` 19 行；`hot()` 36-72；dup_count+粉丝量级热度公式 6-12 行注释 |
| `app.py` | 端点注册范式：import 追加在 21 行；`/wb-api/x-hot` 在 152-158 行（新端点紧随其后）；`proxy.UpstreamError` → JSONResponse 的错误翻译范式 | |
| `config.py` | `DATA_DIR` 17 行；原子写 `save` 50-57；`load_rows/save_rows` 85-98 | |
| `cli.py` | `workbench_cmd` 293-330（`sys.path.insert(0, str(WB))` 后 from server import ...）；workbench 子命令注册 527-542 | |

### 2.4 前端既有资产

- `workbench/web/js/pages/article.js`（726 行）：
  - 子页容器：`tab`（13 行）+ 每子页一个 `v-show` 块 + `registerSubs()`（72-91 行，**路由守卫在 73-74 行：`location.hash` 不以 `/article` 开头直接 return，不得破坏**）；`go(t)` 92 行；`mounted` 343-350；`unmounted` 清空 setSubs 351 行。
  - 素材篮：`basketIds`（24 行）、`addToPool(it)`（146-150 行，调 `WB.basket.add(it)` 后置 `basketIds[it.id]=true`）、`initBasketIds`（151-154 行）。
  - `WB.basket.add` 需要字段 `{id, time, source, text|title, url}`（`workbench/web/js/api.js:67-73`，text 截 200 字，重复 add 会 toast「该条已在素材篮」）。
  - X 热帖右栏既有实现：`loadXHot/toggleXhotMarket` 156-168 行、`fmtFol` 170-172 行（万格式化）、模板 458-470 行。
  - 已加载 `xAccounts`/`xProfiles`（178-181 行 `loadX()`），新子页可直接复用，不必重拉。
- `workbench/web/js/api.js`：`WB.api.get/post/put/del` 同源 `/wb-api` 客户端；`WB.toast`。
- `workbench/web/js/app.js`：`WB.shell.setSubs(list, activeId)` 契约（62-70 行，created 阶段就绪；`pickSub` 调 `onPick`）。
- 样式（`workbench/web/css/app.css`，397 行）：`.card` 117-119；`.badge`(+green/red/yellow/blue) 139-145；`.chip`(+on) 156-162；`.reco-cols/.reco-rail`（sticky 右栏）371-375；`.frow/.lab` 367-370；`.xhot-item/.xhot-top/.rank/.name/.xhot-fol/.xhot-text/.xhot-meta` 377-389；`.act-done`（已加入灰态）391；响应式断点 `@media (max-width:1100px)` 359-363 与 393-396。
- `workbench/web/index.html`：css 引用 7 行、6 个 script 54-60 行，**版本参数统一 `?v=0904c`**。

### 2.5 数据文件现状

- `data/workbench/x_profiles.json`：`{enriched_at, profiles: {handle: {bio, followers, verified, fetched_at}}}`，现有 131 个账号（2026-09-03 实测）。followers 是 grok 检索的**近似整数值**，用于粉丝基线足够。
- `data/workbench/` 下其余文件（settings/drafts/automation/tracked_accounts/x_profiles）与本功能互不干扰；**新增自有文件只有一个：`data/workbench/x_engagement.json`**。

---

## 3. 需求还原（子页要长什么样，一段话定稿）

用户打开 图文页 → 左侧子菜单点「蹭蹭流量」，看到一个按**起爆概率**排序的 X 帖子榜：

- 每行：排名、账号名(@handle)、粉丝数、**四件套**（赞/转/评/浏览）、**增速**（浏览/时）、**起爆概率徽章**（如 `起爆 86`）、**预计评论曝光**（"评论预计 ≈1.8万 曝光"）、发布时间/年龄；
- 发布 <2h 的行加绿色**黄金窗口**徽章；
- 顶部筛选：范围 chips（24h/48h）、市场 chips（池账号覆盖市场，同 xhot 交互）、开关 chips「黄金窗口」「粉丝≥10万」；
- 行动作：`去评论 ↗`（intent 深链）、`原文 ↗`、`＋加入素材 / 已加入 ✓`；
- 顶部 meta 行：数据年龄（"快照 12 分钟前"），FxTwitter 降级或数据过旧时给灰条提示 + CLI 提示。

---

## 4. 与 xhot.py 的关系（裁决：**保留 xhot，不删不并**）

二选一，本文档裁决为**保留**，理由：

1. **口径不同，用户价值不同**。xhot 热度 = `dup_count×3 + 粉丝量级档`（xhot.py:53），回答"哪些事件大家都在转"（簇热度，跨账号真传播信号）；surge 回答"哪条帖子**此刻**正在起爆、去评论最划算"。两个问题都真实存在，合并会丢掉"同事件簇"视角的独立呈现。
2. **降级面**。surge 依赖外呼 FxTwitter + 时序快照冷启动（首轮无增速）；xhot 零外呼、数据站一响就能出榜。FxTwitter 挂掉或刚装好还没跑过采集器时，xhot 是唯一可用的榜（§10 表行2/8）。
3. **前端契约稳定**。`/wb-api/x-hot` 已被推荐页右栏消费（article.js:156-163），保留可零回归。
4. **吸收其精华**。xhot 的 dup_count 信号以 `C = clamp(dup_count/5, 0, 1)` 进入起爆公式（§6.4），等于把 xhot 的簇热度"并入"了 surge 的打分内核——信号并了，模块不删。

**未来演进缝**（本期不做）：若 surge 稳定运行两周、快照覆盖率高，可把推荐页右栏 X 热帖卡的数据源切到 `/wb-api/x-surge?limit=8`，届时 xhot 退役为 FxTwitter 故障期的降级数据源（app.py 一处 if 分支）。本文档不实施这一步。

---

## 5. 数据模型（对应任务 A）：`data/workbench/x_engagement.json`

### 5.1 顶层 shape（version 字段留升级缝）

```json
{
  "version": 1,
  "updated_at": "2026-09-04 10:30:00",
  "last_round": {"ts": "2026-09-04 10:30:00", "range": "24h", "ok": 312, "fail": 9,
                 "skipped": 40, "degraded": "", "errors": ["...前5条错误摘要..."]},
  "statuses": {
    "2095243222734049338": {
      "handle": "deitaone",
      "item_id": "3f2a…md5(数据站条目id)",
      "url": "https://x.com/DeItaone/status/2095243222734049338",
      "time": "2026-09-03 20:11",
      "source": "X·Walter Bloomberg",
      "markets": ["美国"],
      "dup_count": 3,
      "text": "(display 交换后的正文, 截 300 字)",
      "series": [
        {"ts": "2026-09-04 09:58:03", "likes": 120, "retweets": 13, "replies": 54, "views": 180441},
        {"ts": "2026-09-04 10:28:11", "likes": 273, "retweets": 20, "replies": 61, "views": 198200}
      ]
    }
  }
}
```

要点：

1. **键 = status_id 字符串**（纯数字串，如 `"2095243222734049338"`）。同一帖跨源重复（dup）只留一个实体，`dup_count` 取窗口内各条目的最大值。
2. **`series` 每次采集追加一条** `{ts, likes, retweets, replies, views}`（ts 为本机时间 `"%Y-%m-%d %H:%M:%S"`；数值缺失的字段写 `null`，不造 0）。追加即幂等语义的一部分：同一 status 重复采集只追加不覆盖（受 §5.3 冷却约束）。
3. **条目元数据（handle/item_id/url/time/source/markets/dup_count/text）首次见到该 status 时从数据站条目固化**，之后不再回查数据站——这样 8788 出榜与「＋加入素材」完全不依赖数据站活着。
4. `item_id` 是数据站条目 id（md5 串），供「＋加入素材」与草稿 items 引用；缺失时该帖不可加入素材（§9.4 细节约束）。

### 5.2 保留窗口与文件大小控制（写死为模块常量）

| 常量 | 值 | 作用 |
|---|---|---|
| `RETENTION_H` | 72 | 每轮落盘前修剪：`series` 中 `ts` 早于 `now-72h` 的点删除；某 status 修剪后 `series` 为空 → **整个 status 实体删除** |
| `MAX_POINTS_PER_STATUS` | 96 | 单 status 最多保留 96 个快照点（30min 一轮 × 48h 也才 96），超出丢最旧 |
| `MAX_STATUSES` | 2000 | status 实体总数硬顶，超出按"最新快照 ts 最旧"淘汰 |
| `SERIALIZE_COMPACT` | true | 写盘用 `json.dump(..., ensure_ascii=False)` **不带 indent**（x_profiles 的 indent=1 是小文件待遇；本文件大，紧凑序列化省约一半体积） |

体量估算（写进注释）：48h 窗口内 131 账号产帖 ≈ 每天数百条；单轮上限 400（§7.4）；每快照点 ≈110 字节。上限场景 2000 status × 平均 20 点 ≈ 4~5MB 封顶，常态 <1MB，SQLite 级别无忧。**不要**为它上 SQLite——单文件原子替换已是本仓库范式（config.py:50-57）。

### 5.3 幂等与冷却

- `SNAP_COOLDOWN_S = 600`：同 status 距上一快照不足 10 分钟时**跳过外呼**（计入 `skipped`），保证"重复跑命令不产生重复快照、不白打 FxTwitter"。`--force` 可绕过冷却。
- 落盘时机：**每轮结束一次性读-改-写**（§7.5）。中途崩溃只丢当轮，旧文件完好。
- 并发写：CLI 与 serve 同时在跑时靠 `mkstemp+os.replace` 原子替换，最后写者胜；本机单人场景不做进程锁（刻意决策，注释说明）。

---

## 6. 采集器（对应任务 B）：`workbench/server/x_surge.py`（新建）

### 6.1 模块骨架（函数签名定稿，实现按此）

```python
"""X 热帖起爆榜: FxTwitter 互动四件套时序快照 + 起爆概率(v. SoPilot 评论卡位)。

数据流: 数据站 /v1/items(经 proxy) → (handle,status_id) → api.fxtwitter.com/<h>/status/<id>
        → data/workbench/x_engagement.json(series 追加, 72h 保留, 原子写)
纪律: 本模块只写 x_engagement.json; 外呼只发生在 CLI 进程, serve/前端只读。
CLI: python cli.py workbench refresh-x-surge [--range 24h|48h] [--force] [--limit N] [--json]
"""

DATA_FILE   = DATA_DIR / "x_engagement.json"   # DATA_DIR 复用 x_profile_enricher.py:26 的定义方式
API_BASE    = os.environ.get("X_SURGE_API_BASE", "https://api.fxtwitter.com")  # 测试注入选址
RETENTION_H = 72
MAX_POINTS_PER_STATUS = 96
MAX_STATUSES  = 2000
SNAP_COOLDOWN_S = 600
MAX_PER_ROUND  = 400
WORKERS, TIMEOUT_S, RETRY = 6, 10, 1
GOLDEN_WINDOW_H = 2
_URL_RE = re.compile(r"^https?://(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/(\d{5,})/?")

def load_data() -> dict            # 损坏容错: JSONDecodeError/缺键 → {"version":1,...空} (照抄 x_profile_enricher.load_cache 范式)
def save_data(d: dict) -> None     # 修剪(§5.2) + mkstemp + os.replace 原子写
def collect(range_: str, force: bool, limit: int) -> dict    # 主流程 §6.2~§6.5
def compute(rows_meta: list|None=None) -> dict               # 指标计算 §7 (API 调用)
def run_cli(args) -> int           # §6.6
```

### 6.2 第一步：拉近窗 X 条目（经 proxy，不直连 8787）

照抄 xhot.py:36-42 姿势，但**带 cursor 翻页**（131 账号 48h 可能超一页）：

```
qs = {"limit": 500, "dedup": 1, "display": 1, "since": now - range秒 的 "%Y-%m-%d %H:%M"}
若 range 的 markets 筛选存在则附 "markets": ",".join(...)   # CLI 本期不传 markets, 全量拉
最多翻 3 页: 用响应 next_cursor 拼 "cursor" 参数; 累计 items 上限 1500, 超出截断
异常: proxy.UpstreamError → print 提示 + 返回 exit 3 (数据站没起是运维问题, 不是崩溃)
```

- `display:1` 让 text 已是中文译文（serve.py:168-173 在数据站侧完成交换），存进快照元数据后页面直接可用；`text` 截 300 字。
- **只取有 `author_handle` 的条目**（xhot.py:47-49 同款过滤），非 X 条目从源头排除。

### 6.3 第二步：提取 (handle, status_id) 与候选去重

- 对每条的 `url` 跑 `_URL_RE`；不匹配的（转推链/短链/非状态页）跳过并计数。
- 规范化：`handle = match.group(1).lower()`，`status_id = match.group(2)`。
- **status_id 去重**：同窗口多条目同一 status（跨源 dup）→ 只留一个候选，`dup_count` 取 `max(条目 dup_count, 1)`，`item_id` 取**首次遇到**的那条（哪个 md5 都合法，素材引用只需稳定）。
- 若该 status 已在 `x_engagement.json` 且元数据齐全 → 不覆盖已有元数据（time/source 等以首见为准，避免翻页顺序扰动）；仅更新 `dup_count = max(旧, 新)`。

### 6.4 第三步：FxTwitter 批量采集（并发/限速/容错）

- **单轮上限**：候选按 `(age_h 升序, 数据站 url 缺失者沉底)` 排序后截 `MAX_PER_ROUND=400`——新帖优先（黄金窗口也优先），防冷启动首轮把 2000 条旧帖全打一遍。
- **冷却过滤**：候选中距上一快照 `< SNAP_COOLDOWN_S` 且未 `--force` 的 → 计入 `skipped`，不发请求。
- **并发**：`concurrent.futures.ThreadPoolExecutor(max_workers=6)`；每请求 `timeout=10s`。
- **重试**：网络异常/HTTP 5xx 重试 1 次（间隔 0.5s）；4xx 不重试。
- **限速熔断**：任一请求收到 **429** → 立即取消剩余任务（`executor.shutdown(cancel_futures=True)` 思路：主循环置 stop 标记），本轮标记 `degraded="fxtwitter_429"`，已成功的快照照常入库。
- **单帖解析**（全部防御式）：

```python
def _fetch_one(handle, status_id) -> dict | None:
    # GET f"{API_BASE}/{handle}/status/{status_id}"  (headers: UA / Accept / Accept-Encoding: identity)
    # d.get("tweet") 缺失或非 dict → None; 数字字段 int() 失败 → None
    # likes/retweets/replies/views 四键: 缺失写 None(不造 0), views 缺失是已知情况(§9.3)
```

- 单帖失败只计 `{status_id: "错误摘要≤60字"}`，**绝不**让整轮失败；`errors` 只保留前 5 条摘要进文件。
- 全部候选都失败 → 不改写文件（保留旧快照），CLI 返回 3。

### 6.5 第四步：落盘（每轮一次，原子）

1. `load_data()` → 对每个成功 status：`series.append(快照点)` → 按 §5.2 修剪（72h 点、96 点上限、空 series 删实体、超 MAX_STATUSES 淘汰）。
2. 更新 `updated_at` 与 `last_round = {ts, range, ok, fail, skipped, degraded, errors}`。
3. `save_data()` 原子替换。
4. 返回轮报告 dict（§6.6 打印）。

### 6.6 CLI：`python cli.py workbench refresh-x-surge`

- cli.py 改动两处：
  1. 子命令注册：在 `pw_e`（enrich-x-profiles，cli.py:536-542）之后照抄模式新增 `pw_x = wsub.add_parser("refresh-x-surge", help="X热帖互动快照采集(FxTwitter → data/workbench/x_engagement.json)")`，参数 `--range {24h,48h}` 默认 24h、`--force`（绕过 10min 冷却）、`--limit`（覆盖单轮 400 上限，调试用）、`--json`。
  2. `workbench_cmd`（cli.py:293）里加分支：`sys.path.insert(0, str(WB)); from server import x_surge; return x_surge.run_cli(args)`。
- 退出码（对齐 AGENTS.md 全局语义）：`0` 至少采集到一个新快照或全部 skipped；`3` 业务失败（数据站不可达 / 全部候选失败）；`4` 未配置数据源 base_url（proxy 抛"未配置数据源地址"时捕获转 4）。
- `--json` 输出：`{"range":"24h","window_items":861,"candidates":412,"fetched":312,"failed":9,"skipped":40,"degraded":"","elapsed_s":97,"file":"data/workbench/x_engagement.json"}`；非 json 模式打人话两行（采集 N/失败 M/跳过 K，数据年龄 X 分钟）。

---

## 7. 指标计算（对应任务 C）：全部公式与常数

以下计算全部发生在**读取侧**（`/wb-api/x-surge` 调 `x_surge.compute()`），采集器只存原始四件套——公式调参不用重跑采集。

### 7.1 记号

- `now` = 当前本机时间；`t0` = 帖子 `time`（数据站北京时间 `"YYYY-MM-DD HH:MM"`；缺失→`age_h=null`，见 §10 表行7）。
- `age_h = (now - t0) / 3600`，保留 1 位小数。
- `series` 按 ts 升序；最新点 `b=(t_b, v_b, l_b, r_b, p_b)`，向前的相邻点 `a`。

### 7.2 增速（有基线 = series ≥ 2 点）

- 从最新点向前找**第一对**满足 `Δt = t_b - t_a ≥ 300s` 的相邻点（防两次快照贴太近导致除零/抖动）；
- `views_per_h = max(0, v_b - v_a) / (Δt/3600)`（views 理论单调不降，负差按 0 截断——fxtwitter 偶发抖动）；`likes_per_h` 同式，不截负（点赞也可能被撤）。
- 任一输入值为 `null`（views 缺失）→ 该项增速为 `null`，不造假数。
- series 只有 1 点 → **无基线**：`growth=null`，`surge=null`（§9.1）。

### 7.3 增速分位（量纲消除，大V小V同台）

- `P_v` = `views_per_h` 在**本次响应集合中所有有基线帖子**里的分位（`P = #(
  值 < x) / (N-1)`，`N≤1` 时取 0.5），0~1；`P_l` 对 `likes_per_h` 同式。
- 分位数在 `compute()` 内一次遍历算全量（N ≤ 2000，性能无虞），**不落盘**。

### 7.4 起爆概率 surge（0~100，可解释线性加权）

```
R      = views_per_h / max(followers, 1)            # 粉丝基线比: 每小时新增浏览 ÷ 粉丝数
R_norm = clamp( log10(1 + 100·R) / 2 , 0, 1 )       # 对数映射, 见下表
D      = 0.5 ** (age_h / 3)                          # 半衰期 3h 的时长衰减: 0h→1.00, 2h→0.63, 6h→0.25, 12h→0.06
C      = clamp( dup_count / 5 , 0, 1 )               # 簇热度(吸收 xhot 信号): 同事件被 5+ 源报 → 满分
surge  = round( 100 × ( 0.40·P_v + 0.15·P_l + 0.20·R_norm + 0.15·D + 0.10·C ) )
```

- `R_norm` 映射自检表（写进代码注释，方便验收）：R=0.001 →0.02；R=0.01 →0.15；R=0.1 →0.52；R=0.5 →0.85；R≥1 →1.00。含义：每小时新增浏览达粉丝数一半 ≈ 全网级起爆。
- 权重表（合计 1.00，写死为模块常量 `WEIGHTS`，调参只改这一处）：

| 因子 | 权重 | 回答的问题 |
|---|---|---|
| P_v 浏览增速分位 | 0.40 | 这条帖子**此刻**涨得比同窗其他帖子快吗（主信号） |
| P_l 点赞增速分位 | 0.15 | 涨的量有没有人真互动（防纯曝光虚高） |
| R_norm 粉丝基线比 | 0.20 | 相对账号体量是不是超常发挥（小V黑马拉高） |
| D 时长衰减 | 0.15 | 现在去蹭还来得及吗（越新越值） |
| C 簇热度 | 0.10 | 事件本身够不够大（xhot 精华并入处） |

- 无基线（surge=null）、followers 未知（R_norm 取中性常数 0.30，见 §10 表行 6）等降级在 §10。
- 每条响应带 `surge_parts: [["浏览增速分位", 31.2], ["点赞增速分位", 11.7], ...]`（加权分，四舍五入 1 位，合计=surge），前端 title 悬浮展示——对齐 reco `score_parts` 的透明风格（article.js:135-137 消费范式）。

### 7.5 预测总浏览量与预计评论曝光

```
T_fut           = clamp(6 − age_h, 0.5, 6)          # 预测时长预算: 给 6h 内的自然衰减预算, 至少 0.5h
views_pred      = round( v_b + views_per_h × T_fut )
views_pred      = min(views_pred, 5 × max(v_b, 1))  # 封顶 5 倍: 增速线性外推天然高估, 经验截断
comment_exposure= round( v_b × 0.10 )                # SoPilot 口径: 评论区引流≈原帖浏览 10%
golden          = (age_h is not None) and age_h ≤ 2  # 黄金窗口 = 发布后 2h
```

- 常数依据写进注释：10% 为 SoPilot 公开口径的评论区点击转化经验值；黄金窗 2h 同 SoPilot；预测封顶 5× 是防止 30 分钟双快照的瞬时高增速被外推 6 小时后产出离谱数。
- `comment_exposure` 的展示语义：**始终展示数值**（≈N 次曝光），非黄金窗口的行加灰字后缀「已过黄金窗口」不给隐藏（§7.6 排序外的展示语义，边界细则见 §10 表行4）。

### 7.6 排序

`surge` 降序，`null`（无基线）沉底按 `views` 降序；同分按 `views` 降序。

### 7.7 手算示例（写进文档供验收对数）

帖子 06:20 发布，now=07:50 → `age_h=1.5`；快照 07:20 views=100000、07:50 views=118000 → Δt=0.5h，`views_per_h=36000`；`likes_per_h=61.5`；`followers=200000`；`dup_count=2`；本窗分位 `P_v=0.92`、`P_l=0.88`。

```
R=36000/200000=0.18 → R_norm=log10(1+18)/2=0.639
D=0.5^(1.5/3)=0.707
C=clamp(2/5,0,1)=0.4
surge=round(100×(0.40×0.92 + 0.15×0.88 + 0.20×0.639 + 0.15×0.707 + 0.10×0.4))
     =round(100×0.774)=77
T_fut=clamp(6−1.5,0.5,6)=4.5 → views_pred=118000+36000×4.5=280000 (≤5×118000 ✓)
comment_exposure=11800; golden=true(1.5≤2)
surge_parts≈[["浏览增速分位",36.8],["点赞增速分位",13.2],["粉丝基线比",12.8],["时长衰减",10.6],["簇热度",4.0]]
```

---

## 8. API（对应任务 D）：`GET /wb-api/x-surge`

### 8.1 端点注册

`workbench/server/app.py`：21 行 import 追加 `x_surge`；在 `/wb-api/x-hot`（152-158 行）之后照抄该块结构新增：

```python
# ── 图文页: 蹭蹭流量榜(真互动时序 → 起爆概率, 数据来自 CLI refresh-x-surge 落盘) ──
@app.get("/wb-api/x-surge")
def x_surge_list(range: str = "24h", markets: str = "", golden: int = 0,
                 min_followers: int = 0, limit: int = 50):
    try:
        return x_surge.compute(range_=range, markets=markets,
                               golden=bool(golden), min_followers=min_followers, limit=limit)
    except proxy.UpstreamError as e:              # compute 不触外响, 此 except 只是范式对齐
        return JSONResponse({"error": str(e)}, status_code=e.code or 502)
```

**端点只读 `x_engagement.json`，绝不触发外呼**（外呼只在 CLI；页面刷新不能隐式打 FxTwitter——注释里写明）。文件读取加 mtime 缓存（照抄 xaccounts.py:27,62-68 范式）。

### 8.2 查询参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `range` | `24h` | `24h`/`48h`，按帖子 `time` 过滤 |
| `markets` | 空 | csv，与帖子 markets 求交集（空=全部） |
| `golden` | `0` | `1` 只看黄金窗口（age_h≤2 且 age_h 已知） |
| `min_followers` | `0` | 粉丝数下限（如 100000；followers=0/未知的行被此筛掉） |
| `limit` | `50` | 排序截断 |

### 8.3 响应 shape（字段全集，前端按此消费）

```json
{
  "items": [
    {
      "status_id": "2095243222734049338",
      "id": "3f2a…",                          // 数据站条目 id, 「＋加入素材」与 basketIds 的键
      "handle": "deitaone",
      "name": "Walter Bloomberg",             // source 去掉 "X·" 前缀; 兜底 "@"+handle
      "source": "X·Walter Bloomberg",         // 原样, 供 WB.basket.add
      "followers": 3910000,
      "verified": false,
      "time": "2026-09-03 20:11",
      "age_h": 1.5,                           // null=时间缺失
      "url": "https://x.com/DeItaone/status/2095243222734049338",
      "reply_url": "https://x.com/intent/tweet?in_reply_to=2095243222734049338",
      "text": "…(≤300字)",
      "markets": ["美国"],
      "engagement": {"likes": 273, "retweets": 13, "replies": 54, "views": 180441},
      "engagement_at": "2026-09-04 10:28:11", // 最新快照 ts
      "snapshot_n": 6,                        // 已积累快照点数(前端可显示"基线 N 点")
      "growth": {"views_per_h": 36000.0, "likes_per_h": 61.5, "window_min": 30,
                 "has_baseline": true},        // null=无基线
      "percentiles": {"views": 0.92, "likes": 0.88},
      "surge": 77,                            // 0~100 或 null(无基线)
      "surge_parts": [["浏览增速分位", 36.8], ["点赞增速分位", 13.2],
                       ["粉丝基线比", 12.8], ["时长衰减", 10.6], ["簇热度", 4.0]],
      "views_pred": 280000,
      "comment_exposure": 11800,
      "golden": true,
      "dup_count": 3,
      "in_pool": true                         // handle 是否在 xaccounts 池内(池外标记用)
    }
  ],
  "total": 37,                                 // 过滤后总数(截断前)
  "range": "24h",
  "rule": "surge=100×(0.40·浏览增速分位+0.15·点赞增速分位+0.20·粉丝基线比+0.15·时长衰减+0.10·簇热度); 评论曝光≈views×10%; 黄金窗口=发布≤2h",
  "meta": {
    "collected_at": "2026-09-04 10:30:00",
    "data_age_min": 12,                        // now-updated_at; null=从未采集
    "degraded": "",                            // 末轮降级标记("fxtwitter_429"等)
    "last_round": {"ok": 312, "fail": 9, "skipped": 40, "range": "24h"},
    "statuses_tracked": 486,
    "golden_n": 9                              // 黄金窗口命中数(供子菜单计数与空态文案)
  }
}
```

- 错误：文件不存在/从未采集 → **200 + `items:[]` + `meta.data_age_min:null`**（不是 404——"还没跑过采集"是正常初态，前端按空态引导）；`range` 非法 → 400 `{"error": "range 仅支持 24h|48h"}`。

---

## 9. 前端子页（对应任务 E）：article.js 加「蹭蹭流量」

以下改动全部在 `workbench/web/js/pages/article.js`，不新建 JS 文件（该文件就是图文页容器，四子页变五子页）。

### 9.1 子页注册（registerSubs，72-91 行）

- `setSubs` 数组在 `reco` 之后插入第 2 项（素材发现类聚拢在一起）：

```js
{ id: "surge", title: "蹭蹭流量", cnt: this.surgeMeta.golden_n || "",
  icon: I('<path d="M4.5 16.5 3 21l4.5-1.5"/><path d="M14 4c3-1.5 6-1 7 0 1 1 1.5 4 0 7l-6 6-5-5Z"/><path d="M9 12l3 3"/>' ),
  onPick: () => { this.tab = "surge"; } },
```

（火箭形 icon，若实现者画的路径不好看，可用 lucide `rocket` 的 path，形态接近即可；**路由守卫 73-74 行原样保留**。）
- `cnt` 用黄金窗口命中数（页面价值钩子），无命中回退空串。
- `mounted`（343 行）追加 `this.loadSurge();`；`loadSurge` 末尾照 `loadReco` 范式回调 `this.registerSubs()` 刷新计数。

### 9.2 data 新增状态（data() 里，`xhot` 状态附近 26 行后）

```js
/* ── 蹭蹭流量 ── */
surgeRange: "24h", surgeMarkets: [], surgeGoldenOnly: false, surgeBigOnly: false,
surgeItems: [], surgeTotal: 0, surgeRule: "", surgeMeta: {},
surgeLoading: false, surgeErr: "",
```

（`xAccounts/xProfiles` 复用既有 `loadX()` 产物，不重复拉。）

### 9.3 方法（新增，放 `loadXHot` 一组附近）

```js
async loadSurge() {
  this.surgeLoading = true; this.surgeErr = "";
  try {
    const p = new URLSearchParams({ range: this.surgeRange, golden: this.surgeGoldenOnly ? "1" : "0",
                                    min_followers: this.surgeBigOnly ? "100000" : "0" });
    if (this.surgeMarkets.length) p.set("markets", this.surgeMarkets.join(","));
    p.set("limit", "50");
    const d = await WB.api.get("/x-surge?" + p.toString());
    this.surgeItems = d.items; this.surgeTotal = d.total; this.surgeRule = d.rule; this.surgeMeta = d.meta || {};
  } catch (e) { this.surgeErr = e.error || "蹭蹭流量接口不可用"; this.surgeItems = []; }
  this.surgeLoading = false;
  this.registerSubs();
},
toggleSurgeMarket(m) { /* 同 toggleXhotMarket: splice/push 后 loadSurge() */ },
addToPoolSurge(it) { WB.basket.add(it); this.basketIds[it.id] = true; },   // 不跳页, 复用 basketIds 态
fmtNum(n) {  // 浏览/曝光万格式化: <1万 原样, ≥1万 "18.0万"
  return n == null ? "—" : n >= 1e4 ? (n / 1e4).toFixed(1).replace(/\.0$/, "") + "万" : String(n);
},
fmtRate(h) { return h == null ? "—" : this.fmtNum(Math.round(h)) + "/时"; },
surgeParts(it) { return (it.surge_parts || []).map((p) => p[0] + " +" + p[1]).join(" · "); },
surgeAgeText(it) { /* 复用 ageText 思路: "刚刚/N 小时前/N 天前"; null → "时间未知" */ },
dataAgeText() {  // meta.data_age_min → "快照 12 分钟前" / "快照 3.2 小时前" / null → "尚未采集"
},
```

market chips 数据源：直接复用 computed `xMarketChips`（article.js:64-68，池账号覆盖市场，与右栏热帖同口径）。

### 9.4 模板（新增一个 v-show 块，放在子页1 `reco` 块 356-473 行之后、子页2 `gen` 之前）

结构定稿（对齐现有 `.card/.frow/.chip/.badge/.xhot-item` 体系，每行字段排布如下）：

```
<div v-show="tab==='surge'">
  ┌ 工具栏 .feed-toolbar
  │   select 范围(24h/48h, v-model=surgeRange @change=loadSurge)
  │   chip「黄金窗口」:class={on:surgeGoldenOnly} @click 翻转+loadSurge
  │   chip「粉丝≥10万」:class={on:surgeBigOnly}  @click 翻转+loadSurge
  │   <span style="flex:1"> + button 刷新(@click="loadSurge")
  ├ 市场 chips 行 .card .frow:  v-for xMarketChips, 交互同 toggleXhotMarket
  ├ meta 行 .muted:  {{ dataAgeText() }} · 共 {{ surgeTotal }} 条 · 黄金窗口 {{ surgeMeta.golden_n || 0 }} 条
  │   [degraded 或 data_age_min>90] 灰条: "互动数据降级/过期 — 请跑 python cli.py workbench refresh-x-surge"
  ├ surgeErr → .err-box / 空态 .empty:
  │   从未采集(data_age_min===null): "首次使用 — 先运行 python cli.py workbench refresh-x-surge --range 24h 采集互动基线"
  │   采集过但空: "窗口内暂无起爆帖 — 放宽范围或筛选"
  └ 列表 .card:  v-for="(s,i) in surgeItems" :key="s.status_id" class="surge-item"
      行1 .surge-top:   rank{{i+1}} · name · @handle · badge blue「起爆 {{s.surge}}」(title=surgeParts)
                        · badge green「黄金窗口」(v-if golden) · 粉 {{fmtFol(s.followers)}}
                        · span.muted float:right {{surgeAgeText(s)}}前
      行2 a.surge-text:  s.text  (3行 clamp, href=s.url, 复用 .xhot-text 交互)
      行3 .surge-metrics: 赞 {{s.engagement.likes}} · 转 {{s.engagement.retweets}}
                        · 评 {{s.engagement.replies}} · 浏 {{fmtNum(s.engagement.views)}}
                        · 增速 {{fmtRate(s.growth?.views_per_h)}} · 预测浏览 {{fmtNum(s.views_pred)}}
      行4 .surge-expose:  「评论预计 ≈{{fmtNum(s.comment_exposure)}} 次曝光」
                        (golden 时 .surge-golden 高亮; 非 golden 后缀灰字「已过黄金窗口」)
                        · 无基线时整行后缀灰字「基线积累中(快照{{s.snapshot_n}}点), 暂无增速与起爆分」
      行5 .news-actions:  a 去评论 ↗(s.reply_url) · a 原文 ↗(s.url)
                        · basketIds[s.id] ? span.act-done 已加入 ✓ : span.act ＋加入素材(@click=addToPoolSurge(s))
                        · s.in_pool===false → badge「池外」
</div>
```

细节约束：

- **筛选即时性**：黄金窗口/粉丝≥10万/市场/范围统一走服务端参数 + `loadSurge()` 重拉（本地文件计算毫秒级，与 loadReco 交互一致性优先）。
- 「＋加入素材」传给 `WB.basket.add(it)` 的对象必须含 `{id, time, source, text, url}`——API 已按此供给（§8.3）；`basketIds` 判定用 `it.id`（数据站条目 id），与推荐页素材同键，素材池/草稿 items 全链路一致。
- `item_id` 缺失的行（`!s.id`）：不渲染加入按钮，改渲染灰字「未入库」（title 提示"该帖不在数据站当前窗口, 无法进素材池"）。
- 可选键安全：模板里所有可能缺的字段（growth/surge/views_pred/comment_exposure）都按 §9.3 的 fmt 兜底显示「—」，Vue 模板不要用 `?.` 以外的花哨语法（项目 Vue3 全局构建，`?.` 可用，article.js 既有代码已这么写）。

### 9.5 新增 CSS（workbench/web/css/app.css）

在 `.xhot-*` 区块（377-389 行）之后、`.act-done`（391 行）之前插入，全部用既有 `var(--*)` 变量，不引入硬编码主题色：

```css
/* ── 蹭蹭流量(子页2): 起爆榜条目, 布局承袭 .xhot-item 放宽为整页行 ── */
.surge-item { padding: 10px 0; border-bottom: 1px solid var(--border); }
.surge-item:last-of-type { border-bottom: none; }
.surge-top { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; flex-wrap: wrap; }
.surge-top .rank { font-family: var(--mono); font-size: 12px; color: var(--accent); width: 20px; flex: none; }
.surge-top .name { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden;
                   text-overflow: ellipsis; min-width: 0; }
.surge-top .who { font-size: 11px; color: var(--text-mute); white-space: nowrap; }
.surge-text { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
              overflow: hidden; font-size: 13px; line-height: 1.55; color: var(--text);
              text-decoration: none; }
.surge-text:hover { color: var(--accent); }
.surge-metrics { font-size: 12px; margin-top: 5px; color: var(--text-dim);
                 font-variant-numeric: tabular-nums; }   /* 数字等宽, 四件套纵向对齐 */
.surge-expose { font-size: 12px; margin-top: 3px; }
.surge-golden { color: var(--green); font-weight: 600; }
.surge-stale { font-size: 12px; padding: 6px var(--s4); border: 1px dashed var(--yellow);
               border-radius: var(--r-pill, 8px); color: var(--yellow); margin: 8px 0; }
```

- 既有可复用样式**不重复定义**：`.badge.green`（黄金窗口徽章）、`.badge.blue`（起爆概率）、`.chip.on`（筛选开关）、`.feed-toolbar`、`.frow/.lab`、`.err-box/.empty`、`.news-actions` 的 `a/.act/.act-done`、`fmtFol` 用的 `.xhot-fol` 视觉可直接拿 `.muted`。
- 响应式：本子页是单列列表，无需新增断点；确认 359-363 行的 1100px 断点不影响即可（不影响）。

### 9.6 index.html 版本号 bump（防新旧混载，仓库既有纪律）

- `workbench/web/index.html` 第 7 行（css）与 54-60 行（6 个 script）的 `?v=0904c` **一次性全部** bump 为 `?v=0905a`（日期+字母序惯例：0905=9月5日实施窗口，a=当日第 1 版；实施日不同则顺延字母）。
- 规则：**只改 article.js/app.css 也要全量 bump**——app.js 的 no-cache 中间件只保证不缓存 HTML，静态资源的失效完全靠这个查询串，漏一个 script 就会出"页面半新半旧"事故（index.html 内注释已警示）。

---

## 10. 边界与降级（对应任务 F，逐条给行为定稿）

| # | 场景 | 行为定稿 |
|---|---|---|
| 1 | **首轮无基线**（某 status series 只有 1 点） | 四件套正常显示绝对量；`growth=null` → 增速显示「—」；`surge=null` → 不渲染起爆徽章，改灰字「基线积累中(快照N点)」；排序沉底按 views 降序（§7.6）。榜顶 meta 显示"基线积累中 N/M 条" |
| 2 | **FxTwitter 429/挂了** | 采集侧：429 立即熔断本轮、已得快照照常入库、`degraded="fxtwitter_429"`；全部失败不改文件返回 3。展示侧：API 回 `meta.degraded` → 页面 `.surge-stale` 灰条「互动数据降级(上游限流)，榜单按旧快照计算」；**旧快照永不删除**，榜单继续可用，只是数值变陈旧 |
| 3 | **数据年龄过大**（data_age_min > 90min） | 页面灰条「快照 X 小时前 —— 请跑 `python cli.py workbench refresh-x-surge`」（API 侧只给 data_age_min，阈值判断在前端，方便调） |
| 4 | **views 字段缺失** | 快照点 views 存 `null`（不造 0）；views_per_h=null→增速「—」；P_v 不参与（surge 用剩余因子按原权重直接计算并 clamp——刻意**不重配**权重：重配会让缺 views 的帖子系统性虚高）；views_pred=null→「—」；comment_exposure=null→「—」。**不做任何代理估算**（如按点赞倒推浏览）——缺数据就显示缺数据 |
| 5 | **status_id 去重** | 提取层：正则捕获纯数字串；同窗口多条目同 status 合并（§6.3）；采集层：冷却期跳过；存储层：键唯一，series 追加前不查重（键+冷却已保证） |
| 6 | **非池账号混入** | 数据站条目本身都来自 X 池源，但 local 池/历史数据可能出现 xaccounts 里查不到的 handle：followers 从 profiles 缓存取不到 → 0 → R_norm 取中性常数 0.30（不因档案缺失打压或吹爆）；`in_pool=false` → 行内「池外」badge；「仅看粉丝≥10万」会把它们筛掉（followers=0 < 10万，行为正确） |
| 7 | **时间缺失/时区** | 数据站 `time` 是北京时间、工作台采集器也跑本机（同钟），`age_h` 直接本地时间相减；`time` 缺失 → `age_h=null` → golden=false、D=0.25（保守中低值）、显示「时间未知」。**注释警示：部署到非 CST 时区机器需先统一时区，否则 age/黄金窗全错** |
| 8 | **数据站 8787 没起** | 采集器：proxy.UpstreamError → exit 3 + 人话提示（照 cli.py status 328 行的提示话术）；展示侧不受影响（快照自含元数据，页面照常出榜，只是没有新帖进来） |
| 9 | **x_engagement.json 损坏/被手删** | load_data 容错当空缓存，页面显示「尚未采集」空态；重跑采集器即重建（自愈，无需人工修文件） |
| 10 | **item_id 缺失**（快照有、但该帖已滚出数据站窗口且当时没固化到）——由 §6.2 首见固化设计保证不出现；若历史脏数据真出现 | 行内不渲染「＋加入素材」，改灰字「未入库」（§9.4 细节约束） |
| 11 | **转推/他人线程帖** | 板块一入库侧已过滤（basic.py:422-424 只收本人帖），本模块不再判；url 正则不匹配的奇怪链接静默跳过计数 |
| 12 | **并发重跑** | 两个 CLI 同时跑：原子替换最后写者胜，最坏丢一轮增量；可接受，注释说明不做文件锁 |

---

## 11. 落地步骤清单（对应任务 G，文件级，按此顺序做）

1. **新建 `workbench/server/x_surge.py`**（全部新逻辑都在这一个文件）：
   常量区（§5.2/§6.1/§7.4 全部常数+权重）→ `load_data/save_data` → `_fetch_items`(proxy 拉取+翻页) → `_extract_candidates`(正则/去重/冷却) → `_fetch_one` + `_collect_round`(线程池/熔断/轮报告) → `collect(range_, force, limit)` → `compute(range_, markets, golden, min_followers, limit)`(指标+排序+shape) → `run_cli(args)`。
   文件头 docstring 照 §6.1 模板写清纪律。
2. **改 `workbench/server/app.py`**：21 行 import 追加 `x_surge`；152-158 行 x-hot 块后新增 `/wb-api/x-surge`（§8.1）。
3. **改 `cli.py`**：527-542 行 workbench 子命令区新增 `refresh-x-surge` 注册（§6.6）；`workbench_cmd`（293 行）加分发分支。
4. **改 `workbench/web/js/pages/article.js`**：data（§9.2）→ computed（无需新增，复用 xMarketChips）→ methods（§9.3）→ registerSubs 插 surge 项（§9.1）→ mounted 追加 loadSurge → 模板插入子页块（§9.4，位置：reco 块 473 行 `</div>` 之后）。
5. **改 `workbench/web/css/app.css`**：377-391 行区间后插入 §9.5 样式。
6. **改 `workbench/web/index.html`**：全量 bump `?v=0905a`（§9.6）。
7. **不改**：global-news-sources/**（只读红线）、proxy.py、config.py、xhot.py、xaccounts.py、x_profile_enricher.py、api.js、app.js。
8. （可选，不阻塞验收）`README.md`/AGENTS.md 命令表加一行 `refresh-x-surge`。

## 12. 验证清单（对应任务 G，逐条可执行）

前置：数据站在跑（`python cli.py sources serve` 或任务计划已刷新）。

```bash
# 1. 编译与导入
py -3.11 -m py_compile workbench/server/x_surge.py
py -3.11 -c "import sys; sys.path.insert(0,'workbench'); from server import x_surge; print('ok')"

# 2. 首轮采集(冷启动): 观察 --json 报告 ok>0, fail 可有; x_engagement.json 生成且 series 每帖 1 点
py -3.11 cli.py workbench refresh-x-surge --range 24h --json

# 3. 幂等重跑: 立即再跑一次 → fetched=0, skipped≈上轮 ok(SNAP_COOLDOWN 生效), 文件 mtime 可变但快照点数不变
py -3.11 cli.py workbench refresh-x-surge --range 24h

# 4. 二轮基线: 等 ≥10 分钟(或临时调小 SNAP_COOLDOWN_S 验完改回)再跑 → 老帖 series=2 点
#    验证增速: py -3.11 -c 手算任一 status 的 views_per_h 与 API 输出一致(对 §7.7 示例对数)

# 5. API 形状: serve 起后逐项断言
curl "http://127.0.0.1:8788/wb-api/x-surge?range=24h&limit=5"
#    items[].必含 §8.3 全字段; surge∈0..100 或 null; golden 且 age_h≤2; reply_url 含 in_reply_to
curl "http://127.0.0.1:8788/wb-api/x-surge?golden=1&min_followers=100000"
curl "http://127.0.0.1:8788/wb-api/x-surge?range=7d"        # → 400
#    停掉数据站再调 API → 仍 200 出榜(快照自含元数据, 验边界8)

# 6. 降级注入: X_SURGE_API_BASE=http://127.0.0.1:9 env 环境跑采集 → 全 fail 不改文件、exit 3;
#    手动把 last_round.degraded 写成 "fxtwitter_429" 验前端灰条(或临时改代码注入)

# 7. 页面: python cli.py workbench serve --open
#    ①左侧子菜单出现「蹭蹭流量」且 icon/计数正常, reco/gen/pub/auto 四旧子页不回归
#    ②筛选三开关(黄金窗口/粉丝≥10万/市场chip)各自生效且组合生效
#    ③「＋加入素材」→ 按钮变「已加入 ✓」→ 切「内容生成」素材池可见该条 → 刷新页面 basketIds 态保持
#    ④「去评论 ↗」打开 x.com intent 回复框(人工登录态), 「原文 ↗」打开原帖
#    ⑤无基线行: 增速「—」、无起爆徽章、灰字基线积累中; 首次使用空态文案正确(删 x_engagement.json 后刷新)

# 8. 静态资源: 硬刷新(CTRL+F5)无新旧混载; index.html 6 个 script + css 版本号全部 =0905a

# 9. 红线自查: git status 确认改动仅 §11 清单 5 个文件(+可选文档); data/workbench/ 只有 x_engagement.json 新增
```

验收口径：1/2/3/5/7/8/9 全绿即通过；4 依赖 10 分钟等待可放宽为"调小冷却验证后复原"；6 至少验证"全 fail 不写文件 + exit 3"。

---

## 13. 常数总表（实现时集中放文件头，调参只动这里）

| 常量 | 值 | 出处 |
|---|---|---|
| RETENTION_H / MAX_POINTS_PER_STATUS / MAX_STATUSES | 72 / 96 / 2000 | §5.2 |
| SNAP_COOLDOWN_S / MAX_PER_ROUND / WORKERS / TIMEOUT_S / RETRY | 600 / 400 / 6 / 10 / 1 | §6.4 |
| GOLDEN_WINDOW_H | 2 | §7.5 |
| WEIGHTS (P_v, P_l, R_norm, D, C) | 0.40, 0.15, 0.20, 0.15, 0.10 | §7.4 |
| D 半衰期 / R_norm 映射 / C 归一 | 3h / log10(1+100R)/2 / dup/5 | §7.4 |
| T_fut / views_pred 封顶 / comment 系数 | clamp(6−age,0.5,6) / 5× / 0.10 | §7.5 |
| 分位最短间隔 / 无档案 R_norm 兜底 | 300s / 0.30 | §7.2 / §10 表行6 |

## 14. 后续演进缝（本期一律不做，留注释即可）

1. 任务计划/automation 调度 `refresh-x-surge` 每 30min（对齐 bin/refresh_task.bat 模式）；
2. 推荐页右栏 X 热帖卡切换 `/wb-api/x-surge?limit=8` 数据源，xhot 降为降级源（§4）；
3. 评论效果回收：记录用户点击「去评论」的 status_id，24h 后对比其 views 增量，校准 10% 系数；
4. `series` 紧凑化（对象→定长数组）若文件超 10MB 再做。
