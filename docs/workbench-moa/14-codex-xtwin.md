# 14 · 图文页两子页「X 化」统一方案 —— 推荐信息 × 蹭蹭流量

> 契约: 本文是产品+技术方案, **只写方案不改代码**。所有"现状"均已在仓库核实(文件/行级事实 +
> SQLite/缓存实测, 采样时点 2026-09-04), 标注"实测"的数字可直接引用。
> 相关前案: `12-codex-xsurge.md` / `13-cursor-xsurge.md`(X 起爆帖数据侧), `09-codex-tags.md` /
> `08-cursor-tags.md`(标签筛选), `05-codex-article.md`(图文页结构定稿)。

---

## 0. 结论摘要(TL;DR)

1. **一个数据面供两页**: `/wb-api/x-surge`(即 `x_surge.build_view`)扩展为两子页唯一取数口;
   `/wb-api/recommend` 与 `/wb-api/x-hot` **整体退役**(端点+模块+前端引用同一次提交内删净)。
2. **统一排序五选一**: `time / surge / growth / pred / exposure`, 统一 None 沉底规则;
   旧"价值分"(dup_count×3 + 官方机构+2 + 重大事件+2 + 情绪+1 + 标的×0.5, `reco.py`)整体退役。
3. **统一筛选一套**: 时间范围(近1h/6h/12h/1天/2天) + 市场 chips + 赛道(L1) chips + 仅黄金窗口
   + 粉丝≥10万 + 仅投资金融; 两页共享同一份筛选状态; 赛道筛选在工作台层做(数据站 `/v1/items`
   无 sectors 参数, 红线不动)。
4. **卡片互动行统一**: 👍 🔁 💬 👁 | 增速 N/时 | 预测浏览 | 评论可蹭 ~N 曝光 | 构成 S1+S2+S3+S4,
   两页完全一致; 差异化只体现在默认排序/默认筛选/主动作/未采集条目可见性/左菜单角标。
5. **collect 采样随"全 X"扩大**: 现行 newest-first + limit 250 实测只能覆盖 ~11.4h 深度
   (24h 窗口 X 条目 522 条), 改为**覆盖优先 + 分层冷却**, limit 250→300, 48h 全覆盖不触
   2000 帖硬顶, 日调用量反而低于现状上限。
6. 三个边界都有确定行为: 无快照条目(推荐页显示/蹭蹭页不显示, 指标 sorts 沉底)、赛道未打标
   (筛选开启时排除并给缺失计数)、非池账号粉丝缺失(破圈分回退绝对量档 + "粉丝≥10万"排除未知)。

---

## 1. 背景与现状(已核实)

### 1.1 模块盘点

| 文件 | 现状 | 本方案处置 |
|---|---|---|
| `workbench/server/x_surge.py` | `collect(range_h,limit,force)` 采 FxTwitter 四件套+自动翻译; `build_view(range_h,golden,market,min_followers,finance,limit)` 全 X 条目(author_handle 非空, **不限池**)+互动快照 join+surge 四分量+text_zh 译文+finance 标记 | **扩展**为两页统一数据面(§3) |
| `workbench/server/reco.py` | 旧价值打分 `score_of`/`recommend`, 走 `/wb-api/recommend` | **退役删除**(§3.5) |
| `workbench/server/xhot.py` | 旧 X 热帖榜 heat=dup_count×3+粉丝量级档, 走 `/wb-api/x-hot` | **退役删除**(§3.5) |
| `workbench/server/app.py` | 三端点: `/wb-api/recommend`、`/wb-api/x-hot`、`/wb-api/x-surge` | 删二留一扩参(§3.1) |
| `workbench/web/js/pages/article.js` | reco 子页(工具栏+筛选卡+feed+右栏 X 热帖榜)与 surge 子页已存在; `basketIds` 已加入态; `WB.basket` 契约 `{id,time,source,text≤200,url,sel}` | 两子页模板/方法合并复用(§5) |
| `workbench/server/x_profile_enricher.py` | grok x-search → `data/workbench/x_profiles.json`; **`run_cli` 只补池内 handle**(`--handles` 分支 `todo = [h for h in todo if h in accounts]`) | 非池粉丝缺失的根因, §7.3 |
| `workbench/server/stats.py` | `/wb-api/stats` 聚合**全库**条目(含 sectors_l1 计数), 60s 缓存, ≤4 页×1000 | 不动; 两页赛道 chips 不用它(§5.3) |
| `cli.py` | `workbench refresh-x-surge [--range 24h|48h] [--limit 250] [--force]`, 30min 节奏 | range 扩 5 档(§8) |

### 1.2 数据侧实测(2026-09-04)

| 指标 | 数值 | 来源 |
|---|---|---|
| 数据站条目总量 | 3,852 条 | `data/serve/items.db` 只读查询 |
| 近 24h 条目 | 1,513 条(其中 **X 条目 522**, ≈22 条/时) | 同上 |
| 近 48h X 条目 | **1,044 条**; 去重 author_handle **76 个, 全部在 131 池内, 非池=0** | 同上 + `twitter_pool.yaml` 比对 |
| 互动快照跟踪 | 408 帖(48h X 量的 **39%**); 其中 ≥2 快照点(能出增速) **280 帖(27%)** | `data/workbench/x_engagement.json` |
| 赛道打标覆盖率 | X 条目近 24h **61.1% 无 sectors**; 近 48h **49.7% 无 sectors**; L1 头部: 宏观与政策 142 / AI与算力 121 / 金融与加密 78(48h) | 同上 |
| 档案缓存 | `x_profiles.json` 只含池账号(131 池); 非池 handle 无 followers | 文件现状 |

### 1.3 痛点(为什么必须合并)

1. **推荐信息混着非 X 条目**: `reco.recommend` 直拉数据站全量打分, 资讯源快讯与 X 帖混排,
   两套卡片结构(左框通用版 vs X 账号版)并存, "价值分"与"起爆概率"两套排序语义互相打架。
2. **右栏 X 热帖榜是假流量**: `xhot.py` 自己注释承认"不是真流量排序"(dup×3+粉丝档),
   而 x_surge 已有真互动四件套——同一屏内两套"热度"口径, 用户无法解释差异。
3. **两页筛选不对齐**: reco 有定位/类型 chips(对 X 条目意义弱), surge 有黄金窗口/大 V/金融
   chips 但没有赛道; 时间范围 reco 五档 / surge 两档。
4. **采样偏差**(§6 详述): newest-first + 250/轮 + 20min 冷却 ≤ 30min 调度节奏 → 每轮重采同一段
   最新 250 条, 窗口深度只有 ~11.4h, "全 X"范围下老帖永远没有第二快照点, 增速/预测全空。

---

## 2. 目标与非目标(用户拍板 6 条逐条映射)

| # | 拍板需求 | 落点 |
|---|---|---|
| 1 | 推荐信息只显示 X 源内容(author_handle 非空), 非 X 条目全部不出现 | §3.2 `untracked` 参数 + §5 前端; 数据面天然全 X(build_view 本来只收 X 条目) |
| 2 | 蹭蹭流量范围=库内**所有** X 内容(不限 131 池, 含"非关注"账号) | build_view 现状已不限池(实测核实); §6 采样扩大保证非头部条目真的有互动数据; §7.3 非池边界 |
| 3 | 两页卡片全部带完整互动行(👍🔁💬👁/增速/预测/评论曝光/构成四分量) | §4.3 统一互动行; reco 卡片补齐 surge-stats 行 |
| 4 | 排序统一五选一; 删除"价值分"旧规则 | §3.3 五排序键+None 沉底; §3.5 reco.py 退役 |
| 5 | 筛选两页合并同一套(时间范围五档+市场+赛道 L1+黄金窗口+粉丝≥10万+仅投资金融), 两边只显示 X 账号内容 | §3.2/§3.4 后端参数; §5.1 前端共享筛选状态 |
| 6 | 蹭蹭页保留"去评论↗"+黄金窗口徽章; 推荐页保留"＋加入素材"(素材池契约不变) | §4.2 差异化矩阵; `WB.basket.add` 五字段契约零改动 |

**非目标**: 不改数据站(板块一只读红线); 不改 `/wb-api/stats`(资讯页还在用); 不动 WB.basket 结构;
不做账号级聚合页; 不引入前端框架/构建链(维持无构建 Vue3 option-API 模板串风格)。

---

## 3. 方案 A: 后端统一 —— build_view 扩展

### 3.1 一个端点供两页

`GET /wb-api/x-surge` 扩参后同时服务两子页, 差异全在查询参数:

```
GET /wb-api/x-surge
  range         1h | 6h | 12h | 24h | 48h      (默认 24h; build_view 的 range_h 本就是 int, 直通)
  sort          time | surge | growth | pred | exposure   (默认 surge; 页面各自传)
  market        逗号分隔市场(现参数名不变, 兼容现有调用)
  sector        L1 赛道名, 单选(如 "宏观与政策"; 多选留逗号分隔扩展位)
  golden        0|1
  min_followers 0|100000
  finance       0|1
  untracked     0|1   是否并入"无互动快照"条目(推荐页=1, 蹭蹭页=0, §7.1)
  limit         100   (默认不变)
```

响应(在现形状上**只增不改**, 前端可渐进迁移):

```jsonc
{
  "items": [ /* 行字段见 §3.6, 新增: sectors, in_pool, tracked */ ],
  "total": 87,
  "golden_n": 12,            // 筛选前统计(现字段, 角标用)
  "no_baseline": 33,         // 有快照但 <2 点(现字段)
  "untracked_n": 41,         // 新增: 窗口内无快照条目数(untracked=0 时未并入 items 也照报)
  "sectors_l1": [["宏观与政策", 142], ["AI与算力", 121], ...],   // 新增: 筛选前全量 X 行的 L1 计数
  "sector_missing_n": 519,   // 新增: 筛选前无 sectors 条目数(§7.2 提示用)
  "meta": { "data_age_min": 7, "tracked": 408, "updated_at": "...", "rule": "..." }
}
```

### 3.2 build_view 改动点(函数签名与内部)

```python
def build_view(range_h=24, golden=False, market="", min_followers=0, finance=False,
               limit=100, sort="surge", sector="", untracked=False) -> dict:
```

1. **行来源两路合并**: 现在只遍历 `eng["statuses"]`(有快照才有行)。新增第二路:
   遍历 `_fetch_window(range_h)` 元数据里有 X url 但 `status_id not in eng["statuses"]` 的条目,
   构造 `tracked=False` 的行——互动四件套/增速/预测/曝光/`surge` 全部 `None`(不是 0,
   保证沉底与"—"显示), `text_zh=None`(译文随采集走, §6.4), 其余元数据字段照填。
   `untracked=False` 时这一路直接丢弃(但照常计数进 `untracked_n`)。
2. **sectors 进行**: 行字典新增 `sectors = it.get("sectors") or []`(数据站已带, 无需回源),
   `in_pool = handle in xaccounts.load_accounts()`(只读 import, 判"非关注"徽章用),
   `tracked` 布尔。
3. **sector 筛选**(工作台层做, 红线一致): `sector` 非空时
   `rows = [r for r in rows if any(str(s).split(">")[0] == sector for s in r["sectors"])]`。
   未打标条目在筛选开启时**被排除**(§7.2), 关闭时照常出现。
4. **sectors_l1 计数**: 在所有筛选之前对全量行做 `Counter(str(s).split(">")[0] for ...)`,
   按频次降序输出(推荐页 chips "常驻 top6 + 展开全量"的数据源, §5.3)。同时输出
   `sector_missing_n`。
5. **range 语义**: `range_h` 直接透传给 `_fetch_window`(现有 60s 进程内缓存按键缓存,
   5 档各自独立, 无互踩)。**注意**: 1h/6h 小窗口下快照本来就稀疏, 属预期行为(§7.4)。

### 3.3 排序键定义(五选一)与 None 沉底规则

| sort 值 | UI 文案 | 主键 | 次键 | 说明 |
|---|---|---|---|---|
| `time` | 时间顺序 | `time` 降序("YYYY-MM-DD HH:MM" 字典序即时间序) | `status_id` | 唯一没有 None 问题的排序; untracked 新帖天然在顶 |
| `surge` | 起爆概率 | `surge` 降序 | `-(views or 0)` | 现状不变(`rows.sort(key=lambda r: (-r["surge"], -(r["views"] or 0)))`) |
| `growth` | 增速 | `growth_views_h` 降序, None 沉底 | `time` 降序 | 无基线(<2 快照点)沉底 |
| `pred` | 预测浏览 | `views_pred` 降序, None 沉底 | `time` 降序 | views 缺失(FxTwitter 无 views 字段)沉底 |
| `exposure` | 评论曝光 | `reply_exposure` 降序, None 沉底 | `time` 降序 | 同上 |

**统一 None 沉底实现**(一处工具函数, 三处复用):

```python
def _metric_key(r, field):
    v = r.get(field)
    ts = r.get("_ts") or 0          # 行构造时算好 time 的 epoch, 避免排序中反复 strptime
    return (1, 0, -ts) if v is None else (0, -v, -ts)
# sorted(rows, key=lambda r: _metric_key(r, "growth_views_h"))
# 元组首元素: 有值(0)排前 / None(1)排后 → None 沉底;
# 有值组内 -v 升序 = 值降序; None 组内按时间新→旧, 保证"沉底的也按新鲜度可读"。
```

规则口径(写进 `meta.rule` 追加段): **指标排序下, None 恒沉底; 沉底组内部按时间倒序**。
不采用"None 当 0 参与排序"——那会把未采集条目伪装成"零增长", 与真实 0 增速不可区分。

### 3.4 recommend 与 xhot 的退役方式

**同一次提交内原子退役**(本地单用户工具, 无外部消费方, 不留废弃期):

1. 删 `workbench/server/reco.py`、`workbench/server/xhot.py` 两个模块文件。
2. 删 `app.py` 中 `/wb-api/recommend`、`/wb-api/x-hot` 两个端点及 import。
3. 删 `article.js` 中: `recoSort` 的 score/time 双 radio(换五选)、`scoreParts()`、打分规则行、
   价值分徽章、右栏 X 热帖榜整块模板 + `loadXHot/toggleXhotMarket/xhotRange/xhotMarkets` 状态。
4. **保留**的价值不丢: xhot 的"每账号限 2 条防霸榜"思想在推荐页由时间排序天然保证多样性;
   dup_count(同事件×N)徽章两页卡片都继续显示(字段已在行里)。价值分本身按拍板**不迁移、不归档**
   ——git 历史即存档。

> 旧打分规则原文(退役存档, 来自 `reco.py` docstring): dup_count×3 + 官方/机构源+2 +
> 重大事件(macro/policy/earnings)+2 + 情绪非中性+1 + 标的数×0.5。此后图文页排序口径只有
> §3.3 的五个。

### 3.5 红线核对(改动不越界)

| 红线 | 核对结果 |
|---|---|
| workbench 对板块一只读 | build_view 只经 `proxy.fetch_json` 读 `/v1/items`; sector/range 筛选全在内存做, 不给数据站加参数 ✅ |
| 工作台自有数据只写 `data/workbench/` | 本方案零新增写文件; x_engagement/x_surge_texts 写路径不变 ✅ |
| 采集外呼只在 CLI 进程 | `build_view` 扩展仍是纯读; `untracked` 路只查窗口缓存与档案缓存, 零外呼; 翻译仍只随 `collect` ✅ |
| app.py 端点只读缓存 | x-surge 端点行为不变 ✅ |

### 3.6 行字段契约(响应 `items[]`, 现状 + 新增标注)

| 字段 | 类型 | 来源/含义 | 变更 |
|---|---|---|---|
| `status_id` | str | FxTwitter 帖 id(主键, 蹭蹭页 basket id) | 不变 |
| `handle` / `name` | str | 账号 handle(小写)/显示名(去 "X·" 前缀) | 不变 |
| `in_pool` | bool | handle 是否在 131 池(xaccounts 只读判定) | **新增**, "非关注"徽章用 |
| `tracked` | bool | 是否已有互动快照 | **新增** |
| `followers` / `followers_known` | int/bool | 粉丝数(档案缓存)/是否已知 | **新增** known |
| `time` / `age_h` | str/float | 发布时间("YYYY-MM-DD HH:MM")/帖龄小时 | 不变 |
| `text`(≤200) / `text_zh` | str | 原文截断/中文译文(随采集, 可 None) | 不变 |
| `finance` | bool | sectors/tickers/event_type 任一非空 | 不变 |
| `url` / `reply_url` | str | 数据站条目 url / `x.com/<handle>/status/<id>` 直链 | 不变 |
| `markets` / `sectors` | list | 市场标签 / 赛道路径("L1>L2(>L3)") | sectors **新增**进行 |
| `dup_count` | int | 同事件簇大小(徽章"同事件 ×N") | 不变 |
| `likes/retweets/replies/views` | int\|None | FxTwitter 四件套最新快照 | untracked 行全 None |
| `growth_views_h` / `growth_likes_h` | num\|None | 最近两快照差/时间差(≥5min 防抖) | 不变 |
| `surge` | int\|None | S1+S2+S3+S4 封顶 100; untracked 行 None | 微调(见左) |
| `golden` | bool | 发布 ≤2h | 不变 |
| `views_pred` | int\|None | views×(1+3/max(age_h,0.5)) 封顶 ×4 | 不变 |
| `reply_exposure` | int\|None | views×10%(评论可蹭曝光) | 不变 |
| `surge_parts` | obj | `{growth,baseline,decay,abs}` 四分量明细 | 不变 |

> `surge = min(S1+S2+S3+S4, 100)`, 四分量权重
> 40/30/20/10, 档表 `_T1.._T4` 维持 `12-codex-xsurge.md` 定稿不动——本方案不改打分公式,
> 只改排序入口与边界回退(§7.3 的 S2 粉丝未知回退是唯一公式相邻改动)。

---

## 4. 方案 B: 两子页的产品差异化定义

### 4.1 定位分工(一句话)

- **推荐信息 = "看什么、收什么"**: 全 X 信息流, 按时间或指标排序浏览, 看到好的进素材池。
  对标的是"信息发现流"。
- **蹭蹭流量 = "去哪儿蹭、现在去"**: 已起爆/将起爆的帖子, 按(增速-)排序找评论卡位目标,
  黄金窗口内去评论蹭曝光。对标 `sopilot.net/zh/hot-tweets` 的"热帖+可操作"形态。

### 4.2 差异化矩阵(避免同页换皮的硬约束)

| 维度 | 推荐信息 | 蹭蹭流量 |
|---|---|---|
| 默认排序 | **时间顺序**(time) | **起爆概率**(surge) |
| 默认时间范围 | 近1天(24h) | 近1天(24h) |
| 默认筛选 | 全关(纯净流) | 全关, 靠**黄金窗口徽章**引导而非默认过滤 |
| 无快照条目 | **显示**(untracked=1, 互动行显示"—"+"待采集") | **不显示**(untracked=0, 互动数据是本页存在意义) |
| 主动作 | **＋加入素材**(主, 已加入变"已加入 ✓"); 原文链接次之 | **去评论 ↗**(主, 直链 status); ＋加入素材为次动作 |
| 黄金窗口 | 不做特殊元素(仅时间戳旁小徽章) | **黄金窗口徽章**(现样式保留, 榜单位置语义) |
| 排序默认外的常用档 | 增速 / 评论曝光(找"正在热起来/能蹭到曝光"的) | 增速 / 预测浏览(找"还在涨/盘子大"的) |
| 左菜单角标 | `total`(当前筛选下 X 条目数, 现状保留) | `golden_n`(黄金窗口帖数, 现状保留) |
| 空态文案 | "该范围内暂无 X 内容 —— 放宽时间或筛选" | 现文案保留("先跑两轮 refresh-x-surge…") |
| 布局 | 单列 feed(右栏热帖榜退役后 `.reco-cols` 收敛为一列) | 现单列 surge feed 不变 |

判定标准: 任一时刻把两页截图摆在一起, **不看标题也能分辨**——推荐页是"账号+内容+标签"的信息卡,
蹭蹭页是"概率大数字+互动行+去评论"的作战卡。若某次迭代让两者默认视图趋同, 即视为违反本节。

### 4.3 卡片结构(互动行统一, 骨架各异)

两页卡片**下半部分互动行完全一致**(抽一个模板片段复用, §5.2):

```
👍 1.2万  🔁 856  💬 234  👁 45.6万 | 增速 3,210/时 | 预测浏览 52万 | 评论可蹭 ~4.6万曝光
构成: 增速40 + 破圈30 + 衰减20 + 绝对量7
```

- None 一律显示 "—"(增速档显示现文案 "增速 —(攒基线中)"; untracked 行显示 "互动数据待采集")。
- `surge_parts` 四分量照抄现格式(`growth/baseline/decay/abs`)。
- 上半部分骨架保持两页各异: 推荐页用现 `nc-grid`(左账号框+右内容框, 账号名/handle/定位/市场
  /简介/赛道徽章), 蹭蹭页用现 `surge-grid`(左概率柱+右帖体)。

### 4.4 左菜单角标与文案

- 推荐信息角标 = `total`(数值来自响应, 不再是 recoTotal 旧接口字段); 蹭蹭流量角标 = `golden_n`。
- 菜单标题不改("推荐信息"/"蹭蹭流量"); reco 页顶部打分规则说明行删除, 换成一行固定说明:
  "仅 X 账号内容 · 排序: 时间/起爆/增速/预测/曝光"。

---

## 5. 方案 C: 前端改造清单(article.js)

### 5.1 状态合并(一套筛选, 两份差异)

```js
/* 新: 两页共享的筛选状态(同一套, 语义+视觉都同一份 chips) */
xf: { range: "24h", markets: [], sectors: [], golden: false,
      bigOnly: false, finance: false },
sort: { reco: "time", surge: "surge" },      // 排序按页记忆(差异化矩阵 §4.2)
recoItems: [], surge: [], xmeta: {},          // 各页结果分开存(切换 tab 不互刷)
untrackedShown: { reco: true, surge: false }, // §7.1
```

- 砍掉: `recoSince/sinceOpts 旧挂法/recoMarkets/recoPositionings/recoItemTypes/recoSort/
  surgeRange/surgeGolden/surgeMarkets/surgeBigOnly/surgeFinance` 九组散状态 → 全部并入 `xf`
  + `sort`。定位/类型 chips 随 reco.py 退役删除(X 条目上这两组标签语义弱, 拍板清单里也没有)。
- `sinceOpts` 统一五档: `[["1h","近1小时"],["6h","近6小时"],["12h","近12小时"],
  ["24h","近1天"],["48h","近2天"]]`(现成常量, 两页共用)。

### 5.2 模板/方法合并的最小方案

原则: **不引入子组件机制**(现文件是单组件模板串, 保持风格), 用"共享状态 + 一份筛选卡模板 +
一个装载函数"达到复用:

1. **筛选卡模板只写一份、两处 include 式复用**: 由于两页都用 v-show 常驻 DOM, 且 Vue 模板串
   不便做 partial, 最小代价方案是把筛选卡(markets chips 行 + sectors chips 行 + 三个开关 chip)
   的 20 行标记在两个子页各放一份, **但绑定完全相同的 `xf` 状态**——视觉同一套、状态同一套,
   只是 DOM 出现两次。若后续觉得双份标记难维护, 再升级为局部组件 `wb-xfbar`(props: 无,
   直接读写 `xf`), 本期不做。
2. **一个装载函数**: `loadXF(tab)` 替代 `loadReco`/`loadSurge`:

```js
async loadXF(tab) {
  const p = new URLSearchParams({
    range: this.xf.range, sort: this.sort[tab],
    untracked: tab === "reco" ? "1" : "0", limit: "100",
  });
  if (this.xf.markets.length) p.set("market", this.xf.markets.join(","));
  if (this.xf.sectors.length) p.set("sector", this.xf.sectors.join(","));
  if (this.xf.golden)  p.set("golden", "1");
  if (this.xf.bigOnly) p.set("min_followers", "100000");
  if (this.xf.finance) p.set("finance", "1");
  const d = await WB.api.get("/x-surge?" + p.toString());
  /* tab==="reco" → this.recoItems=d.items; 否则 this.surge=d.items; this.xmeta 共享 */
}
```

   筛选变化时**两页同刷还是惰性刷**? 建议: 改筛选只刷当前 tab(点击反馈快), 切到另一 tab 时若
   `xf` 版本号变了再重刷(一个 `xfVersion` 计数器即可)。避免改一个 chip 打两个接口。
3. **五选排序 switch**: 模板里一个 radio-group `v-model="sort[tab]" @change="loadXF(tab)"`,
   五个 option 复用一份数组 `sortOpts = [["time","时间"],["surge","起爆"],["growth","增速"],
   ["pred","预测浏览"],["exposure","评论曝光"]]`; 无需 per-sort 分支逻辑(排序全在服务端)。
4. **互动行片段**: 把现 surge 卡的 `surge-stats` + `surge-parts` 两行抽成同一份标记在两页卡片
   里复用(reco 卡的 `nc-body` 底部插入同款两行, 数据字段名完全一致, 零映射)。
5. **卡片动作区差异**: reco 卡 `news-actions` = 原文链接/展开全文/＋加入素材(现逻辑不动);
   surge 卡 = 去评论 ↗ + ＋加入素材(现逻辑不动)。`addSurgeToPool`/`addToPool` 都继续走
   `WB.basket.add` 五字段契约, `basketIds` 键不变(数据站条目 id 与 status_id 天然不同域)。

### 5.3 赛道 chips 数据来源: **从 x-surge 响应聚合, 不用 /stats**

| 候选 | 结论 |
|---|---|
| `/wb-api/stats.sectors_l1` | **否**。它聚合的是全库条目(含资讯源), 计数口径与"仅 X"页面不一致, 会把"金融与加密 24 条"这类 X 侧计数报大; 且 60s 缓存+4 页全量拉取, 为两页 chips 跑它太重 |
| **x-surge 响应 `meta.sectors_l1`(选定)** | 服务端已在 build_view 里持有筛选前的全量 X 行, 顺手 Counter 一次即得; 计数口径与页面完全一致; 零额外请求 |

前端: `sectorChipsTop = xmeta.sectors_l1.slice(0,6)`(常驻 top6, 与资讯页交互一致),
展开区给全量; 每个 chip 尾缀计数(如 `宏观与政策 142`); `sector_missing_n > 0` 时在 chips 行尾
显示灰字 "另 N 条未打标不参与赛道筛选"(§7.2)。

### 5.4 右栏 X 热帖榜: 退役

- 依据: xhot 是假流量口径(§1.3-2), 与五选排序语义冲突; "多样性扫读"诉求由推荐页
  时间排序 + 每账号天然分散覆盖。
- 动作: 删 `reco-rail` 整块模板 + `loadXHot/toggleXhotMarket/xMarketChips` 中 xhot 专用部分
  (`xMarketChips` 仍被 surge 市场行使用, **保留**); `.reco-cols` 网格在 CSS 中收敛为单列
  (或 reco 子页不再包 `.reco-cols`, 直接单列; 建议后者, CSS 少动)。
- 顺带删除 `xHotName()`(若仅右栏在用; 它与 `xName()` 职责重叠, 统一用后者)。

### 5.5 删除清单(前端, 一次提交)

`reco.py` 相关: score 徽章、`scoreParts()`、打分规则行、score/time 双 radio。
`xhot.py` 相关: `reco-rail` 模板块、`xhot/xhotRange/xhotMarkets/xhotRule` 状态、`loadXHot()/
toggleXhotMarket()`。散状态合并见 §5.1。`isX()`/通用左框分支可保留(数据全 X 后恒真,
但保留防御性渲染成本为零, 本期不清理, 避免无谓 diff)。

---

## 6. 方案 D: collect 采样随"全 X"扩大 + 翻译随行

### 6.1 现状采样偏差(实测数字推演)

- 24h 窗口 X 条目 522(≈22 条/时), 候选按**新→旧**排序截 `limit=250` → 每轮实际采样深度
  ≈ 250/22 ≈ **11.4h**。
- 单帖冷却 20min **小于**调度节奏 30min → 下一轮到点时上一轮的 250 条已全部解冻, 而它们仍是
  窗口里最新的 250 条 → **每轮重采同一段**; 11.4h 之外的尾巴几乎永远等不到快照。
- 后果实测: 48h X 量 1,044, 快照只跟踪 408(39%), 能出增速的仅 280(27%)。"全 X"范围下,
  老帖的增速/预测/曝光全空, `growth/pred/exposure` 三个排序对它们无意义。

### 6.2 改法: 覆盖优先 + 分层冷却(改 `_fetch_candidates` + `collect` 的 todo 筛选)

候选优先级重排(每层内部仍新→旧):

1. **零快照**条目(窗口内任何 age)——补首点, 这是"全 X"承诺的底线;
2. **黄金窗口(≤2h)且距上次采样 ≥20min**——起爆段要密集点;
3. **其余已采样条目按分层冷却到期**: age≤2h → 20min; 2h<age≤12h → 60min; age>12h → 180min
   (衰减期后的增速信息价值低, 少采)。

实现要领: `_fetch_candidates` 现在只做"窗口拉取+去重+新→旧截断"; 改为拉全窗口(48h 1,044 条,
翻页上限 max_pages=5×1000 足够), 与 `eng["statuses"]` 比对算出每条的优先级/是否到期,
再按优先级排序截 `limit`。`COOLDOWN_S` 常量改成分层函数 `_cooldown_s(age_h)`。

### 6.3 预算与上限核算(30min 节奏, limit 250→300)

| 项 | 每轮(稳态估算) | 说明 |
|---|---|---|
| 新增条目 | ~11 | 22 条/时 ÷ 2 |
| 黄金窗口复采 | ~44×(2h 黄金期内 3~4 次)摊到轮 ≈ 8~12 | 与新增重叠后更少 |
| 2~12h 带到期 | ~22 | 264 条 × 每小时 1 次 |
| >12h 带到期 | ~130 | ~780 条 × 每 3h 1 次 |
| **合计** | **~170-200 ≤ 300** | 单轮 4 并发×8s 超时, 实跑 2~3 分钟, 30min 节奏无压力 |

- 日调用量: ~5,000 次/日, **低于**现行配置的理论上限(250×48 轮=12,000, 现状实为全部砸在重复段);
  FxTwitter 429 全局熔断逻辑原样保留, `--force` 语义不变。
- `MAX_STATUSES=2000` 硬顶: 48h X 量 1,044, 72h 保留窗口 ~1,500 → 不触顶, 参数不动;
  `RETAIN_H=72` 与最大 range 48h 兼容(留 24h 余量), 不动。
- `--limit` 默认值 250→300(cli.py 同步改); `--range` choices 扩为 `["1h","6h","12h","24h","48h"]`
  (采集窗口与浏览窗口对齐, 默认仍 24h)。

### 6.4 翻译随行策略

- 现状: `translate_pending(cands)` 挂在 collect 轮尾, 每轮最多 60 条, 0.25s 间隔防限流;
  缓存 `x_surge_texts.json` 按 status_id 永存。**维持"翻译只随采集"的架构**(build_view 零外呼
  红线), 不在端点侧补翻译。
- 覆盖优先采样后, untracked 条目进入候选 → 译文自动随行, 无需独立翻译调度。
- 每轮 60 条上限维持: 稳态新增翻译 ≈ 新条目数(11/轮), 存量缺口(首轮全 X 化后最多 ~600 条)
  会在 ~10 轮(5 小时)内追平, 不必调大(调大反而单轮拉长)。
- 前端对无 `text_zh` 的行显示原文(title 悬浮提示, 现有 `:title` 逻辑已支持)。

---

## 7. 方案 E: 边界行为(逐条定死)

### 7.1 无互动快照的条目(新入库、未采集)

| 场景 | 行为 |
|---|---|
| 推荐信息页 | **显示**(untracked=1): 信息流不该漏新帖; 时间排序下按时间自然在顶; 互动行整体 "—", 尾缀 "互动数据待采集"(下一轮 collect 自动补上, ≤30min) |
| 蹭蹭流量页 | **不显示**(untracked=0): 本页每个数字都依赖快照, 无快照条目只制造噪音; 响应里用 `untracked_n` 透出数量即可 |
| `surge/growth/pred/exposure` 排序 | None 恒沉底(§3.3); 不会出现"未采集被当成 0 分"的假象 |
| `time` 排序 | 正常参与(唯一不依赖快照的排序) |
| 有 1 个快照点(<2 无增速) | 两页都显示; `no_baseline` 计数; 增速/构成中 S1 显示 0(现 _tiers 对 None 给 0 档, 保留), 前端增速格显示 "—(攒基线中)" |

### 7.2 赛道未打标条目(实测 24h 61.1% / 48h 49.7% 无 sectors)

- 赛道筛选**关闭**(默认): 未打标条目正常出现, 与打标条目无任何差别。
- 赛道筛选**开启**: 未打标条目**被排除**(与资讯页 news.js 客户端 sector 过滤行为一致, 两页口径
  统一), 不做"含未打标"开关(复杂度不值); 但必须可见——chips 行尾灰字 "另 N 条未打标不参与
  赛道筛选", N=`sector_missing_n`, 防止"帖子去哪了"困惑。
- chips 计数只统计打标条目(§5.3), 因此 chip 上的数字是"选中后至少能看到的量", 不虚标。

### 7.3 非池账号粉丝数缺失("非关注"账号)

- 现状澄清(实测): 近 48h 库内 76 个去重 handle **全部在 131 池内, 非池=0**——"全 X"范围今日
  实际仍是池内容; 但需求红线是**不按池过滤**(未来任何源吐出带 author_handle 的 x.com 条目
  自动进两页), 所以边界必须现在定死。
- **破圈分(S2)**: `x_profiles.json` 无该 handle → followers=0 → 现 `fbase=max(followers,1000)=1000`
  会让 `ratio=views/1000` 轻易打满 30 分档(views≥3,000 即满), **虚高**。改法(短长期各一):
  - 短期(build_view 内): followers 未知(不在档案缓存)时 S2 回退用 `_T4(views)` 绝对量档
    (上限 10 分, 保守), 行上标 `followers_known=false`; 已知时维持现 `ratio` 口径。
  - 长期(可选 follow-up): `x_profile_enricher.run_cli` 放开非池 handle(如 `--include-nonpool`,
    自动收集 engagement 缓存里无档案的 handle 分批补), 补齐后自然回到 ratio 口径。
- **"粉丝≥10万"筛选**: followers 未知的条目**一律排除**(宁可漏筛不可误放; 未知≠≥10万)。
  已知且 <10万 同样排除。UI 上粉丝位显示 "粉 ?" 而非 "粉 0"(配合 `followers_known`)。
- **S4 绝对量档**不受影响(用 views, 不用粉丝); **破圈度原始值**展示不受影响。

### 7.4 其他边界(顺手定死)

| 边界 | 行为 |
|---|---|
| FxTwitter views 缺失(字段可为 None) | views/预测/曝光/回复曝光全 None → 沉底 + "—"; 现逻辑已如此, 保持 |
| 快照在 72h 保留窗之外但条目仍在窗口内 | 理论不发生(48h range < 72h 保留); 若因 2000 帖淘汰发生, 该条目按 untracked 路径重进(零快照), 自愈 |
| `data_age_min > 90`(数据偏旧) | 现黄色警示保留, 两页共享(放 `xmeta` 上, 推荐页也显示——它同样依赖快照新鲜度) |
| range=1h/6h 小窗口 | 快照稀疏是预期; 空态文案提示"窗口太小, 换近1天"; 后端不做特殊处理 |
| 同一 status 被多源重复 | `_fetch_window` 元数据以 sid 首见为准(现 `meta.setdefault`), 行为不变 |
| 赛道 chip 选择后再切时间范围 | chips 计数随响应刷新(是筛选前计数, 天然随 range 变), 前端无需特判 |

---

## 8. 方案 F: 落地步骤(文件级) + 验证清单

### 8.1 步骤(顺序执行, 每步可独立验证)

| 步 | 文件 | 改动 |
|---|---|---|
| 1 | `workbench/server/x_surge.py` | build_view 加 `sort/sector/untracked` 参数; untracked 第二路行合并; 行加 `sectors/in_pool/tracked/followers_known`; 响应加 `untracked_n/sectors_l1/sector_missing_n`; `_metric_key` None 沉底; S2 粉丝未知回退(§7.3); `_ts` 预解析 |
| 2 | `workbench/server/x_surge.py` | `_fetch_candidates` 覆盖优先+分层冷却(§6.2); `collect` 的 `COOLDOWN_S` 换 `_cooldown_s(age_h)`; `translate_pending` 不动 |
| 3 | `cli.py` | `refresh-x-surge` 的 `--range` choices 扩五档; `--limit` default 300(帮助文案同步) |
| 4 | `workbench/server/app.py` | `/wb-api/x-surge` 端点透传新参数(sort/sector/untracked); 删 `/wb-api/recommend`、`/wb-api/x-hot` 端点与 `reco/xhot` import |
| 5 | 删文件 | `workbench/server/reco.py`、`workbench/server/xhot.py` |
| 6 | `workbench/web/js/pages/article.js` | §5 全部: 状态合并(`xf/sort/xmeta`)、`loadXF(tab)`、五选 radio、筛选卡双份标记共享状态、互动行片段两页复用、reco 卡补互动行、删右栏热帖榜/score 徽章/散状态、角标改 `xmeta` 取数 |
| 7 | `workbench/web/css/*` | reco 子页去 `.reco-cols` 包裹(单列); `.reco-rail` 样式可留(news 页若复用则不动, 确认后删) |
| 8 | 收尾 | grep 全仓 `recommend|/x-hot|recoSort|score_parts|价值排序` 清残留; `docs/` 下相关方案文加一行"已被 14 取代"注记 |

建议一次 PR/一次提交(端点删除与前端切换必须原子, 中间态会白屏)。

### 8.2 验证清单

后端(不启动前端即可验):

```bash
# 每种排序出数且 None 沉底(抽查首尾行字段)
python -c "import sys; sys.path.insert(0,'workbench'); from server import x_surge as x; \
  r=x.build_view(range_h=48, sort='growth', untracked=True, limit=200); \
  print(r['total'], r['untracked_n'], len(r['sectors_l1']), r['sector_missing_n']); \
  print([ (i['growth_views_h'], i['time']) for i in r['items'][:3] ], \
        [ (i['growth_views_h'], i['time']) for i in r['items'][-3:] ])"
# sector 筛选: 选中"宏观与政策"后 total 下降且 sector_missing_n 照报
# 采集: 连跑两轮, 第二轮 tracked 增长且不再只重采最新 250
python cli.py workbench refresh-x-surge --range 48h
python cli.py workbench refresh-x-surge --range 48h
```

接口: `curl "http://127.0.0.1:8788/wb-api/x-surge?range=6h&sort=time&untracked=1"` 200 且含新字段;
`/wb-api/recommend`、`/wb-api/x-hot` 404; `/wb-api/stats`、`/wb-api/v1/*` 回归不受影响。

前端(UI 手验): ①两子页筛选 chips 完全同套且互相同步状态; ②五选排序在两页都能切、
切页记忆各自默认; ③推荐页卡片有完整互动行, 未采集条目显示"待采集"; ④蹭蹭页看不到未采集条目;
⑤"＋加入素材"(两页)入池后内容生成页可见、"去评论↗"直链 status; ⑥左菜单角标两页数值正确;
⑦赛道筛选开启时 chips 行尾出现"另 N 条未打标"; ⑧"粉丝≥10万"开启后非池/未知账号消失。

红线回归: `data/workbench/` 外无新写文件; serve 进程跑验证期间零外呼(可观察 FxTwitter 无新请求);
资讯页/草稿/发布/自动化四子页无感知。

### 8.3 回滚

单提交 revert 即可。互动快照缓存格式**零 schema 变更**(只有读取侧行为变化), 旧代码可直接读新缓存;
前端 localStorage(WB.basket/主题)不受影响。

---

## 9. 风险与开放问题

| # | 风险/问题 | 处置 |
|---|---|---|
| 1 | FxTwitter 限频加剧(覆盖优先后单轮调用结构变化) | 429 全局熔断保留; limit 300 上限兜底; 若频繁熔断, 先降 >12h 带冷却到 240min, 不动黄金段 |
| 2 | "全 X"范围未来混入低质非池账号(spam/搬运号) | 本期不做质量过滤(拍板未要求); 观察入口已留: `in_pool` 字段可做"仅关注"开关, 属后续迭代 |
| 3 | 赛道打标率低(50%~61% 缺失)使赛道筛选体感"变少" | `sector_missing_n` 透明化; 根治在板块一(打标覆盖率), 已知 follow-up, 不在本方案扩权 |
| 4 | 推荐页含 untracked 条目后与蹭蹭页条目集不同, 用户疑惑 | 差异化矩阵(§4.2)显式声明这是特性; 推荐页空态/提示文案解释"待采集" |
| 5 | xhot 删除后"每账号限 2 条"防霸榜消失 | 时间排序天然分散; 若用户反馈大号刷屏, 追加 `per_handle=2` 服务端参数(预留, 不实现) |
| 6 | 五选排序中 growth/pred/exposure 在小窗口+低覆盖期大面积 None | §6 采样扩大后 48h 覆盖率应从 27%(≥2 点)显著回升; 上线后一周复测, 若仍 <50% 再评估采集节奏 |
| 7 | `.reco-cols` CSS 收敛影响其他页 | `.reco-cols` 仅 reco 子页使用(grep 已核), news 页另有布局类; 删除前再确认一次 |

---

## 附: 一次提交的验收一句话

> 图文页两个子页只剩一套筛选、一套排序、一种互动行; 推荐页=全 X 信息流(时间序+收素材),
> 蹭蹭页=全 X 起爆榜(概率序+去评论); 价值分与假热度榜从代码里消失; 采样覆盖 48h 全量 X
> 而不是最新 11 小时。
