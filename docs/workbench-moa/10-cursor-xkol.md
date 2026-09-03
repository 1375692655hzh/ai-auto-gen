# 10-cursor-xkol — 工作台 X(Twitter) KOL 条目按账号展示优化实施方案

> 岗位：方案设计岗（cursor）。**只出计划，不动代码。**
> 日期：2026-09-03。产出文件仅本篇。
> 范围：只改 `workbench/` + 新增 `scripts/enrich_x_profiles.py` + `index.html` 资源版本号 bump；可只读 `global-news-sources/config/twitter_pool.yaml`（及 gitignored 的 `twitter_pool.local.yaml`）。
> 红线：不改 `global-news-sources/` 任何文件；workbench 对三板块只读；唯一写口 `data/workbench/*.json`（本期新增 `x_profiles.json`）。服务器运行时不调外部 CLI。
> 现有修复不得回退：`registerSubs` 路由守卫、双框 `.nc-grid`、赛道分层徽章、筛选区五组、定位分布卡。

---

## 0. 名词与范围

| 名词 | 含义 | 权威位置 |
|---|---|---|
| X 池 | 131 个账号的 yaml 清单，被两个源入口共享 | `global-news-sources/config/twitter_pool.yaml` |
| flash 入口 | `twitter_kol_flash`，role∈{media,data_bot,company,breaks}，实测 34 账号 | `builtin.py` L144-148；`basic.py` L316 |
| views 入口 | `twitter_kol_views`，role∈{analyst,trader,kol,insider}，实测 97 账号 | `builtin.py` L151-155；`basic.py` L317 |
| 源对象 | `/v1/sources` 的 110 条注册表行（`@source` 计数 110） | `sources/builtin.py`；`serve.py` L132-140 |
| 账号对象 | 池 yaml 的一条 `accounts[]` | 字段见 §2 |
| 条目 | `/v1/items` 一行；X 条目带 `author_handle` / `author_role` / 账号级 `markets` | `store.py` `_COLS` L36-43；fetcher 写出 L439-448 |
| 录入信息 | 池 yaml 已有：name / handle / role / markets / note / homepage / tier / priority | 不依赖 grok |
| 增强信息 | grok 补的 bio / followers / verified / location | 缓存 `data/workbench/x_profiles.json` |

前端只打同源 `/wb-api/*`（`api.js` L9）。`/wb-api/v1/*` 是纯 GET 代理（`app.py` L30-32 → `proxy.forward`），**里面没有账号级对象**。必须另开 workbench 自有端点读池文件。

---

## 1. 现状审计（已读码，行号为工作区当前文件）

### 1.1 池与抓取（只读确认，本期零改）

`global-news-sources/fetchers/basic.py`：

| 行号 | 现状 | 判断 |
|---:|---|---|
| 311-318 | 注释写明两源共用池；`TW_POOL_DEFAULT` 指向 `config/twitter_pool.yaml`；`TW_ROLE_FLASH` / `TW_ROLE_VIEWS` 分流 | 与 builtin 装饰器一致 |
| 349-362 | `fetch_twitter_kol(conf, mode)`；`pool_file` 可覆盖默认路径；文件缺失抛配置故障 | workbench 读池时用同一默认路径 |
| 363 | `yaml.safe_load` 读主池 | workbench 同样用 PyYAML |
| **364-381** | **本机 `twitter_pool.local.yaml` 合并**（详见 §2） | 端点必须复刻，不能只读主文件 |
| 439-448 | 每条推文写出 `source: "X·{name}"`、`author_role`、`author_handle`、账号级 `markets`、`lang`；正文 `text` 以 `@handle: ` 为前缀 | 条目侧已有按账号区分的字段；**资讯页左框没用上** |
| 440 | `text = "@{screen_name}: {推文}"` | 右框正文自带 @handle；左框再画 `.who` 会三重重复（源名池级 + .who + 正文前缀） |

`global-news-sources/sources/builtin.py` L144-155：两个源的 **title** 是池级长名：

- flash：`X大V快讯(FxTwitter免登录池·媒体官号/数据平台/官方机构)`
- views：`X大V观点(FxTwitter免登录池·分析师/交易员/KOL/内部人士)`

`global-news-sources/sources/tags.py` L31-32：源级 **brief** 同样是池级入口说明；源级 **markets** 是全池覆盖 `[全球, 美国, 台湾, 日本, 韩国, 土耳其]`（6 个，缺 A股/香港）。这正是左框 6 枚市场徽章的数据源。

`global-news-sources/sources/taxonomy.py` L57-61：`ROLE_TO_POSITIONING` 把 media→新闻源、data_bot/breaks→快讯源、company→机构、analyst/trader/kol/insider→大V。条目 `positioning` 已按账号 role 派生（`store.py` L273-281），与源对象上的「大V」不是一回事。

`global-news-sources/sources/store.py`：

| 行号 | 现状 | 判断 |
|---:|---|---|
| 41 | `_COLS` 含 `author_role` / `author_handle` | `SELECT *` 会随行返回，前端不用白名单 |
| 286 | 入库 `source` 优先用条目自带值（即 `X·显示名`） | 图文页 `it.source` 已是账号名 |
| 441-473 | `query()` 的 `sources` 参数 = **source_id IN (...)**，没有 `author_handle` 过滤 | 右栏点账号不能走 `f.sources` |
| 482-484 | `q` 拆词后对 `text` / `text_zh` / `title_zh` 做 `LIKE AND`，**不搜 author_handle 列** | 因正文以 `@handle:` 开头，`q=handle` 多数能命中，但会误伤「别人推文里提到该 handle」 |

`global-news-sources/sources/serve.py` L132-140 / L150-179：`/v1/sources` 只出 110 源；`/v1/items` 的 `sources=` 是源 id。**loadDict 的字典里没有账号级对象。**

`global-news-sources/config/twitter_pool.yaml`：131 条 `- handle:`，131 条 `note:`（录入简介全覆盖）。role 分流 34 flash + 97 views。本机 `twitter_pool.local.yaml` 当前仓库内不存在（`.gitignore` L50），但合并规则仍必须实现。

### 1.2 工作台后端

`workbench/server/app.py`（233 行）：

| 行号 | 现状 | 判断 |
|---:|---|---|
| 30-32 | `/wb-api/v1/{path:path}` 纯代理 | 保留；账号字典不能塞进这条 |
| 35-40 | `/wb-api/stats` | 可加 `top_x_accounts`（见 §4.A） |
| 130-139 | `/wb-api/recommend` | 条目原样打分返回，含 `author_*`；图文页能拿到 handle |
| 214-219 | 非 `/wb-api` 静态 `Cache-Control: no-cache` | 仍需 bump `?v=` |
| 无 | 没有 `/wb-api/x-accounts` / `/wb-api/x-profiles` | 本期新增 |

`workbench/server/stats.py`（108 行）L62-65、L101-102：`top_sources` 按 `source_id` 聚合，名称取条目 `source` 的 setdefault。X 两条会因产量高占满「产量最高的源」前两名，且 **lab 显示的是某条 `X·某账号名`，key 却是池级 source_id**——点条形图会按整个池过滤，和标签语义错位。

`workbench/server/config.py` L16-19：`DATA_DIR = <repo>/data/workbench`，已有 `settings.json` / `tracked_accounts.json` / `drafts.json` / `automation.json` 的原子写。增强缓存跟这个目录走。

`workbench/server/views.py`：已有「只读扫三板块文件、不 import 引擎」先例（L42-56 用正则读 `workflow.yaml`）。本期读池 yaml **允许用 PyYAML**（项目已依赖 `global-news-sources/requirements.txt` L2 `pyyaml>=6.0`），但 **禁止 `import fetchers.basic`**（AGENTS.md：不直接 import 内部模块驱动操作；合并逻辑在 workbench 侧复刻）。

`workbench/server/proxy.py` L21-32：只转发 GET。新端点不走 proxy，直接读本地文件。

工作台无独立 `requirements.txt`；`python cli.py workbench serve`（`cli.py` L293-296）与 sources 同一 Python 环境，PyYAML 已随板块一依赖安装。缺库时端点返回 500 + hint，不新增依赖文件。

### 1.3 资讯页 `workbench/web/js/pages/news.js`（525 行）

| 行号 | 现状 | 判断 |
|---:|---|---|
| 18 / 31-33 / 274-306 | `dict.sources` 来自 `/v1/sources`；筛选五组：市场/定位/类型/赛道/情绪 | **保留，不得回退** |
| 37 | `expanded: {}`，仅服务 `text_src`（L369-373） | 正文折叠另开 `bodyOpen`，避免和「查看原文」抢同一 key |
| 73 / 448-455 | 右栏「产量最高的源」`top_sources` slice 8，点击 `pickSource(sid)` | 池级聚合，见 §4.A |
| 192-201 | `sourceInfo(id)` / `sourceTitle(id)` 按 **source_id** join 110 源 | 工具条 chips（L322）应继续用这个；**卡片左框不能用** |
| 226-228 | `registerSubs` 的 `/news` hash 守卫 | **原样保留** |
| 337 | `.nc-grid` 双框 | **保留** |
| **338-350** | 左框：`sourceTitle(it.source_id)` + `it.positioning` + **源对象 markets 优先** + 源 brief + `.who` 的 `@handle`+role | **四个 UI 问题的主现场**：131 账号共用池名；6 枚池级市场徽章；brief 是入口说明；handle 与池名/正文重复 |
| 353-366 | 右框赛道分层 + 类型/情绪/标的 | **保留** |
| 368 | `.news-text` 全文 `pre-wrap`，无字数/行数折叠 | 问题 4 |
| 437-445 | 定位分布卡 | **保留** |

左框当前数据流（X 条目）：

```
sourceTitle(source_id)  →  "X大V观点(FxTwitter免登录池·分析师/交易员/KOL/内部人士)"
sourceInfo.markets      →  6 个池覆盖市场（压过条目 it.markets）
sourceInfo.brief        →  "X账号池观点入口(分析师/交易员/KOL)"
.it.author_handle       →  再画一行 @handle
```

条目上其实已有 `it.source = "X·显示名"`、`it.markets`（账号级）、`it.author_role`。不用新端点也能做「名字+handle+role+市场」的最低修复；**简介 note 不在条目上**，所以仍要 `/wb-api/x-accounts`。

### 1.4 图文页 `workbench/web/js/pages/article.js`（572 行）

| 行号 | 现状 | 判断 |
|---:|---|---|
| 51-53 | `registerSubs` 的 `/article` 守卫 | **原样保留** |
| 82-88 | `loadDict` 只聚合 `markets`，**不存 sources** | 本期要并行拉 x-accounts / x-profiles |
| 294-327 | 推荐卡片已是简化双框 | 左框用 `it.source`（已是 `X·显示名`）+ `it.markets`（已是账号级）+ `.who` 仅 handle、无 role |
| 无 | 无 `expanded` / 无正文折叠 | 与资讯页同步加 |
| 无 | 无 note / 无粉丝数 | 与资讯页同一套 join |

图文页左框比资讯页好一点（没用池级 title/markets），但仍缺 role 徽章、简介、粉丝；handle 单独一行与 `X·name` 语义重复。**必须同步改，不能只改 news.js。**

### 1.5 样式与壳

`workbench/web/css/app.css`（354 行）：

| 行号 | 现状 | 判断 |
|---:|---|---|
| 15-42 | oklch token + kebab 命名 | 新类只引用变量 |
| 186 | `.news-text { white-space: pre-wrap; word-break: break-word; }` | 与 `-webkit-line-clamp` 冲突，见 §6 |
| 194-207 | `.nc-grid` / `.nc-src` / `.nc-src .brief`（已 3 行 clamp）/ `.who` / `.nc-body` | 新类紧挨此块 |
| 349-353 | 1100px 藏右栏；`.nc-grid` 在 L207 已纵堆 | 正文折叠不改断点 |

`workbench/web/index.html`：资源版本号 **0903b**（L7 CSS；L51-57 六个 JS）。惯例全文件统一 bump，即使某个 JS 没改。

`workbench/web/js/api.js`：`WB.api.get("/x-accounts")` 会打 `/wb-api/x-accounts`（L9 自动加前缀）。适合把账号 join 辅助函数放到 `WB.xkol`，供 news / article 共用。

### 1.6 数据路径对照（问题 1 的根因一句话）

| 需要显示 | 条目上有没有 | `/v1/sources` 有没有 | 池 yaml 有没有 |
|---|---|---|---|
| 显示名 name | 间接：`source` 形如 `X·name` | 无（只有池 title） | 有 |
| @handle | `author_handle` | 无 | 有 |
| role | `author_role` | 无 | 有 |
| 账号级 markets | `it.markets` | 有的是 **6 值池覆盖** | 有 |
| 一句话简介 note | 无 | 有的是 **入口 brief** | 有 |
| homepage / tier / priority | 无 | 无 | 有 |
| bio / followers / verified / location | 无 | 无 | 无（增强脚本） |

---

## 2. 池加载机制确认（local 覆盖合并规则）

权威代码：`global-news-sources/fetchers/basic.py` L360-381。workbench 必须 **行为等价复刻**，不要 import fetcher。

### 2.1 主文件

```
pool_path = conf.pool_file 或 TW_POOL_DEFAULT
           = <repo>/global-news-sources/config/twitter_pool.yaml
pool = yaml.safe_load(主文件) or {}
```

路径解析与 fetcher 一致：相对 fetcher 文件是 `parent.parent / "config" / "twitter_pool.yaml"`（L315）。workbench 用 `Path(__file__).resolve().parents[2] / "global-news-sources" / "config" / "twitter_pool.yaml"`（与 `config.py` L16 的 `parents[2]` 同根）。

### 2.2 local 文件位置

```
loc = pool_path.with_name("twitter_pool.local.yaml")
```

即与主文件 **同目录**，不是工作台 `data/workbench/`。gitignore 第 50 行：`/global-news-sources/config/twitter_pool.local.yaml`。当前仓库无此文件；有则合并，无则跳过。

### 2.3 accounts：按 handle 的 **账号级整表替换**（不是字段级 merge，也不是纯追加）

```364:374:global-news-sources/fetchers/basic.py
    # 本机追加池(分发场景): twitter_pool.local.yaml(gitignored) 的账号并入,
    # 同 handle 覆盖池内条目——同事私加账号不动库文件, git pull 不冲突。
    loc = pool_path.with_name("twitter_pool.local.yaml")
    if loc.is_file():
        try:
            lp = yaml.safe_load(loc.read_text(encoding="utf-8")) or {}
            extra = lp.get("accounts") or []
            base = {str(a.get("handle", "")).lower(): a for a in (pool.get("accounts") or [])}
            for a in extra:
                base[str(a.get("handle", "")).lower()] = a
            pool["accounts"] = list(base.values())
```

精确语义：

1. 先把主池 `accounts` 建成 `dict[handle_lower] = 整个账号 dict`。
2. 遍历 local 的 `accounts`：`base[handle_lower] = a`（**赋值，不是 `update`**）。
3. 新 handle → 追加；已有 handle → **整对象被 local 那条换成**。local 缺的字段不会从主池补回。
4. handle 比较：`str(...).lower()`，大小写不敏感。空 handle 会撞到同一个 `""` 键，实施时跳过空 handle。
5. **不是字段级合并。** 若误写成 `base[h].update(a)`，与 fetcher 行为不一致，禁止。

### 2.4 defaults / filters：字典 **字段级** update（local 覆盖同名键）

```375:379:global-news-sources/fetchers/basic.py
            for k in ("defaults", "filters"):
                if lp.get(k):
                    merged = dict(pool.get(k) or {})
                    merged.update(lp[k])
                    pool[k] = merged
```

仅当 local 该键 truthy 才合并。账号端点用不到这两个键，但复刻函数要整段拷贝，避免以后脚本过滤行为漂移。

### 2.5 失败策略

L380-381：`except Exception: pass`。local 损坏时 **静默丢掉 local，主池照用**。workbench 复刻同样吞掉，可在响应里加 `local_error: true` 供调试（不影响 accounts 内容）。

主文件缺失：fetcher 抛 `RuntimeError`。工作台端点返回 404 `{error, hint}`，前端按「无账号字典」降级（见 §5.3）。

### 2.6 下游过滤（端点是否照做）

fetcher 随后按 `enabled`、role、markets、tier、priority 过滤后才抓取（L383-403）。**`/wb-api/x-accounts` 不过滤 role/enabled**：UI join 需要看到池里每一条（含未启用），否则历史条目会缺名。只要求 `handle` 非空。响应可带 `enabled` 字段，前端不消费也无妨。

---

## 3. 四个 UI 问题与对策（对应关系）

| # | 用户问题 | 根因（行号） | 对策 |
|---|---|---|---|
| 1 | 左框按池显示不按账号 | `news.js` L340 `sourceTitle(it.source_id)` 取 builtin/tags 池级 title | 有 `author_handle` 时改走账号字典；新增 `GET /wb-api/x-accounts` |
| 2 | 录入之外要 bio/粉丝/认证/地点 | 池 yaml 无这些字段；运行时禁止调 CLI | 手动脚本批量问 grok → `data/workbench/x_profiles.json`；`GET /wb-api/x-profiles` 只读下发 |
| 3 | 左框重复：6 枚池级市场徽章 + `.who` 再画 handle | L343 源 markets 优先；L348-349 与名称叠 handle | X 条目改用账号级字段优先级表（§5）；非 X 保持现状 |
| 4 | 右框过长 | L368 / `article.js` L321 无折叠；`.news-text` L186 `pre-wrap` | 约 300 字或 6 行折叠；`bodyOpen` 字典；CSS 见 §6 |

---

## 4. 三项评估结论（先拍板）

### 4.A 右栏「产量最高的源」要不要拆成账号级 top —— **做轻量 sibling，不拆源**

**结论：保留现有 `top_sources` 池级条卡不动；在其下新增一张「X 账号产量」Top10。不把 131 账号伪装成 source_id。**

理由：

1. `stats.py` L62、L101-102 按 `source_id` 聚合是对的——采集单元就是两个池入口。拆掉会让非 X 源的对比失真。
2. 现状的交互 bug 更值得修：`per_source_name` 用条目 `source`（`X·某账号`）当 lab，点击却 `pickSource(sid)` 滤整个池（`news.js` L215 / L450）。**本期顺手把 X 两条的 lab 改成源 title**（`twitter_kol_views` → 池级短名），避免「看到账号名、点进去却是全池」。这不是拆源，是修标签。
3. 账号级 Counter 几乎零成本：同一批 `items` 上 `author_handle` 再 `most_common(10)` 即可。
4. 反查路径：**不要** 发明 `sources=handle`（serve 不认）。点击账号条：
   - `f.q = handle`（正文有 `@handle:` 前缀，`store.py` L482-484 能搜到）；
   - 同时 `f.sources = ["twitter_kol_flash","twitter_kol_views"]`（SQL `IN`，两入口并集）；
   - `f.since = ""`（与现有 `pickSource` 放开时间窗一致）。
   - 误伤：其它推文 mention 该 handle 也会进结果。接受；提示文案可写「按关键词 @handle 反查」。不做前端「已加载条目过滤」——当前页只有 100 条，Top 账号大量历史会被截掉，体验假。
5. **不做** 的替代方案（否决）：把 `top_sources` 直接改成 handle 聚合——非 X 源会消失；给 serve 加 `author_handle=` 参数——要改板块一，越权。

`stats.aggregate()` 增加：

```python
xh = Counter()
xh_name = {}
for i in items:
    h = str(i.get("author_handle") or "").lstrip("@").lower()
    if not h:
        continue
    xh[h] += 1
    xh_name.setdefault(h, i.get("source") or h)
data["top_x_accounts"] = [[xh_name[h], n, h] for h, n in xh.most_common(10)]
```

前端 `xAccBars` / `pickXAccount(h)`。无 X 条目时卡片 `v-if` 隐藏。

### 4.B 来源详情注册表要不要为 131 账号加分区 —— **不做分区、不做折叠明细**

**结论：110 源表结构不变。仅在 `twitter_kol_flash` / `twitter_kol_views` 两行说明列末尾追加 muted 短句「池内 N 账号」（N 来自 `/x-accounts.total`）。不新增第三行伪源，不展开 131 行。**

理由：

1. 注册表的主键是 source_id，筛选按钮走 `srcFilter(id)`（`news.js` L219-223），账号不是源。把 131 行塞进去会把「110 源」语义打烂，且点「筛选」没有合法 id。
2. 账号字典已经有专用端点 + 信息流左框，详情表再做一遍是重复。
3. 「一行入口再折叠」属于过度设计：多一套展开状态、搜索还要决定搜不搜账号 note。

执行岗若连「池内 N 账号」都觉得吵，可以删掉，不影响主需求。

### 4.C article.js 推荐信息子页 —— **必须同步，简化版同一套 join**

推荐卡片已是 `.nc-grid`（L295）。左框改成与资讯页 X 分支同一套字段优先级（§5），但密度更高：简介 2 行 clamp（复用 `.nc-src .brief` 现成 3 行即可，不新开一套）；不要定位徽章（role 已表达）；不要粉丝以外的增强字段。右框同样做正文折叠。`loadReco` 前后拉一次 `WB.xkol.load()`。

---

## 5. 左框字段优先级表

判定：`isX(it) = !!(it.author_handle)`。非 X：**零改动**，仍走现在的 `sourceTitle` + 源 markets + 源 brief，无 `.who`。

### 5.1 X 条目左框（上到下）

| 顺序 | 字段 | 取值优先级 | 缺失时 |
|---|---|---|---|
| 1 | 显示名 | `xAcc.name` → 去掉前缀后的 `it.source`（剥 `X·`）→ `author_handle` | 不会空 |
| 2 | @handle + role 徽章 | handle 恒用 `it.author_handle`（条目权威，防改名延迟）；role 文案：`xAcc.role` → `it.author_role`；中文映射见下 | role 空则只显示 @handle |
| 3 | 简介 | **池 `note` 优先** → grok `bio` 兜底 | 都空则整行不渲染 |
| 4 | 账号级 markets | **`it.markets` 优先**（入库已按账号+ticker 并集，`store.py` L276-278）→ 否则 `xAcc.markets` | 空则无徽章。**禁止** `sourceInfo(source_id).markets` |
| 5 | 粉丝数（可选） | `xProf.followers` 为 number 才显示 | 缓存缺失/空 → 不渲染，不算错误 |
| — | 明确不显示 | 源级 title、源级 brief、源级 6 市场、条目 `positioning`（与 role 重复；media 等 role 已比「大V」更细） | — |
| — | 可选增强不进左框 | `verified` / `location`：本期不画，避免 188px 左栏再堆。数据仍下发，以后用 | — |

显示名做成链接：`xAcc.homepage` 或 `https://x.com/{handle}`，`target=_blank`。

role 中文（硬编码在 `WB.xkol.ROLE_ZH`，与录入规范第二节一致）：

```
media=媒体  data_bot=数据  breaks=爆料  company=公司
analyst=分析师  trader=交易员  kol=KOL  insider=内部人士
```

未知 role 原样显示。徽章 class：沿用 `.badge`，不用新颜色。

粉丝格式：`<10000` 原样；否则 `12.3万`（中文栏）。`verified===true` 不单独占行；若要极轻提示，可在 @handle 旁加一个 `.badge`「认证」，**默认不做**，把宽度留给简介。

### 5.2 与 `.who` 去重

优化后 **不再使用** `.who` 作为第三行「再写一遍 handle」。handle 固定在第 2 行，与第 1 行显示名分工。删除 X 分支里的旧 `.who`。非 X 本来就没有 `.who`。

### 5.3 降级（缓存/端点都没有时仍要能看）

| 数据 | 降级 |
|---|---|
| `/x-accounts` 失败或 `{}` | name ← `it.source` 去 `X·`；role ← `it.author_role`；markets ← `it.markets`；简介行隐藏 |
| `/x-profiles` 文件不存在 | 粉丝行隐藏；简介若有 note 仍显示 |
| 某 handle 不在池（local 未合入的历史号） | 同上条目字段降级 |
| 简介 note 与 bio 都空 | 不渲染 `.brief`，不要占位「暂无简介」 |

**验收句：只靠录入信息（条目 + 池 yaml，无 x_profiles.json）必须完整渲染 1-4 行。**

### 5.4 工具条来源 chip 仍用源级

`news.js` L322 `sourceTitle(sid)` 保持池名。那是 `f.sources` 里的 source_id，不是卡片。

---

## 6. 长文截断方案（CSS + JS 伪码）

### 6.1 行为

- 右框 `.news-text` 在 **未展开** 且 **需要截断** 时最多 6 行。
- 「需要截断」：`(title — text)` 去空白后 **长度 > 300**，或文本中显式换行数 ≥ 6。
- 操作行增加 `展开全文` / `收起`，与现有 `查看原文(译前)` 并列，**独立状态**。
- `news.js` 与 `article.js` 同样做。`article.js` 没有 `text_src` 按钮，只加正文折叠。

### 6.2 为什么不能直接 line-clamp + 现有 pre-wrap

`.news-text`（`app.css` L186）`white-space: pre-wrap` 会保留推文换行。`-webkit-line-clamp` 依赖 `display: -webkit-box; -webkit-box-orient: vertical; overflow: hidden`。在 Chromium 里 **pre-wrap 与 -webkit-box 同时存在时 clamp 经常失效**（盒子按内容撑开，`scrollHeight` 判断也会漂）。

解法：**折叠态关掉 pre-wrap，展开态恢复。**

### 6.3 CSS（紧挨 `.nc-*` 块，约 L207 后）

```css
/* X/长文折叠: 折叠态必须 white-space:normal, 否则 line-clamp 与 pre-wrap 互斥 */
.news-text.is-clamp {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 6;
  overflow: hidden;
  white-space: normal;          /* 覆盖 L186 的 pre-wrap */
  word-break: break-word;
}
.news-text.is-open {
  display: block;
  -webkit-line-clamp: unset;
  overflow: visible;
  white-space: pre-wrap;        /* 展开后还原换行 */
}
.nc-src .followers {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-mute);
}
.nc-src .name a { color: inherit; }
.nc-src .name a:hover { color: var(--accent); }
```

不新增主题色。`.nc-src .brief` 已有 3 行 clamp（L200-202），账号简介复用，不要再给 brief 加按钮。

### 6.4 JS 状态（复用 expanded 字典模式，不复用同一个 key）

`news.js` `data()` 增加 `bodyOpen: {}`（L37 旁）。`article.js` 同样加。不要写 `expanded[it.id]` 兼管原文和正文——点「展开全文」会误开译前原文。

伪码（两页共用，建议挂 `WB.xkol`）：

```javascript
function bodyText(it) {
  return (it.title ? it.title + " — " : "") + (it.text || "");
}
function needClamp(it) {
  const t = bodyText(it);
  if (t.length > 300) return true;
  const lines = t.split(/\n/).filter((x) => x.trim().length);
  return lines.length > 6;
}
function toggleBody(map, id) {
  map[id] = !map[id];
}
```

模板：

```html
<div class="news-text"
     :class="needClamp(it) && !bodyOpen[it.id] ? 'is-clamp' : (bodyOpen[it.id] ? 'is-open' : '')">
  {{ it.title ? it.title + ' — ' : '' }}{{ it.text }}
</div>
<!-- news-actions 内 -->
<span class="act" v-if="needClamp(it)" @click="bodyOpen[it.id] = !bodyOpen[it.id]">
  {{ bodyOpen[it.id] ? '收起' : '展开全文' }}
</span>
```

不需要截断时不要加 `is-clamp`，避免短讯也被裁。Vue 对 `bodyOpen[it.id]` 的赋值能触发视图（与现有 `expanded[it.id]` 同一套路，L372）。

测量方案（`scrollHeight > clientHeight`）作可选增强，不作为 P0：300 字阈值对中文 6 行已经同量级（约 40–50 字/行 × 6）。显式换行多的短帖用行数规则兜住。

---

## 7. 改动清单（文件级，照此施工）

**禁止修改：** `global-news-sources/**`、`ai-workflow/**`、`auto-publisher/**`、除本清单外的 docs、任何 `data/**` 样例入库。

| 文件 | 改什么 |
|---|---|
| **新建** `workbench/server/xpool.py` | `load_pool()` 复刻 basic.py L360-381；`accounts_map()` → `{handle_lower: {name,role,markets,note,homepage,tier,priority,enabled,uid}}`；`load_profiles()` 读 `data/workbench/x_profiles.json`，缺文件返回 `{profiles:{}, missing:true}` |
| `workbench/server/app.py` | 在 `/wb-api/stats` 附近新增 `GET /wb-api/x-accounts`、`GET /wb-api/x-profiles`；`from . import xpool`。**不**在运行时调 CLI |
| `workbench/server/stats.py` | `top_sources` 对 `twitter_kol_*` 用源 title 而非条目 `X·账号`；新增 `top_x_accounts`（§4.A） |
| **新建** `scripts/enrich_x_profiles.py` | 手动增强 CLI，见 §8。写 `data/workbench/x_profiles.json` |
| `cli.py`（可选但建议） | `workbench enrich-x` 透传到脚本，便于 AGENTS 速查；不做也不阻塞，直接 `py -3.11 scripts/enrich_x_profiles.py` |
| `workbench/web/js/api.js` | 增加 `WB.xkol`：`load()` 并行 GET 两个端点、`acc(handle)`、`prof(handle)`、`ROLE_ZH`、`needClamp` / `bodyText` |
| `workbench/web/js/pages/news.js` | `mounted` 调 `WB.xkol.load()`；左框 X 分支按 §5；`bodyOpen`；右栏 X 账号产量卡；来源详情两行池规模（可选）；**不得改** `registerSubs` 守卫、五组筛选、赛道分层、定位分布、`.nc-grid` 结构 |
| `workbench/web/js/pages/article.js` | `mounted`/`loadReco` 使用同一 `WB.xkol`；左框 X 分支；`bodyOpen` + 展开全文；**不得改** `registerSubs` 守卫 |
| `workbench/web/css/app.css` | §6.3 类放在 `.nc-time` 规则后（约 L206 后） |
| `workbench/web/index.html` | 全部 `?v=0903b` → `?v=0903c`（L7 及 L51-57 共 7 处，整页统一，禁止只 bump 改过的文件） |

不改：`proxy.py`、`reco.py`（条目已含 author_*）、`views.py`、`config.py`（脚本自己原子写 json 即可；若想复用 `save_rows` 风格，可在 xpool 里抄 `config.py` L50-57 的 mkstemp+os.replace，不要把 profiles 塞进 settings.json）。

---

## 8. 后端 API 形状

### 8.1 `GET /wb-api/x-accounts`

```json
{
  "total": 131,
  "local_merged": false,
  "accounts": {
    "altinhisseler": {
      "handle": "altinhisseler",
      "name": "ALTIN HİSSELER",
      "role": "kol",
      "markets": ["土耳其"],
      "note": "BIST影响榜前列，…",
      "homepage": "https://x.com/altinhisseler",
      "tier": "core",
      "priority": "high",
      "enabled": true
    }
  }
}
```

- Key **一律 lower + 去 @**。
- 主文件缺失：404 `{error:"twitter_pool.yaml 不存在", hint:"确认板块一 config 目录"}`。
- PyYAML 未装：500 `{error:"PyYAML 未安装", hint:"pip install pyyaml>=6.0"}`。
- 内存缓存：mtime(主)+mtime(local) 变化才重读；否则 60s TTL 亦可。池 131 条，解析成本可忽略。
- **不要** 把 131 账号并进 `/v1/sources` 代理响应。

### 8.2 `GET /wb-api/x-profiles`

文件不存在时 **200**（不要 404，前端好写）：

```json
{ "missing": true, "updated_at": null, "backend": null, "profiles": {} }
```

有缓存则：

```json
{
  "missing": false,
  "updated_at": "2026-09-03 19:10:00",
  "backend": "grok-cli",
  "profiles": {
    "altinhisseler": {
      "handle": "altinhisseler",
      "bio": "...",
      "followers": 120000,
      "verified": false,
      "location": "Istanbul",
      "enriched_at": "2026-09-03 19:10:00",
      "error": null
    }
  }
}
```

只读。不触发 enrich。

### 8.3 `xpool.load_pool()` 伪码（必须与 fetcher 逐行同义）

```python
def load_pool(pool_path: Path | None = None) -> dict:
    pool_path = pool_path or (REPO / "global-news-sources/config/twitter_pool.yaml")
    if not pool_path.is_file():
        raise FileNotFoundError(str(pool_path))
    import yaml
    pool = yaml.safe_load(pool_path.read_text(encoding="utf-8")) or {}
    loc = pool_path.with_name("twitter_pool.local.yaml")
    local_ok, local_err = False, False
    if loc.is_file():
        try:
            lp = yaml.safe_load(loc.read_text(encoding="utf-8")) or {}
            extra = lp.get("accounts") or []
            base = {str(a.get("handle") or "").lstrip("@").lower(): a
                    for a in (pool.get("accounts") or []) if a.get("handle")}
            for a in extra:
                h = str(a.get("handle") or "").lstrip("@").lower()
                if h:
                    base[h] = a          # 账号级整表替换
            pool["accounts"] = list(base.values())
            for k in ("defaults", "filters"):
                if lp.get(k):
                    merged = dict(pool.get(k) or {})
                    merged.update(lp[k])
                    pool[k] = merged
            local_ok = True
        except Exception:
            local_err = True             # 与 fetcher 一样吞掉
    pool["_local_merged"] = local_ok
    pool["_local_error"] = local_err
    return pool
```

相对 fetcher 的唯一有意差异：跳过空 handle（避免 `""` 撞键）。其余保持一致。

---

## 9. 前端实施要点

### 9.1 `WB.xkol`（`api.js`）

```javascript
WB.xkol = {
  accounts: {},
  profiles: {},
  missingProfiles: true,
  poolTotal: 0,
  ROLE_ZH: { media: "媒体", data_bot: "数据", breaks: "爆料", company: "公司",
             analyst: "分析师", trader: "交易员", kol: "KOL", insider: "内部人士" },
  key(h) { return String(h || "").replace(/^@/, "").toLowerCase(); },
  async load() {
    try {
      const d = await WB.api.get("/x-accounts");
      this.accounts = d.accounts || {};
      this.poolTotal = d.total || 0;
    } catch (e) { this.accounts = {}; }
    try {
      const p = await WB.api.get("/x-profiles");
      this.profiles = p.profiles || {};
      this.missingProfiles = !!p.missing;
    } catch (e) { this.profiles = {}; this.missingProfiles = true; }
  },
  acc(h) { return this.accounts[this.key(h)] || null; },
  prof(h) { return this.profiles[this.key(h)] || null; },
  name(it) {
    const a = this.acc(it.author_handle);
    if (a && a.name) return a.name;
    const s = String(it.source || "").replace(/^X·/, "");
    return s || it.author_handle;
  },
  role(it) {
    const r = (this.acc(it.author_handle) || {}).role || it.author_role || "";
    return this.ROLE_ZH[r] || r;
  },
  brief(it) {
    const a = this.acc(it.author_handle) || {};
    const p = this.prof(it.author_handle) || {};
    return a.note || p.bio || "";
  },
  markets(it) {
    if (it.markets && it.markets.length) return it.markets;
    return ((this.acc(it.author_handle) || {}).markets) || [];
  },
  href(it) {
    const a = this.acc(it.author_handle);
    if (a && a.homepage) return a.homepage;
    const h = String(it.author_handle || "").replace(/^@/, "");
    return h ? "https://x.com/" + h : "";
  },
  followers(it) {
    const n = (this.prof(it.author_handle) || {}).followers;
    if (typeof n !== "number") return "";
    return n >= 10000 ? (n / 10000).toFixed(n >= 100000 ? 0 : 1) + "万粉" : n + "粉";
  },
  needClamp(it) { /* §6.4 */ },
};
```

`news.js` / `article.js` 的 `mounted` 里 `WB.xkol.load()`，失败不影响 `load()` / `loadReco()`。

### 9.2 资讯页左框模板替换（仅 X 分支；L338-350）

```html
<div class="nc-src" v-if="it.author_handle">
  <div class="name">
    <a v-if="xHref(it)" :href="xHref(it)" target="_blank" rel="noopener">{{ xName(it) }}</a>
    <template v-else>{{ xName(it) }}</template>
  </div>
  <div class="who">@{{ it.author_handle }}
    <span v-if="xRole(it)" class="badge">{{ xRole(it) }}</span></div>
  <div class="brief" v-if="xBrief(it)">{{ xBrief(it) }}</div>
  <div class="nc-badges" style="margin-bottom:0">
    <span v-for="m in xMarkets(it)" class="badge">{{ m }}</span>
  </div>
  <div class="followers" v-if="xFollowers(it)">{{ xFollowers(it) }}</div>
</div>
<div class="nc-src" v-else>
  <!-- 原 L340-347 源级展示原样保留 -->
</div>
```

方法可以是页面上的薄封装：`xName(it){ return WB.xkol.name(it); }`，避免模板里写 `WB.xkol` 在 Vue 生产构建里偶发找不到（本项目是 global build，`WB` 在 window 上，模板用 methods 更稳）。

### 9.3 右栏 X 账号产量（`news.js` 在「产量最高的源」卡之后）

```html
<div class="card" v-if="xAccBars.length">
  <h3>X 账号产量</h3>
  <div class="bars">
    <div v-for="r in xAccBars" :key="r[2]" class="bar-row clickable" @click="pickXAccount(r[2])">
      <span class="lab">{{ r[0] }}</span>
      ...
    </div>
  </div>
</div>
```

`pickXAccount(h)`：`this.f.q = h; this.f.sources = ["twitter_kol_flash","twitter_kol_views"]; this.f.since = ""; this.reload();`

`top_sources` 点击逻辑不改。stats 侧把 X 两行 lab 换成源 title 后，这条卡才名实相符。

### 9.4 图文页左框（`article.js` L297-304）

与 §9.2 同一 X 分支；非 X 继续 `it.source` + `it.positioning` + `it.markets`（推荐页没有 `sourceInfo`，保持现状即可）。加上 `bodyOpen` 与展开按钮。

---

## 10. 增强脚本设计

### 10.1 定位与红线

- 路径：`scripts/enrich_x_profiles.py`（与 `scripts/migrate_tags_v5.py` 同层，独立可跑）。
- **按需手动跑**。不进 `workbench serve`，不进 refresh 任务计划。
- 写：`data/workbench/x_profiles.json`（`data/` 已 gitignore L42）。
- 读：池文件（只读，含 local 合并，调用 `xpool.load_pool`；脚本把 `workbench/` 插入 `sys.path`）。
- 服务器进程 **零** subprocess。

建议用法：

```
py -3.11 scripts/enrich_x_profiles.py --backend cursor --batch 12
py -3.11 scripts/enrich_x_profiles.py --backend grok --batch 12
py -3.11 scripts/enrich_x_profiles.py --backend grok --handles altinhisseler,TuncayTursucu
py -3.11 scripts/enrich_x_profiles.py --dry-run
py -3.11 scripts/enrich_x_profiles.py --backend grok --force
```

| 参数 | 默认 | 含义 |
|---|---|---|
| `--backend` | `cursor` | `cursor` 或 `grok` |
| `--batch` | `12` | 每批 handle 数，允许 10–15，越界 clamp |
| `--handles` | 空 | 逗号列表；空 = 池内全部 enabled |
| `--force` | 关 | 已有 `enriched_at` 且无 error 的也重抓 |
| `--dry-run` | 关 | 只打印批次与 prompt，不调 CLI、不写盘 |
| `--max-retries` | `2` | 单批失败重试次数 |

### 10.2 批大小与调度

131 账号 ÷ 12 ≈ 11 批。批次之间 `sleep(2)`。单批超时建议 180s（grok 带 x_search 会偏慢）。顺序按池文件原序，便于对照 yaml。

跳过策略：`--force` 关闭时，缓存里该 handle `error` 为空且 `bio`/`followers` 至少有一个非空 → 跳过。

### 10.3 JSON schema（两后端同一契约）

元素：

```json
{
  "handle": "altinhisseler",
  "bio": "string or null",
  "followers": "integer or null",
  "verified": "boolean or null",
  "location": "string or null"
}
```

根必须是 **数组**。handle 去 @、大小写不敏感对齐。缺字段当 null。followers 若模型返回 `"12.3K"` 由脚本解析：`K/k=千`、`M/m=百万`、`万=10000`，解析失败 → null，不算整批失败。

### 10.4 Prompt 模板（两后端共用正文）

```
你是 X/Twitter 账号资料核查员。对下面每个 handle 用 X 搜索（x-search / x_search）查官方账号页，补全资料。
禁止读任何技能文件、配置文件、本仓库代码。禁止编造：查不到的字段填 null。
不要输出 Markdown 围栏、不要解释。只输出一个 JSON 数组。

每个元素必须是:
{"handle":"string","bio":string|null,"followers":int|null,"verified":bool|null,"location":string|null}

handle 列表:
@altinhisseler
@TuncayTursucu
...
```

`verified`：蓝标/官方认证为 true，其余 false；不确定 null。

### 10.5 非纯 JSON 容错

模型常包 ```json 或前后说一句。提取：

```python
def extract_json_array(text: str) -> list:
    i, j = text.find("["), text.rfind("]")
    if i < 0 or j <= i:
        raise ValueError("no json array")
    return json.loads(text[i:j+1])
```

**第一个左方括号到最后一个右方括号**（用户指定）。再 `json.loads`。失败则该批进入重试。

若后端包了一层 `{result: "..."}`（cursor-agent `--output-format json`），先取 `result` 字符串再跑 extract。

### 10.6 失败、重试、部分成功

```
旧缓存 = 读现有 x_profiles.json（无则 profiles={}）
for batch in batches:
    for attempt in 0..max_retries:
        try:
            raw = invoke_cli(batch)
            arr = extract_json_array(raw)
            break
        except:
            sleep(5 * (attempt+1))
    else:
        整批标记失败，旧缓存这些 handle 原样保留；
        从未出现过的 handle 写入 {error: "batch_failed", enriched_at: 旧或空}
        continue
    for el in arr:
        规范化后写入 profiles[handle]，error=null，enriched_at=now
    本批未出现在 arr 里的 handle：保留旧值；无旧值则 error="missing_in_model_output"
    每批成功后立刻原子写盘（半路崩溃不丢已成功批次）
```

原子写：抄 `config.py` L50-57（mkstemp + `os.replace`）。顶层 `updated_at` / `backend` 每次成功批更新。

退出码：全部成功 0；部分失败 3（对齐 AGENTS 业务失败）；池文件缺失 4。

### 10.7 两种 CLI 调用对比

| | A. cursor-agent + grok 模型 | B. grok CLI（xAI Grok Build） |
|---|---|---|
| 可执行文件 | `C:\Users\hzh\AppData\Local\cursor-agent\cursor-agent.cmd` | `C:\Users\hzh\.grok\bin\agent.exe`（PATH 上也可 `grok`） |
| 包装 | **必须** `cmd //c`，且先 `cd` 到仓库根 | 必须先 `cd` 到仓库根（`--cwd` 无头模式会丢答复，见 grok 技能档案） |
| 模型 | `--model cursor-grok-4.6-high` | 默认 grok-4.6（不要乱加 `-m grok-4.5`，4.5 无后端搜索） |
| 工具 | 用户预期内置 x-search；**CLI `-p` 是否暴露 x-search 必须实测**（失败则该 backend 标不可用，改 grok） | 会话 signals 已证实工具名 `x_search` + `web_search` |
| 防跑偏 | prompt 写「禁止读技能/配置」 | **必须** `--max-turns 15` + 同样禁止读技能（否则 agent-reach 技能会烧光预算） |
| 信任 | `--trust` 必带，否则直接报错 | 只读任务可不加 `--always-approve`；不要让它写仓库 |
| JSON | `--output-format json` → 从信封 `result` 再抽数组；无 `--json-schema` 则全靠 prompt | `--json-schema '<schema>'`（隐含 json 输出）+ 仍做方括号抽取兜底 |
| 优点 | 与本工作台同一 Cursor 账号；模型即方案指定的 grok | x_search 是一等工具，补 X 资料更稳 |
| 缺点 | x-search 在 cursor-agent 无头模式可能缺失 | 依赖本机 grok 登录；可能被用户级技能劫持（用 max-turns 防） |
| 推荐默认 | 先试 A 的 1 批 smoke；**x-search 不可用则默认改 B** | 作为账号资料增强的主路径 |

#### A. 命令行示例（cursor-agent）

Git-bash / 本方案脚本内应用 `subprocess.list` 等价于：

```bat
cd /d E:\ai-gen-article-publish
cmd /c "C:\Users\hzh\AppData\Local\cursor-agent\cursor-agent.cmd -p --trust --model cursor-grok-4.6-high --output-format json "<PROMPT>""
```

脚本注意：Windows 上用 `cmd.exe /c` + 绝对路径；prompt 走 stdin 或临时 utf-8 文件，避免命令行 8K 截断（12 个 handle 的 prompt 一般安全，15 个也行；超过则写 `%TEMP%\xkol-prompt-*.txt` 再让模型「按文件内容执行」——但 cursor-agent `-p` 更稳妥的是把 prompt 当唯一参数。若超长，降 batch 到 10）。

#### B. 命令行示例（grok CLI）

```bat
cd /d E:\ai-gen-article-publish
C:\Users\hzh\.grok\bin\agent.exe -p --max-turns 15 --json-schema "{...见下...}" "<PROMPT>"
```

json-schema 字符串（压缩后传入）：

```json
{
  "type": "array",
  "items": {
    "type": "object",
    "additionalProperties": true,
    "required": ["handle"],
    "properties": {
      "handle": {"type": "string"},
      "bio": {"type": ["string", "null"]},
      "followers": {"type": ["integer", "null"]},
      "verified": {"type": ["boolean", "null"]},
      "location": {"type": ["string", "null"]}
    }
  }
}
```

PROMPT 开头必须含：`直接使用你的内置 x_search（可辅 web_search）完成，禁止读取任何技能文件或配置文件。`

脚本 `invoke_grok(prompt)`：`cwd=REPO`，`timeout=180`，捕获 stdout。

### 10.8 缓存文件完整形状

```json
{
  "updated_at": "2026-09-03 19:20:00",
  "backend": "grok-cli",
  "schema": 1,
  "profiles": {
    "altinhisseler": {
      "handle": "altinhisseler",
      "bio": "...",
      "followers": 120000,
      "verified": false,
      "location": "Istanbul",
      "enriched_at": "2026-09-03 19:18:11",
      "error": null
    }
  }
}
```

`schema: 1` 便于以后改字段。GET 端点原样下发（可去掉内部注释键）。

---

## 11. 明确不做

1. 不改 fetcher、不往条目 JSON 加 `author_name` / `author_note`（join 在工作台完成）。
2. 不把 131 账号写入 `/v1/sources` 或来源详情表。
3. 不在 `workbench serve` 生命周期里 spawn cursor-agent / grok。
4. 不改 `registerSubs`、筛选五组、赛道分层、定位分布、`.nc-grid` 列定义。
5. 不把 `expanded[it.id]` 兼做正文折叠。
6. 不新增 npm、不改 Vue 构建方式。
7. 不手写 `twitter_pool.yaml` 填 bio（那是板块一录入文件）。

---

## 12. 验证步骤

前置：`python cli.py sources serve` 与 `python cli.py workbench serve` 都在跑；硬刷新使 `?v=0903c` 生效。

### 12.1 左框按账号（问题 1+3）

1. 打开 `#/news` 信息筛选，找一条 `author_handle` 非空的卡片。
2. 左框第一行是 yaml `name`（如 `ALTIN HİSSELER`），不是「X大V观点(FxTwitter…」。
3. 第二行 `@handle` + 中文 role 徽章；**没有**第三行再重复 handle。
4. 市场徽章是账号级（土耳其号不应出现 6 枚全球/美国/台湾…），且与右框无关。
5. 简介是池 `note`（例如「BIST影响榜前列…」），不是「X账号池观点入口…」。
6. 点显示名新开 `x.com/...`。
7. 找一条 **无** `author_handle` 的快讯（如新浪 7×24）：左框仍是源 title + 源市场 + 源 brief，与改前一致。
8. 筛选五组、赛道 L1>L2 徽章、定位分布卡、左菜单切来源详情再回来，子菜单仍停在资讯页（`registerSubs` 守卫未回退）。

### 12.2 缓存缺失降级（无 grok 资料也能看）

1. 确保 **没有** `data/workbench/x_profiles.json`（或临时改名）。
2. 重启 8788，刷新资讯页。
3. X 左框仍有 name / @handle+role / note / 账号市场；**没有**粉丝行；控制台无未捕获异常。
4. `/wb-api/x-profiles` 返回 200 且 `missing: true`。
5. 再断掉 x-accounts（临时改文件名池 yaml——**验证完立刻改回，且这步在独立副本上做更安全**；或用浏览器拦截该 GET）：卡片仍能靠 `it.source` / `it.author_role` / `it.markets` 渲染，不空白、不崩布局。

### 12.3 长文折叠（问题 4）

1. 找一条明显长推（或 views 里带多段换行的）。右框默认最多约 6 行，出现「展开全文」。
2. 点击后 `pre-wrap` 换行恢复，按钮变「收起」；再点回去。
3. 「查看原文(译前)」与展开全文互不影响（`expanded` vs `bodyOpen`）。
4. 短讯（<300 字且少换行）无展开按钮、不被裁切。
5. `#/article` 推荐信息子页：X 卡片左框同样按账号；长正文同样可折叠。

### 12.4 右栏与来源详情（§4.A / 4.B）

1. 「产量最高的源」里 twitter 两条的 lab 是池级源名，点击后工具条 chip 为 flash/views，信息流仍是该池全部账号。
2. 「X 账号产量」Top10 出现；点击某 handle 后 `q` 与两个 twitter source chip 生效，列表以该账号为主。
3. 来源详情仍是 ~110 行，没有 131 账号表；twitter 两行说明可带「池内 131 账号」。

### 12.5 增强脚本 —— 路径 A（cursor-grok）

1. `py -3.11 scripts/enrich_x_profiles.py --backend cursor --dry-run`：打印将发送的 11 批 handle，不写盘。
2. `py -3.11 scripts/enrich_x_profiles.py --backend cursor --handles altinhisseler --batch 10`：只跑 1 个账号 smoke。
3. 看 stdout 是否像 JSON 数组；若只有「我无法搜索 X / 没有 x-search」类答复 → **记为 A 不可用**，不要强跑 131。
4. 若成功：打开 `data/workbench/x_profiles.json`，该 handle 有 `bio` 或 `followers`，`enriched_at` 非空。
5. 刷新工作台，该账号左框出现粉丝（若 followers 为数字）。

### 12.6 增强脚本 —— 路径 B（grok CLI）

1. 确认 `C:\Users\hzh\.grok\bin\agent.exe` 可执行（本机 OAuth 已登录）。
2. `py -3.11 scripts/enrich_x_profiles.py --backend grok --handles altinhisseler,TuncayTursucu --batch 10`
3. 进程 cwd 必须是仓库根；命令含 `--max-turns 15`。
4. 成功则缓存 2 条；再跑全池（可隔夜）：`... --backend grok --batch 12`。
5. 制造一次失败：断网跑一批，确认 **旧 profiles 仍在**，失败 handle 带 `error`，退出码 3。
6. 工作台 **不要重启脚本依赖的 CLI**；只 `GET /x-profiles` 能读到新缓存（60s 内或立刻，端点无缓存也可接受）。

### 12.7 回归清单（打勾）

- [ ] `registerSubs`：在图文页停留时，资讯页迟到的 stats 回调不会改左菜单
- [ ] `.nc-grid` 188px + 窄屏纵堆仍在
- [ ] 赛道黄徽章 L1 + 灰 L2、`+n`
- [ ] 筛选：市场/定位/类型/赛道/情绪 五组，无 kinds/forms 回流
- [ ] 定位分布卡可点
- [ ] `index.html` 七处均为 `0903c`
- [ ] 未改 `global-news-sources` 任何文件（`git status` 确认）

---

## 13. 实施顺序建议

1. `xpool.py` + 两个 GET + 用 curl 看 131 key。
2. `WB.xkol` + news 左框 X 分支 + CSS 折叠（无增强缓存即可验收 1/3/4 与降级）。
3. article.js 同步。
4. stats `top_x_accounts` + 右栏卡 + twitter lab 修正。
5. `enrich_x_profiles.py`：dry-run → A smoke → B smoke → 全量。
6. bump `0903c`，走完 §12。

粒度到此可直接照做。
