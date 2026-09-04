# 15-cursor-xtwin — 图文页双子页 X 化统一:【推荐信息】×【蹭蹭流量】合并重构方案

> 岗位: 答卷人 cursor(方案设计, 不动代码)。日期: 2026-09-03。
> 产出: 仅本文档 `docs/workbench-moa/15-cursor-xtwin.md`, 不改任何代码。
> 任务: 图文页两个子页(推荐信息 / 蹭蹭流量)在"全 X 内容"口径下合并重构——
> 一个后端引擎、一套筛选与排序、一套卡片互动行; 两页只保留产品定位差异, 不做换皮。
> 前置: 12/13 号方案已落地 `workbench/server/x_surge.py`(互动快照 → 起爆四分量), 本篇在其上做统一,
> 并整体退役旧价值分(`reco.py`)与旧热帖榜(`xhot.py`)。
> 事实来源: 工作区当前代码(行号 2026-09-03 实测) + 任务书给定已验证事实(直接采信)。

---

## 0. 结论速览

| 决策点 | 结论 |
|---|---|
| 后端引擎 | 只留一个: `x_surge.build_view` 扩展为"全 X 条目 feed"(无快照的条目也出行), 新增 `sort` 五选、`sector` L1 筛选、range 1~48h |
| `/wb-api/x-surge` | 保留并扩参, 成为两个子页的唯一取数口 |
| `/wb-api/recommend` | 退役: 先挂 410 桩一个版本, 下个清理版删路由; `reco.py` 整文件删除(dup_count×3+官方/机构+2 那套规则整体退役) |
| `/wb-api/x-hot` + `xhot.py` | 退役(右栏 X 热帖榜随推荐页双栏布局一并取消), 同样走 410 桩过渡; 13 号方案已由 x_surge 实现其"真流量"目标, 代理热度分失去存在理由 |
| 前端 | `article.js` 两子页共用 loadFeed + 同一套排序/范围/筛选 chips + 互动行局部组件; 卡片保留两套布局(定位差异, 见 §4) |
| 采集 | 默认 250/轮暂不动, 先加观测字段; 触达阈值再升 400/轮 + MAX_STATUSES 4000; 修"先截断后跳冷却"的采样饥饿缺陷 |
| 价值分 | 前端"价值 N"徽章、打分规则行、score 排序 radio 一并删除; 素材池契约不变 |

一句话: **两页同源同骨架, 差异只在默认值、主动作与卡片左区**——推荐信息回答"刚发生了什么"(读),
蹭蹭流量回答"现在去蹭哪条"(动)。

---

## 1. 需求 → 现状差距审计

用户拍板的 6 条需求, 逐条对现状(行号为工作区当前文件实测):

| # | 需求 | 现状 | 差距 | 处置 |
|---|---|---|---|---|
| 1 | 推荐信息只显示 X 源(author_handle 非空), 非 X 条目全不出现 | `article.js loadReco`(L118-134)调 `/wb-api/recommend`, `reco.py recommend`(L36-56)拉数据站全源条目, 非 X 内容照出 | 取数口就错了, 换源才能根治 | 推荐页改调 `/wb-api/x-surge`(§3/§5); recommend 退役(§3.7) |
| 2 | 蹭蹭流量范围=库内**所有** X 内容(不限 131 池, 含"非关注"账号) | `x_surge.build_view` L348 以 `eng["statuses"]` 为主表遍历——**只有被采集过快照的帖才出现**, 且 `_fetch_candidates` 虽不限池, 但未采到快照前影子都没有 | 主表选错: 该以"窗口内 X 条目"为主表, 快照作可选 join | §3.2 行来源反转 |
| 3 | 两页卡片全部带完整互动行(👍🔁💬👁 | 增速 | 预测 | 评论可蹭~N曝光 | 构成 S1~S4) | 只有蹭蹭页有(article.js L564-576); 推荐页卡片无任何互动字段 | 互动行抽成局部组件, 两页共用 | §4.3/§5.3 |
| 4 | 排序五选一(时间/起爆/增速/预测浏览/评论曝光), 删除价值分 | 蹭蹭页固定 surge 降序(x_surge.py L419, 前端无排序 UI); 推荐页 score/time 二选; 价值分规则 reco.py L19-33 | 统一 sort 参数 + None 沉底; 价值分三处删 | §3.3, §3.7, §5.2 |
| 5 | 筛选两页同一套: 时间(近1h/6h/12h/1天/2天)+市场+赛道(L1)+仅黄金窗口+粉丝≥10万+仅投资金融 | 推荐页: since 下拉+市场/定位/类型 chips(L400-427); 蹭蹭页: 24h/48h+golden/big/finance+市场(L517-532); **两边都没有赛道筛选**(数据站 /v1/items 无 sectors 参数, 只能工作台层做) | 一套 chips 组件两页实例化; 赛道在 build_view 内过滤 | §3.4/§5.2 |
| 6 | 蹭蹭页保留"去评论↗"+黄金窗口徽章; 推荐页保留"＋加入素材"(素材池契约不变) | 均已存在(L578/550 与 L476; basket 契约 L206-211) | 无差距, 合并时保持 | §5.5 |

另有两个任务书点名的"存量处置"问题:

- 右栏 X 热帖榜(`article.js` L483-511 + `xhot.py`): 其 docstring(L3-11)自认是"真流量版落地前"的代理
  (heat=dup_count×3+粉丝量级), 13 号方案落地后真流量四件套已有时序快照, 代理分严格被支配 → **退役**(§5.4)。
- `reco.py` 价值分: 规则、路由、前端徽章三处都在, 必须同一版本一起摘干净, 否则出现"没有打分入口却显示价值 0"的脏 UI。

---

## 2. 总体架构: 一个引擎, 两个视图

```
                     ┌─ CLI 进程(唯一外呼点) ─────────────────────────┐
                     │ python cli.py workbench refresh-x-surge       │
                     │   collect(): 数据站拉近窗 → FxTwitter 四件套   │
                     │   → data/workbench/x_engagement.json 快照     │
                     │   → 顺带 translate_pending() 译文缓存          │
                     └───────────────┬───────────────────────────────┘
                                     │ 只读
   数据站(8787, 只读) ── proxy ──> x_surge.build_view(range_h, sort, golden,
   /v1/items(全源条目)              market, sector, min_followers, finance, limit)
   x_profiles.json(粉丝) ───────>      │
   x_engagement.json(快照) ─────>      │  主表=窗口内全 X 条目; 快照/译文/粉丝可选 join
                                       ▼
                            /wb-api/x-surge  (唯一取数口)
                                       │
                ┌──────────────────────┴──────────────────────┐
                ▼                                             ▼
   子页【推荐信息】(读)                            子页【蹭蹭流量】(动)
   默认: 时间顺序 · 近12h                          默认: 起爆概率 · 近1天
   主动作: ＋加入素材                              主动作: 去评论↗ (+黄金徽章)
   卡片左区: 账号档案框                            卡片左区: 起爆概率大数字
                └──────── 同一套: 五选排序 / 六组筛选 / 互动行组件 / 素材池写入 ──┘
```

红线不变式(全部继承自 12/13 号方案与项目 AGENTS.md):

- workbench 对板块一只读(经 proxy), 服务器进程零外呼; 采集外呼只在 CLI 进程。
- 工作台自有数据只写 `data/workbench/`(x_engagement.json / x_surge_texts.json / x_profiles.json)。
- 素材池 `WB.basket` 契约 `{id, time, source, text≤200, url}` 不动, 生成页无感。

---

## 3. 后端统一(A)

### 3.1 build_view 统一签名

`workbench/server/x_surge.py` 的 `build_view`(现 L324-425)扩展为:

```python
def build_view(range_h: int = 24, sort: str = "surge", golden: bool = False,
               market: str = "", sector: str = "", min_followers: int = 0,
               finance: bool = False, limit: int = 100) -> dict:
```

| 参数 | 类型/默认 | 语义 | 现状 |
|---|---|---|---|
| `range_h` | int, 24 | 回看窗口小时数, 合法域 **1~48**(前端五档 1/6/12/24/48) | 已支持任意小时(`_fetch_window` 用 since 字符串), 只需钳位 `max(1, min(range_h, 48))` |
| `sort` | str, "surge" | 五选一, 见 §3.3 | 无此参(硬编码 surge 降序, L419) |
| `golden` | bool, False | 仅黄金窗口(发布≤2h) | 已有 |
| `market` | str, "" | 逗号分隔市场 chips, OR 语义 | 已有(L412-414) |
| `sector` | str, "" | **新增**, 逗号分隔 L1 赛道 chips, OR 语义 | 无(§3.4) |
| `min_followers` | int, 0 | 粉丝下限(前端只发 100000) | 已有, 行为细化见 §7.4 |
| `finance` | bool, False | 仅投资金融 | 已有(L417-418) |
| `limit` | int, 100 | 返回条数; `total` 仍返回筛选后全量 | 已有 |

### 3.2 行来源反转(本方案最关键的一处改动)

现状 L348: `for sid, s in eng["statuses"].items():` —— 以**快照库为主表**, 再去窗口元数据里 `meta.get(sid)`,
查不到就丢弃(L350-351)。后果: 没采过快照的 X 条目在页面上根本不存在, 需求 1/2 无法满足。

反转为主表=窗口条目、快照=可选 join:

```python
items = _fetch_window(range_h)                    # 全源条目, cursor 翻页(现 L98-117, 不改逻辑)
for it in items:
    m = _URL_RE.search(it.get("url") or "")
    if not m or not it.get("author_handle"):      # 全 X 口径: x.com 链接 + handle 非空, 不限池
        continue
    sid = m.group(2)
    s = eng["statuses"].get(sid)                  # 快照可选: None = 新入未采集
    series = (s or {}).get("series") or []
    last = series[-1] if series else None
    # likes/retweets/replies/views/growth/views_pred/reply_exposure/surge_parts
    #   全部允许 None(has_engage=False 时整组为 None);
    # surge 分量仍逐档计算(退化值), 但排序用 has_engage 门禁(§3.3), 展示不撒谎(§4.3)
    rows.append({... 现有字段 ...,
        "has_engage": bool(series),
        "sectors": it.get("sectors") or [],
        "sectors_l1": [str(x).split(">")[0] for x in (it.get("sectors") or [])],
        "growth_stale": ...,                      # §7.2
        "followers": followers_or_None,           # §7.4: 缓存 miss=None, 区别于真实 0
    })
```

- `handle` 来源从 `s["handle"]`(快照)改为条目 `author_handle`(更权威, 快照只作回退)。
- `reply_url` / `url`: 无快照时用条目自身 `it["url"]`(本来就是 x.com/handle/status/id 形态, L398 同构)。
- `meta` 扩充(全部筛选前统计, 沿用 golden_n 先例 L409): `x_total`(窗口内 X 条目总数)、
  `engaged_n`(其中有快照数)、`sectors_l1`(`[[L1, 条数]...]` 降序, 供前端赛道 chips, §5.2)、
  `sector_unlabeled_n`(无任何 sectors 的 X 条目数, §7.3)。

### 3.3 排序五选一与 None 沉底(任务书 A 的排序键定义)

| sort 值 | UI 文案 | 主键(降序) | None 判定(沉底条件) |
|---|---|---|---|
| `time` | 时间顺序 | `time`(条目发布时间, 字符串序即时间序) | 无——所有行必有 time, 正常参排 |
| `surge` | 起爆概率 | `surge`(0~100 四分量) | `not has_engage`(退化分不参排) |
| `growth` | 增速 | `growth_views_h`(浏览/时, 快照≥2 点才有) | `growth_views_h is None` **或** `growth_stale` |
| `views_pred` | 预测浏览 | `views_pred`(=views×(1+3/age) 封顶×4) | `views_pred is None`(即无 views) |
| `reply_exposure` | 评论曝光 | `reply_exposure`(=views×10%) | `reply_exposure is None`(同上) |

统一沉底实现(替代现 L419 单行排序):

```python
def _sort_key(r, sort):
    if sort == "time":
        return (0, "", -(r["_ts"] or 0))                    # 理论上不走这段
    v = {"surge":    r["surge"] if r["has_engage"] else None,
         "growth":   None if (r["growth_views_h"] is None or r["growth_stale"]) else r["growth_views_h"],
         "views_pred": r["views_pred"],
         "reply_exposure": r["reply_exposure"]}[sort]
    return (v is None, -(v or 0), -(r["_ts"] or 0))
rows.sort(key=lambda r: (r["time"] or ""), reverse=True) if sort == "time" \
    else rows.sort(key=lambda r: _sort_key(r, sort))
```

规则总结(写进响应 `meta.rule` 供前端展示):

1. **None 值一律沉底**, 沉底组内部按发布时间新→旧排(用户至少能看到"最新但没数据"的帖)。
2. 非沉底组内: 主键降序, 并列再按时间新→旧。
3. `surge` 的沉底判据是 `has_engage` 而非数值——无快照帖会算出退化 surge(如 0+0+时效20+0), 参排会
   冒充中等分, 必须门禁。
4. `growth_stale`(最后快照距今>45min, 即 30min 节奏下连续两轮没采到)在 growth 排序下视同 None 沉底,
   但字段照常返回、卡片照常显示(标注"滞后", §7.2)——避免拿 6 小时前的旧两点差冒充"当前增速"。
5. API 默认 `sort="surge"` 保持向后兼容; 两页的差异化默认由**前端**发参决定(§4.2), 后端不感知页面。

### 3.4 赛道(L1)筛选

- 已验证事实: 数据站 `/v1/items` 无 sectors 过滤参数(08 号方案 §1 已确认 store.query 无此入参),
  赛道筛选**只能在工作台层做**——与 market 筛选同模式(build_view 内存过滤), 不碰板块一。
- `sector` 参数: 逗号分隔 L1 名(如 `半导体,人工智能`), OR 语义: `any(l1 in r["sectors_l1"] for l1 in wants)`。
- L1 词表=封闭 19 值(taxonomy.py L103 `L1_L2`), 但 chips 不硬编码词表, 用响应 `meta.sectors_l1`
  (窗口内实际出现过的 L1 + 计数), 与 xMarketChips 取"实际覆盖"的现有做法一致(article.js L67-71)。
- 筛选顺序: golden → market → sector → min_followers → finance → sort → limit(现顺序 L409-419 插入 sector)。

### 3.5 range 1h~48h

- 服务端本来就吃任意小时; 需要做只有三件: ①钳位 1~48; ②`_fetch_window` 的 `max_pages` 按窗口放大
  (≤24h 维持 5 页, 48h 用 8 页——L98-100 注释实测过"新非 X 源挤掉 X 帖"的占位问题, 48h 窗口条目更多,
  5×1000 可能截断在 X 条目之前); ③CLI `refresh-x-surge --range` choices 从 `["24h","48h"]`
  放开到 `["1h","6h","12h","24h","48h"]`(cli.py L549-552)。
- 快照侧无需动: RETAIN_H=72 ≥ 48, 48h 窗口内的帖快照不会被保留策略先淘汰。

### 3.6 响应形状(before / after)

```jsonc
// after(新增/变化字段加注释, 其余不动)
{
  "items": [{
    "status_id": "...", "handle": "...", "name": "...", "followers": 0,   // followers 可为 null(§7.4)
    "time": "2026-09-03 14:05", "age_h": 1.2,
    "text": "原文≤200", "text_zh": "译文或null",
    "finance": true, "url": "https://x.com/...", "reply_url": "https://x.com/...",
    "markets": ["美股"], "dup_count": 1,
    "sectors": ["半导体>存储"], "sectors_l1": ["半导体"],                  // 新增
    "likes": 120, "retweets": 30, "replies": 45, "views": 50000,
    "growth_views_h": 800, "growth_likes_h": 2.1,
    "growth_stale": false,                                               // 新增
    "has_engage": true,                                                  // 新增
    "surge": 62, "golden": true, "views_pred": 90000, "reply_exposure": 5000,
    "surge_parts": {"growth": 32, "baseline": 18, "decay": 10, "abs": 2}
  }],
  "total": 87, "golden_n": 12, "no_baseline": 9,
  "meta": {
    "data_age_min": 14, "tracked": 1200, "updated_at": "...",
    "x_total": 340, "engaged_n": 210,                                    // 新增
    "sectors_l1": [["宏观", 90], ["半导体", 44]], "sector_unlabeled_n": 31, // 新增
    "sort": "growth",                                                    // 新增(回显)
    "rule": "surge=增速40+破圈30+衰减20+绝对量10; 评论曝光≈views×10%; 黄金窗口≤2h; 无快照条目在指标排序下沉底"
  }
}
```

### 3.7 `/wb-api/recommend` 与 `/wb-api/x-hot` 的退役方式

两页合并后推荐页改调 `/wb-api/x-surge`, recommend/x-hot 失去调用方。退役走"两版清场":

| 版本 | 动作 |
|---|---|
| 本版 | ① `app.py` 删 `reco`/`xhot` import(L21); ② `/wb-api/recommend`(L141-150)与 `/wb-api/x-hot`(L153-158)
函数体替换为一行桩: `return JSONResponse({"error": "已退役: 推荐信息/热帖榜已并入 /wb-api/x-surge(图文页 X 化统一, 见 docs/workbench-moa/15)", "deprecated": True}, status_code=410)`;
③ 删除 `workbench/server/reco.py`、`workbench/server/xhot.py` 两个文件;
④ 前端同版切到 /x-surge(article.js 与后端同仓同发) |
| 下个清理版 | 删两个 410 桩路由 |

为什么留 410 桩而不是直接删路由: `app.py` L244-250 的 no-cache 中间件说明团队已被 webview 缓存旧 JS
咬过——旧 `article.js` 若从缓存复活, 会调 /recommend; 404 会被前端 `catch` 显示"推荐接口不可用"
(L131), 410 + hint 则能自解释。桩成本两行, 买一个版本的容错, 值。

`reco.py` 删除连带项盘点: `score_of`/`recommend` 无其他引用(grep 全仓仅 app.py L21/L146);
`_TRUSTED_POS` 的"双标签制 positioning"口径在 xaccounts/news 页另有实现, 不受影响。
`xhot.py` 的"每账号限 2 条"多样性规则**不迁移植入** surge 榜(起爆排序天然分散, 加限反而伤害排序语义;
若未来评论区反馈大号霸榜, 作为独立迭代加 `per_handle_cap` 参数)。

---

## 4. 两子页的产品差异化定义(B)

两页数据同源、筛选同套、互动行同款——差异化必须落在"默认值 + 主动作 + 卡片左区"三处实体差异上,
并给出防换皮自检。

### 4.1 定位一句话

- **推荐信息 = "读什么"**: 信息发现流。回答"我的 X 时间线上刚发生了什么值得看的"。
  心智是"刷", 核心体验是时间顺序的密度与新鲜度。
- **蹭蹭流量 = "现在蹭哪条"**: 行动榜。回答"哪条帖此刻去评论/引用, 我的曝光收益最大"。
  心智是"抢", 核心体验是起爆概率、黄金窗口倒计时和一键跳转评论框。

### 4.2 默认值矩阵(差异的主体)

| 维度 | 推荐信息 | 蹭蹭流量 |
|---|---|---|
| 默认排序 | **时间顺序**(time)——资讯流第一性是新鲜 | **起爆概率**(surge)——行动榜第一性是收益 |
| 默认时间范围 | **近12小时**——X 原生内容高频, 12h 已厚; 更短窗口"刷"不完就翻页 | **近1天**(24h)——增速/基线需要足够历史, 窗口太短全是"攒基线中" |
| 默认筛选 | 全不选(全量 X 流) | 全不选; "仅黄金窗口"只作显式筛选+徽章, 不默认开(默认开会把页面切成"几乎总是 3 条"的空态) |
| 主动作 | **＋加入素材**(送素材池, 契约不变) | **去评论 ↗**(跳原帖回复) |
| 次动作 | 去评论 ↗(弱化, 普通链接样式) | ＋加入素材(次级样式) |
| 左菜单角标 | `total`(窗口内 X 条目数, 语义="有多少可读") | `golden_n`(黄金窗口帖数, 语义="现在有几条能蹭", 沿用现状 L84) |
| 卡片左区 | **账号档案框**(沿现 reco 左框 L436-444: 账号名/handle/定位/市场徽章/简介——读的场景需要判断信源可信度) | **起爆概率大数字 + 黄金窗口徽章**(沿现 surge 左栏 L547-551——动的场景需要一眼看到收益) |
| 排序行内提示 | 无 | 沉底条目组顶部一行 muted 分隔:"以下 N 条暂无互动数据(攒基线中), 按时间排列" |
| 空态文案 | "窗口内暂无 X 内容 —— 放宽时间或清掉筛选" | 沿现状(L541-542)+ 提示跑 `refresh-x-surge` 两轮起增速 |

### 4.3 卡片解剖: 一条统一互动行 + 两个差异区

统一互动行(需求 3, 两页完全一致, 数据全来自统一行字段):

```
👍 1.2万  🔁 3400  💬 456  👁 5.0万 │ 增速 800/时 │ 预测浏览 9.0万 │ 评论可蹭 ~5000 曝光
构成: 增速32 + 破圈18 + 衰减10 + 绝对量2
```

- 四件套取 `likes/retweets/replies/views`, 空值 `fmtN` 现有逻辑已渲染"—"(L200-205), 不改。
- 增速: `growth_views_h != null` 显示绿色增速, 否则"增速 —(攒基线中)"; `growth_stale` 追加"(滞后)"。
- 预测/曝光: null 时整段隐藏(现 L571-572 行为)。
- 构成行: 有快照才显示; 无快照显示"互动数据采集中, 暂无构成"。

卡片三段式(两页共享 中/下 段, 差异在 左区 与 动作区):

```
┌─[推荐信息页]──────────────────────────┐  ┌─[蹭蹭流量页]────────────────────────┐
│ 左区: 账号档案框        │ 账号名 @handle  │ 左区: 62% 起爆概率      │ #3 账号名 @handle │
│  (名/handle/定位/市场/简介)│ 时间·赛道·市场 │  [黄金窗口]             │ 时间·赛道·市场     │
│───────────────────────────────────│  │───────────────────────────────────│
│ 中区(共享): text_zh||text 正文(展开/收起)           中区(共享): 同左                  │
│ 下区(共享): 统一互动行 + 构成行                                                     │
│ 动作区: [＋加入素材] [原文链接↗]      │  动作区: [去评论↗] [＋加入素材] [已加入✓]   │
└───────────────────────────────────┘  └───────────────────────────────────┘
```

赛道/市场徽章进中区标签行(共享 `visibleSectors/sectorParts/sectorsRest` 现有方法 L144-150,
surge 卡片现缺赛道徽章, 一并补齐——需求 5 "标签同一套"的展示侧)。

### 4.4 防换皮自检(合并后验收时逐条打勾)

1. 两页默认排序不同(time vs surge), 切到对方默认排序后内容序列明显不同。
2. 两页默认范围不同(12h vs 24h), 各自空态/密度合理。
3. 主动作不同且位置第一(加入素材 vs 去评论), 左区信息结构不同(档案 vs 概率)。
4. 左菜单角标语义不同(可读量 vs 可蹭量)。
5. 推荐页没有任何"起爆/曝光"字眼承担导航职责(只随互动行展示), 蹭蹭页没有任何"档案简介"区块。

若四条里任意两条不成立, 说明做成了换皮, 打回 §4.2 调默认。

---

## 5. 前端改造清单(C)

范围: 仅 `workbench/web/js/pages/article.js`(839 行)+ `workbench/web/css/app.css` 少量。Vue 3 选项式,
不引构建步骤, 不动 `app.js` 壳层。

### 5.1 状态与加载器合并(最小 diff 方案)

现状三套互不相干的状态(`recoSince/recoMarkets/recoSort/...` L19-23, `xhot*` L26, `surge*` L28-29)
+ 三个 loader。合并为**每页一份筛选状态 + 一份结果桶 + 一个参数化 loader**:

```js
/* data() */
rangeOpts: [["1h","近1小时"],["6h","近6小时"],["12h","近12小时"],["24h","近1天"],["48h","近2天"]],
sortOpts:  [["time","时间顺序"],["surge","起爆概率"],["growth","增速"],
            ["views_pred","预测浏览"],["reply_exposure","评论曝光"]],
feed: {                       // 每子页一份: 筛选状态 + 结果(互不串味, 天然支持"两页不同默认")
  reco:  { range:"12h", sort:"time", markets:[], sectors:[], golden:false,
           big:false, fin:false, items:[], total:0, meta:{}, loading:false, err:"" },
  surge: { range:"24h", sort:"surge", markets:[], sectors:[], golden:false,
           big:false, fin:false, items:[], total:0, meta:{}, loading:false, err:"" },
},
```

```js
/* methods: 唯一 loader, 两页共用 */
async loadFeed(pg) {
  const f = this.feed[pg]; f.loading = true; f.err = "";
  try {
    const p = new URLSearchParams({ range: f.range, sort: f.sort });
    if (f.golden)  p.set("golden", "1");
    if (f.big)     p.set("min_followers", "100000");
    if (f.fin)     p.set("finance", "1");
    if (f.markets.length) p.set("market", f.markets.join(","));
    if (f.sectors.length) p.set("sector", f.sectors.join(","));
    const d = await WB.api.get("/x-surge?" + p.toString());
    f.items = d.items; f.total = d.total; f.meta = { ...(d.meta||{}), golden_n: d.golden_n };
  } catch (e) { f.err = e.error || "接口不可用"; }
  f.loading = false; this.registerSubs();
},
toggleChip(pg, group, val) { /* 数组组 toggle + loadFeed(pg); 布尔组同构 */ },
```

删除项: `loadReco/recoToggle/loadXHot/toggleXhotMarket/loadSurge/toggleSurgeMarket/sinceValue/
scoreParts`(后两者被组件/接口替代), `reco*/xhot*/surge*` 全部散状态, `tagEnums`(定位/类型 chips
随价值分一起退役——X 统一口径下这两个标签组不再出现)。
保留项: `basketIds/initBasketIds/addToPool(改写,见5.5)/sectorParts/visibleSectors/sectorsRest/
fmtN/fmtFol/sentimentBadge(资讯页共用? 本页已无情绪来源, 可删)/xMarketChips/positive body 展开 族`。

### 5.2 排序 switch 与赛道 chips

- 五选排序: 两页工具栏各渲染一组 radio, `v-for="[v,t] in sortOpts"` + `v-model="feed[pg].sort"`
  + `@change="loadFeed(pg)"`——一行模板, 无 switch 语句, 后端承担全部排序语义(§3.3)。
- **赛道 chips 数据来源决议: 用响应 `meta.sectors_l1`(服务端在筛选前统计), 不用 /wb-api/stats。**
  理由: ① chips 必须在"已选中某赛道"时仍列出其他赛道(否则自过滤后 chips 消失),
  从返回行聚合做不到(返回行已被 sector 过滤)——meta 统计发生在过滤前, 正确;
  ② `/stats` 的 `sectors_l1`(stats.py L105)是**全库全源**口径, 含非 X 条目、窗口与当前页不一致,
  还多一次全量拉取(虽有 60s 缓存); ③ `meta.sectors_l1` 与 golden_n 同一先例(x_surge.py L409),
  零额外请求、口径与当前窗口严格一致。stats.sectors_l1 保留不动(资讯页/看板还要用)。
- 市场 chips 沿用 `xMarketChips`(池账号覆盖市场, L67-71); 两页共用同一组(现状已如此)。

### 5.3 互动行局部组件(卡片复用的最小方案)

Vue 3 选项式支持组件内 `components` 局部注册, 不需要动 app.js:

```js
/* WB.pages.article 内新增 */
components: {
  "x-eng-line": {
    props: ["r"],
    template: `
      <div>
        <div class="surge-stats">
          <span>👍 {{ $root.fmtN(r.likes) }}</span><span>🔁 {{ $root.fmtN(r.retweets) }}</span>
          <span>💬 {{ $root.fmtN(r.replies) }}</span><span>👁 {{ $root.fmtN(r.views) }}</span>
          <span v-if="r.growth_views_h != null" class="grow">增速 {{ $root.fmtN(r.growth_views_h) }}/时<template v-if="r.growth_stale">(滞后)</template></span>
          <span v-else class="muted">增速 —(攒基线中)</span>
          <span v-if="r.views_pred != null">预测浏览 {{ $root.fmtN(r.views_pred) }}</span>
          <span v-if="r.reply_exposure != null" class="exposure">评论可蹭 ~{{ $root.fmtN(r.reply_exposure) }} 曝光</span>
        </div>
        <div class="surge-parts muted" v-if="r.has_engage">
          构成: 增速{{ r.surge_parts.growth }} + 破圈{{ r.surge_parts.baseline }} +
          衰减{{ r.surge_parts.decay }} + 绝对量{{ r.surge_parts.abs }}</div>
        <div class="surge-parts muted" v-else>互动数据采集中, 暂无构成</div>
      </div>`,
  },
},
```

(若 `$root` 取法与壳层挂载方式不合, 退一步把 fmtN 挂到组件 methods 内联, 8 行复制, 不强求。)
两页模板各自保留 `<v-for>` 卡片循环(布局本就要求不同, §4.3), 中区正文/标签行与下区
`<x-eng-line :r="row">` 逐字同构; 后续改互动行只动组件一处。

### 5.4 右栏 X 热帖榜: 删; xhot.py: 退役

- 推荐页双栏 `.reco-cols`(L397)收为单栏信息流, 右栏 `reco-rail` 卡(L483-511)整块删除。
- 理由: 热帖榜的存在理由(xhot.py L3-11 自述"真流量字段缺失, 用 dup+粉丝代理")已被 x_surge
  时序快照彻底满足; 榜单能力=蹭蹭页本身(sort=surge 即热帖榜)。两页合并后再挂第三个榜只会
  稀释定位。
- `xhot.py` + `/wb-api/x-hot`: 按 §3.7 两版清场。多样性规则("每账号限2条")不迁移(§3.7)。
- CSS: `.reco-cols/.reco-rail/.xhot-item/.xhot-top/.rank/.xhot-text/.xhot-meta` 中仅右栏使用的类删除;
  **`.xhot-fol` 保留**(surge-top 在用, L559); `.surge-grid/.surge-rank/.prob` 等不动。

### 5.5 素材池写入统一(契约不变)

- 现 `addToPool(it)`(推荐, L151-156, id=条目 md5)与 `addSurgeToPool(r)`(surge, L206-211,
  id=status_id)合并为一个 `addToPool(row)`: 统一 `id=row.status_id`——两页同源后同一帖在两页
  必须是同一素材(重复加入互相识别"已加入 ✓"), id 域一致是前提, 顺带修正了旧行为里
  "同一 X 帖从两页加入会变成两个素材"的隐患。
- 五字段 `{id, time, source, text, url}` 逐字保持(契约不变): `source=name`(X· 前缀已剥),
  `text=row.text`(≤200 服务端已截), `url=row.reply_url`(与现 surge 写入一致)。
- localStorage 里旧 md5 id 素材不受影响(不同域不冲突, 现注释 L206 同款结论), 生成页零改动。

### 5.6 registerSubs / mounted

- `registerSubs`(L75-97): reco 角标 `cnt: this.feed.reco.total || ""`; surge 角标不变
  (`feed.surge.meta.golden_n`)。
- `mounted`(L383-390): `this.loadFeed("reco"); this.loadFeed("surge")` 替代 loadReco/loadXHot/loadSurge;
  `loadDict`(市场词表)与 `loadX`(账号档案)保留。

---

## 6. collect 采样是否随"全 X"扩大(D)

### 6.1 现状容量账

- 单轮上限 `limit=250`(cli.py 默认, x_surge.py `collect` L167), 调度 30min/轮 → 名义 1.2 万次/日
  抓取容量; 单帖冷却 20min → 单帖实际采样频率 ≤ 每 30min 一次, 72h 最多 ~144 点 > MAX_POINTS 96, 够。
- 候选生成 `_fetch_candidates`(L120-136): 窗口内**全 X**(本就不限池)按时间新→旧排序后**截 250**。
- 存储: MAX_STATUSES=2000 帖硬顶 + 72h 保留(L30-32); 2000/3 天 ≈ **667 帖/天**的稳态容纳量,
  超出按"最久未更新"淘汰(L87-90)。

### 6.2 全 X 口径的三个压力点

1. **窗口截断饥饿(现有缺陷, 合并后被放大)**: `collect` 先把候选截到 250(L136), **然后**才过滤
   冷却期(L173-178)。一旦窗口内 X 条目 >250, 一轮里 250 个名额可能大部分被"冷却中"的旧候选占掉,
   新帖反而进不了本轮——全 X 后库内 X 条目变多, 此缺陷从偶发变常态。
2. **2000 帖硬顶挤出**: 池内 131 账号时代日增 X 帖大概率 <667; 全 X(含数据站聚合到的任意
   author_handle)后可能触顶 → 视图窗口(48h)内的帖被淘汰, 用户看到"闪没"的行。
3. **FxTwitter 429**: 每轮 250 请求、并发 4, 已有全局熔断(L189-191); 扩量线性放大 429 概率。

### 6.3 采样策略决议

| 项 | 决议 |
|---|---|
| 默认 limit | **250 不动**。先量化再扩量: `collect` 报告新增 `x_window`(窗口内 X 条目总数, `_fetch_candidates` 里顺手可得)与现有 `todo/skip_cooldown` 跑一天观察 |
| 饥饿缺陷 | **必修**: 冷却过滤前移到截断之前(`_fetch_candidates` 接收 `eng`, 冷却中的不占 250 名额), 等效单轮新增覆盖 = min(新帖数, 250) |
| 扩量触发器 | 连续 3 轮 `x_window - skip_cooldown > 220` → `--limit` 默认提到 400(429 由熔断兜底, 熔断轮次顺延即可); `tracked > 1800` → MAX_STATUSES 2000→4000(粗估文件 ≤10MB 量级, 原子写照旧) |
| 采样优先级 | 维持"新→旧"(L134-135), 不引入粉丝加权——黄金窗口帖天然最新, 排序天然照顾 |
| 二采优先 | 增补: 同轮内只有 1 个快照且 age≤2h 的候选排前面(先给新鲜帖攒出第二点, growth 才能成形); 实现为排序 key 加一维, 5 行内 |

### 6.4 翻译随行策略

- 维持"翻译候选 = 当轮采集候选"(`collect` L217 调 `translate_pending(cands)`), 每轮上限 60、
  `zh_native` 免翻判定、未配置静默跳过——全 X 后候选变多但机制不变, 欠账靠后续轮次自然消化
  (冷却跳过的候选仍进 `cands`, 会反复补翻尝试, 直到出窗)。
- 已知尾部风险: 出窗前一直排不进当轮候选的帖不会被翻译。可接受(译文只是增强, `text_zh` 为 null
  时卡片回退原文); 可选 P2 优化: `translate_pending` 按 `eng` 里 views 降序挑欠账 Top-N, 让高曝光
  帖优先有译文。
- 译文缓存不淘汰, 只存 `{sid: {zh, ts}}`, 增长为文本级, 无需治理。

---

## 7. 边界行为定义(E)

### 7.1 无互动快照的条目(新入未采集)

- 出现: 照常出卡(行来源反转后天然覆盖, §3.2)。
- 排序: `time` 正常参排; `surge/growth/views_pred/reply_exposure` 四种一律沉底
  (§3.3 None 判定; surge 走 has_engage 门禁, 退化分不参排)。
- 展示: 互动四件套显示"—"(fmtN 现行为), 增速"攒基线中", 无构成行(§4.3)。
- 动作: 不受影响——推荐页可加入素材(读文本不需要互动数据), 蹭蹭页"去评论↗"依然成立
  (reply_url 来自条目本身)。
- 生命周期: 下一轮 `refresh-x-surge` 采到首点后 has_engage=true; 两轮后(≥5min 间隔)出增速。

### 7.2 增速滞后(有快照但太久没更新)

- 判定: `now - last.ts > 45min`(30min 节奏下连续两轮没采到; 采样饥饿修复后应罕见, 多因 429 熔断)。
- 行为: `growth_views_h` 照常返回显示并加"(滞后)"; growth **排序**下沉底(§3.3 规则 4)——
  旧两点差/旧 span 是过期速率, 排进"当前增速榜"会误导卡位决策; surge 是分量合成(时效衰减项
  本来就罚旧帖), 不额外处理。

### 7.3 赛道未打标条目

- 筛选开启(任选了 L1 chip): **严格滤除**未打标条目——用户点了"半导体", 混入 31 条无赛道帖是噪音;
  等价于"该 chip 语义 = sectors_l1 包含所选"。
- 透明度: `meta.sector_unlabeled_n` 返回; 前端在赛道 chips 行尾追加灰 chip `未打标 N`(只读, 不可点),
  让用户知道滤掉了多少。若 N 占比异常高(说明板块一打标覆盖差), 提示语指向板块一, 不在工作台补标
  (工作台只读红线)。
- 筛选未开启: 未打标条目正常出现, 卡片赛道徽章位留空(不显示"无赛道"占位)。

### 7.4 非池账号粉丝数缺失(破圈分 + "粉丝≥10万"筛选)

- 语义修正: `x_profiles.json` 只覆盖池账号(enrich CLI L146-147 显式限制在池内), 非池 handle 必然
  miss。现状把 miss 当 `followers=0` → `fbase=max(0,1000)=1000`(L378), 对真实几十万粉的未建档大号,
  破圈度 `views/1000` 被放大几十倍、S2 直接打满 30——**排序被系统性扭曲**, 必须改为:
  - 缓存 miss → `followers=None`: S2(破圈)记 0 分(保守, 宁漏勿滥), `rate_norm` 同理 S1 记 0;
    前端粉丝位显示"粉—?"。
  - 缓存命中但值为 0(查无此号/新号): 维持 fbase=1000 地板(真 0 粉号用地板是合理保守)。
  - `min_followers` 筛选: followers=None 一律**排除**(严格口径, 与 §7.3 一致: 用户点了"≥10万",
    不知道粉丝数的帖不该混入)。
- 补档通路(P2, 可独立后续): `enrich-x-profiles --handles` 放开"必须在池内"限制(允许任意 handle),
  并在 `collect` 报告里列出快照库中无档案的 handle Top-N, 引导一次性补档。补上后这些帖自动
  参与 S1/S2 与筛选, 无需改本方案结构。

### 7.5 其他

- 数据站不可用: `_fetch_window` 抛 UpstreamError → 现有路由 catch 转 502(app.py L169-170), 前端
  err 框照旧; 不做"纯快照降级视图"(快照无 meta 无法组行, 且 60s 窗口缓存已缓解抖动)。
- 快照文件损坏: `load_engage` 当空库重来(L50-51)→ 全部行 has_engage=false, time 排序仍可用,
  指标排序空态——可接受, 不加特判。
- 快照库为空(新环境): 同上, 空态文案已引导跑两轮 CLI(L541-542)。

---

## 8. 落地步骤(F, 文件级)

单 PR 可交付(前后端同仓同发), 步骤按依赖排序:

| # | 文件 | 动作 | 内容 |
|---|---|---|---|
| 1 | `workbench/server/x_surge.py` | 改 | ① 行来源反转(§3.2) + 统一行新增字段; ② `build_view` 加 `sort`/`sector` 参, `_sort_key` + 钳位(§3.1/3.3); ③ meta 扩充(§3.6); ④ followers=None 语义(§7.4); ⑤ `_fetch_candidates` 冷却过滤前移 + `x_window` 观测 + 二采优先(§6.3); ⑥ 48h 时 max_pages=8(§3.5) |
| 2 | `workbench/server/app.py` | 改 | `/wb-api/x-surge` 透传 `sort`/`sector`(L161-170); `/wb-api/recommend`、`/wb-api/x-hot` 改 410 桩; 删 `reco`/`xhot` import(L21) |
| 3 | `workbench/server/reco.py` | 删 | 整文件(价值分退役) |
| 4 | `workbench/server/xhot.py` | 删 | 整文件(热帖榜退役) |
| 5 | `workbench/web/js/pages/article.js` | 改 | §5 全部: feed 状态与 loadFeed、五选排序与六组筛选 chips(含赛道)、x-eng-line 组件、两页卡片模板改写、右栏删除、素材写入统一、registerSubs/mounted 调整、删除废弃方法与 tagEnums |
| 6 | `workbench/web/css/app.css` | 改 | 删右栏专属类(§5.4); 新增沉底分隔行样式(一个 muted 类, 复用现有即可则零新增) |
| 7 | `cli.py` | 改 | `refresh-x-surge --range` choices 放开至五档(L549-552); help 文案同步 |
| 8 | `docs/` | 记 | 本方案落 `docs/workbench-moa/15-cursor-xtwin.md`(即本文); 12/13 号文中被取代章节不加改(历史存档), 在文首加一行"部分被 15 号取代"指针即可 |

回滚单元: 整 PR revert 即回到双引擎现状; 数据文件(x_engagement/texts/profiles)向后兼容
(只增字段不迁移), 回滚不丢数据。

---

## 9. 验证清单(F)

### 9.1 后端(数据站 + 工作台双服务起, curl)

```
python cli.py sources serve &  python cli.py workbench serve
# ① 五种排序各拉一次, 校验首行主键确实降序、None 沉底(响应里 has_engage=false 的行全在尾部)
curl 'http://127.0.0.1:8788/wb-api/x-surge?range=24h&sort=time'
curl '...&sort=surge' / sort=growth / sort=views_pred / sort=reply_exposure
# ② 全 X 口径: 响应每行 url 匹配 x|twitter.com 且 handle 非空; 对照数据站 /v1/items 窗口内
#    X 条目数 == meta.x_total(不受快照库限制)
# ③ 筛选: sector=半导体 只出 sectors_l1 含半导体; market/golden/min_followers/finance 组合
# ④ 赛道 meta: sectors_l1 计数和 + sector_unlabeled_n == x_total
# ⑤ 退役桩: /wb-api/recommend、/wb-api/x-hot 返回 410 + deprecated hint
# ⑥ 边界注入: 暂改名 x_engagement.json → sort=time 仍有数据、其余 sort 全沉底; 恢复
# ⑦ 采集: python cli.py workbench refresh-x-surge --range 6h 跑两轮, 第二轮出 growth;
#    报告含 x_window; 构造 >250 候选(48h)时冷却帖不占名额(对比修复前后 todo 构成)
```

### 9.2 前端(手测)

- [ ] 推荐页: 只见 X 账号卡; 默认"时间顺序+近12小时"; 主动作"＋加入素材"; 无价值分徽章/规则行/定位类型 chips; 右栏消失, 单栏流。
- [ ] 蹭蹭页: 默认"起爆概率+近1天"; 沉底组有分隔提示行; 卡片含完整互动行+构成; "去评论↗"+黄金徽章在。
- [ ] 两页各切五种排序、五档范围、全部筛选 chips, 组合无报错; 赛道 chips 出现且选中后不消失(含"未打标 N"灰 chip)。
- [ ] 素材池: 推荐页加入 → 蹭蹭页同帖显示"已加入 ✓"(同 status_id); 生成页素材池可见、字段完整; 旧素材(早前加入)不丢。
- [ ] 左菜单角标: reco=total, surge=golden_n, 数字随筛选变化。
- [ ] 无快照条目卡: 四件套"—"、攒基线中、无构成行、动作可用。
- [ ] 强刷(Ctrl+F5)后无 console 报错; 旧缓存 JS 调 /recommend 得到 410 时 err 框文案可读。

### 9.3 回归

- [ ] 资讯页素材篮、生成页、`/wb-api/stats`(sectors_l1 仍在)不受影响。
- [ ] `python cli.py workbench status --json` 通过; doctor 不报工作台缺文件。
- [ ] 全仓 grep: `reco.` / `xhot` / `score_parts` / "价值排序" 零残留(app 桩内提示文案除外)。

---

## 10. 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| 全 X 后 surge 榜混入大量低质非池帖(刷量号/广告号) | 中 | S1/S2 以粉丝为基线, 无档案号计 0 分自然沉底(§7.4); 后续可加"仅关注池"一键 chip(池账号表已有, 一次性参数, 不在本期) |
| FxTwitter 429 频发导致增速普遍滞后 | 中 | 熔断已有; growth_stale 沉底保证榜面诚实(§7.2); 扩量触发器(§6.3)留有余量 |
| webview 旧缓存 JS 调已退役接口 | 低 | 410 桩一版(§3.7); no-cache 中间件已在 |
| 推荐页失去非 X 内容被诟病"信息变少" | 低 | 产品拍板即口径(需求 1); 非 X 内容仍在资讯页完整可用, 推荐页定位改为"X 时间线精选" |
| 赛道打标覆盖低导致赛道筛选名存实亡 | 低 | sector_unlabeled_n 透明化(§7.3); 打标覆盖属板块一议题, 工作台不越界 |

## 11. 不做清单(Non-goals)

- 不做自动评论/自动发帖(发布红线, 13 号方案已定性)。
- 不动 `global-news-sources/` 任何文件(含 /v1/items 加 sectors 参数的诱惑——工作台层过滤已够)。
- 不迁移 xhot 的"每账号限 2 条"多样性规则(§3.7)。
- 不做排序的多键组合(五选一单键 + 沉底规则已覆盖需求; 组合排序等真实反馈)。
- 不改 WB.basket 契约与生成页任何逻辑。
- 不在本期扩 `--limit` 到 400(先观测, §6.3 触发器说话)。
