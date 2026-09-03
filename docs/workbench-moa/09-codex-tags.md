# 前端工作台匹配源侧新标签体系——详细更改计划

- 日期：2026-09-03
- 作者：codex(gpt-5.6-sol)
- TL;DR：删除旧 `kinds/forms/channels` 主筛选，统一为市场/定位/类型/赛道 L1/情绪；资讯与推荐卡片改成来源框和内容框，来源简介在前端按 `source_id` join；赛道筛选由工作台新增只读包装端点完成，源侧代码保持零改动。

> 本文仅是实施计划。实施范围只允许修改 `workbench/`，以及更新静态资源版本号；`global-news-sources/` 保持只读、零修改，工作台仍只通过 HTTP GET 读取前三板块，唯一持久化写口仍是 `data/workbench/*.json`。

## 1. 现状审计

### 1.1 `workbench/web/js/pages/news.js`

| 行号 | 现状 | 判断 |
|---:|---|---|
| 14-25 | 注释已提到双标签制；`dict` 聚合市场、形态、定位、来源；`enums` 同时保留旧 `kinds`、未使用的 `info_types`，以及新 `item_types/positionings/sentiments`。 | 部分对齐。旧枚举仍混在页面状态中，是后续重名与参数漂移的根源。 |
| 28-30 | `f` 同时保存 `markets/kinds/forms/positionings/item_types/sentiments/sources`，另有 `q/tickers/event_types/since/dedup/display`。 | 未对齐。`kinds/forms` 应退出主筛选；`event_types` 没有可见控件，是幽灵状态。 |
| 41-43 | `activeCount()` 仍统计 `kinds/forms`。 | 未对齐，删除筛选后必须同步改，避免角标虚高。 |
| 103-117 | `buildQuery()` 将 `markets/kinds/forms/positionings/item_types/sentiments/sources` 原样传给 `/v1/items`。 | 新字段已透传，但旧字段未退出；没有赛道筛选路径。 |
| 118-128 | `load(cursor)` 直接请求 `/v1/items`，追加分页数据并使用 `next_cursor`。 | 原生分页已可用，改包装端点时必须保住追加语义；还应加请求序号，避免快速点 chips 时旧响应覆盖新响应。 |
| 136-140 | `clearAll()` 仍清理旧 `kinds/forms` 和不可见 `event_types`。 | 未对齐，需与最终筛选模型一次性收敛。 |
| 149-160 | `loadDict()` 从 `/v1/sources` 聚合 `markets/forms/positionings`，并完整保存 `d.sources`。源对象中的 `brief/positioning/markets` 已经到达浏览器。 | 已具备前端来源 join 的数据条件；无需给源侧条目加字段。 |
| 168-173 | `sourceTitle(id)` 每次用 `.find()` 查来源，随后回退 `/stats` 和 ID。 | 功能可用，但卡片批量 join 应改成 `sourceMap`，把每次 O(n) 查找降为 O(1)。 |
| 191-205 | `registerSubs()` 有 `location.hash...startsWith("/news")` 守卫。 | 已修复，实施时原样保留，不得回退。 |
| 245-254 | 连续出现两个同名 `<h4>类型</h4>`：第一组绑定旧六值 `enums.kinds`，第二组绑定新四值 `enums.item_types`。 | 明确 bug。删除第一组与所有 `kinds` 页面状态，只保留新四值“类型”。 |
| 255-269 | 情绪、定位已存在；形态仍作为独立主筛选。 | 定位/情绪保留；形态删除，原因是它是采集技术形态，与条目“类型”语义重叠。 |
| 297-321 | 卡片把时间、来源、源/条目标签、事件、重复数全部堆在一条 `.news-meta` 中，标题和正文也拼为一行。 | 未满足双框需求，且源级、条目级语义混杂；整块替换。 |
| 359-407 | 右栏有市场覆盖、`stats.item_types` 类型分布、产量最高来源、热门标的、数据站。 | 类型已对齐；缺少 `stats.positionings` 的“定位分布”。 |
| 420-451 | 来源详情已有 positioning 列；说明单元格使用 `s.brief || s.title`。 | 数据已齐。建议把来源名与简介拆列、将旧 `kind` 明示为“采集类型”，避免再次与条目“类型”混淆。 |

### 1.2 `workbench/web/js/pages/article.js`

| 行号 | 现状 | 判断 |
|---:|---|---|
| 15、19 | 字典仍是 `markets/channels`，推荐筛选状态仍是 `recoMarkets/recoChannels`。 | 未对齐，应改成市场、定位、类型三组。 |
| 49-66 | `registerSubs()` 有 `/article` 路由守卫。 | 已修复，原样保留。 |
| 80-90 | `loadDict()` 从 `/v1/sources` 聚合 legacy `s.channel`，但没有保留全量 sources。 | 未对齐；改为保留 sources 供卡片 join，不再消费 `channel`。 |
| 91-105 | `loadReco()` 向 `/recommend` 传 `markets/channels`。 | 未对齐；改传 `markets/positionings/item_types`。 |
| 262-276 | 推荐筛选模板只有市场和渠道。 | 未对齐；渠道替换成定位，并新增类型。 |
| 282-298 | 推荐卡片复用单行 `.news-meta` 堆徽章，只展示市场、情绪、重复数。 | 未对齐；改为双框简化版，并补类型、定位、赛道、标的和来源简介。 |

### 1.3 `workbench/server/reco.py`

| 行号 | 现状 | 判断 |
|---:|---|---|
| 5、15 | 文档与 `_OFFICIAL` 仍把 `exchange/media_official/data_vendor/broker_research` 旧 `channel` 枚举当“官方/机构”。 | 未对齐。源侧权威维度已变为 `positioning`。 |
| 24-25 | `score_of()` 以 `it.get("channel") in _OFFICIAL` 给“机构源 +2”。 | bug：新条目应按 `positioning in {"官方", "机构"}` 加分，并在原因中分别显示“官方源”或“机构源”。 |
| 36-50 | `recommend()` 接收并透传 `kinds/channels`。 | 未对齐；签名与上游 query 改为 `item_types/positionings`。 |

### 1.4 `workbench/server/stats.py`

| 行号 | 现状 | 判断 |
|---:|---|---|
| 20-31 | 最多读取 4 页、每页 1000 条，并返回 `truncated`。 | 可作为赛道包装端点扫描上限与截断语义的参照，但不要直接耦合其私有函数。 |
| 72-83 | `sources_detail` 已返回 `positioning/brief/markets`，同时保留 legacy `channel/kind`。 | 数据已对齐，来源详情只需前端重排列。 |
| 97-98 | 已聚合 `item_types` 与 `positionings`。 | 已对齐，无需修改；定位分布只需 `news.js` 增加条卡。 |

### 1.5 `workbench/server/app.py`

| 行号 | 现状 | 判断 |
|---:|---|---|
| 30-32 | `/wb-api/v1/{path:path}` 调 `proxy.forward()`，query 原样透传。 | 已对齐 GET-only 原则；继续保留。赛道筛选另建工作台包装端点，不改变纯代理语义。 |
| 130-136 | `/wb-api/recommend` 签名为 `since/markets/kinds/channels/limit`。 | 未对齐；改为 `since/markets/positionings/item_types/limit`。 |
| 211-216 | 非 `/wb-api` 静态资源响应统一 `Cache-Control: no-cache`。 | 已对齐；仍需 bump URL 版本号，防 webview/中间缓存混载。 |

### 1.6 `workbench/server/proxy.py`

| 行号 | 现状 | 判断 |
|---:|---|---|
| 21-32 | `forward()` 只构造 GET 请求，保留原 query，并在服务端注入 Bearer key。 | 已对齐，不修改。 |
| 71-91 | `fetch_json()` 为 stats/reco 等服务端聚合提供同一 GET 通道。 | 新赛道包装端点复用它，不能直接 import 源侧 store/taxonomy。 |

### 1.7 `workbench/web/css/app.css`

| 行号 | 现状 | 判断 |
|---:|---|---|
| 15-63 | 深浅主题均定义了完整 oklch token。 | 新样式只引用现有变量，不新增硬编码主题色。 |
| 139-163 | 已有 `.badge` 与 `.chip` 语义样式。 | 标签继续复用；只补层级赛道、双框布局和降级态。 |
| 165-192 | 三栏布局和信息流样式已存在；`.news-card` 当前是单列行式，`.news-meta` 承载所有标签。 | 保留外层 1px 行分隔，内层增加两个有边界的语义框。 |
| 335-339 | 仅处理 1100px 下隐藏右栏，未处理双框窄屏折叠。 | 新增 760px/1100px 响应式规则。 |

### 1.8 `workbench/web/index.html`

| 行号 | 现状 | 判断 |
|---:|---|---|
| 7、51-57 | CSS 与所有本地 JS 都使用 `?v=0903a`。 | 实施完成统一 bump 为 `?v=0903b`，不得只改其中两个文件造成新旧混载。 |

### 1.9 `global-news-sources/sources/taxonomy.py`（只读）

| 行号 | 现状 | 对工作台的约束 |
|---:|---|---|
| 13 | `MARKETS` 为 8 个封闭值。 | 工作台按此顺序展示，不按字典排序破坏固定口径。 |
| 30 | `POSITIONINGS` 为 5 个封闭值。 | 替换所有面向用户的 legacy channel。 |
| 57-61 | X 池 `ROLE_TO_POSITIONING` 已定义角色映射。 | 卡片可显示 `author_handle/author_role`，但定位仍以 source/条目 `positioning` 为准。 |
| 73 | `ITEM_TYPES` 为 4 个封闭值。 | 页面只保留这一组“类型”。 |
| 103-123 | `L1_L2` 定义 19 个封闭 L1 与封闭 L2。 | 本期筛选只做到 L1；L2/L3 用于卡片分层展示，不新增自由筛选。 |

结论：`taxonomy.py` 是唯一业务真相，但源侧目前没有 taxonomy metadata API。在禁止改源侧的前提下，工作台只能保存一份**只读展示镜像**；镜像集中在一个工作台模块中，前端两页不得各复制一套。实施时在单元测试中逐项锁定 8/5/4/19 值，并在注释标注来源 commit `0188415`；待源侧未来公开字典端点后，立即改为 GET 获取。

### 1.10 `global-news-sources/sources/serve.py`（只读）

| 行号 | 现状 | 对工作台的约束 |
|---:|---|---|
| 133-140 | `/v1/sources` 支持市场、定位等源级过滤，并返回完整源对象。 | 来源 join 使用该响应，不要求源侧注入 brief。 |
| 151-179 | `/v1/items` 支持 `markets/kinds/info_types/channels/forms/item_types/positionings/sources/tickers/sentiments/event_types/q/since/limit/cursor/dedup/display`。其中 `kinds/info_types/channels/forms` 是兼容字段；**没有 sectors 参数**。 | 新 UI 只使用新维度；赛道 L1 不能伪装成 `/v1/items` 原生参数。 |
| 166-173 | `display=1` 时以 `text_display/title_display` 替换显示文本，并把原文放进 `text_src/title_src`。 | 双框内容区继续保留“查看译前原文”。 |
| 179 | `total` 当前是本次 `out` 长度，不是全库精确命中总数。 | 不得在赛道包装端点把两种口径混为一谈；响应要显式给 `truncated/total_relation`。 |

硬约束结论：不修改 `taxonomy.py`、`serve.py` 或任何 `global-news-sources/` 文件；运行中的 8787 是旧进程，验证前必须重启，否则新键不会出现。

## 2. 改动清单

### 2.1 新建 `workbench/server/tag_options.py`

1. 集中定义 `MARKETS/POSITIONINGS/ITEM_TYPES/SECTOR_L1` 四个 tuple，值和顺序逐字对齐 `taxonomy.py@0188415`。这是源侧暂未提供枚举 API 时的工作台展示镜像，不承载归一化或打标逻辑。
2. 提供 `public_options()` 返回 JSON 数组，供前端两页共用；在 `app.py` 暴露 `GET /wb-api/tag-options`。
3. 增加模块注释：禁止在 `news.js/article.js` 再复制枚举；未来 `/v1/taxonomy` 可用时删除本模块镜像。
4. 理由：集中一份镜像比两个页面各自硬编码更不易漂移。被否方案“从当前 items/sources 动态聚合”只能得到已出现的值，无法保证完整 8/5/4/19 封闭枚举。

### 2.2 新建 `workbench/server/items.py`

实现只读的赛道过滤包装器 `query(params) -> dict`：

1. 输入白名单与源侧 `/v1/items` 一致，但新增工作台专用 `sector_l1s`；禁止把该参数传给 8787。
2. `sector_l1s` 为空时，删除工作台专用参数后原样调用 `proxy.fetch_json("items?... ")`，保留源侧 cursor 和响应口径。
3. `sector_l1s` 非空时：
   - 依据 `tag_options.SECTOR_L1` 校验并去重；非法值返回 400。
   - 固定按源侧 `limit=1000`、最多 4 页扫描，其他市场/定位/类型/情绪/来源/q/tickers/since/dedup/display 参数继续下推。
   - 对每条的 `(it.get("sectors") or [])` 取 `path.split(">", 1)[0].strip()`；任一路径 L1 命中即保留（组内 OR，和其他筛选组 AND）。
   - 对过滤结果维持源侧时间顺序，以工作台游标 `wbsec1:<urlsafe-base64-json>` 分页。游标只保存 `offset` 与规范化 query 的 SHA-256 摘要；摘要不匹配返回 400，避免把旧游标用于新筛选。
   - 响应固定为 `items/next_cursor/total/truncated/total_relation`。扫描完源侧则 `total_relation:"exact"`；达到 4000 条仍有上游 cursor 时为 `"lower_bound"`，UI 显示“至少 N 条”。
4. 加 60 秒进程内缓存，key 为下推 query（不含 `cursor/limit`）加 `sector_l1s`；缓存完整过滤数组与 `truncated`，加载更多不重复扫 4000 条。
5. 包装器全程只用 `proxy.fetch_json()` GET，不 import `_store`，不落盘，不改变工作台只读边界。

明确选型：**采用工作台服务端包装过滤**。被否方案“浏览器只过滤当前 100 条”会产生假空页、漏结果和错误 total；被否方案“右栏点击后仅反查当前数据”仍不是真筛选；被否方案“本期只展示赛道”不能满足筛选区目标。代价是首次赛道查询最多读取 4000 条、延迟与配额增加，因此必须有 60 秒缓存、扫描上限和 `lower_bound` 明示。

### 2.3 修改 `workbench/server/app.py`

1. 导入 `items` 与 `tag_options`。
2. 在纯代理路由附近新增 `GET /wb-api/tag-options`；只返回展示枚举。
3. 新增 `GET /wb-api/items` 包装端点。建议接收 `Request`，由 `items.query(dict(request.query_params.multi_items()))` 统一解析，捕获参数错误为 400、`proxy.UpstreamError` 为原状态码或 502。
4. 保留 30-32 行 `/wb-api/v1/{path:path}` 原样；普通代理仍是 query 原样透传。
5. 将 130-136 行 `/wb-api/recommend` 签名改为：

   ```python
   def recommend(since: str = "", markets: str = "",
                 positionings: str = "", item_types: str = "",
                 limit: int = 50):
       return reco.recommend(since, markets, positionings, item_types, limit)
   ```

6. 不保留 UI 使用的 `kinds/channels` 别名，避免新老含义继续并存；若外部调用方需要兼容，应另开版本化契约，而不是静默合并。

### 2.4 修改 `workbench/server/reco.py`

1. 顶部规则说明改为“官方/机构定位 +2”。
2. 删除 `_OFFICIAL`，新增 `_AUTHORITATIVE_POSITIONINGS = {"官方", "机构"}`。
3. `score_of()` 改为：

   ```python
   positioning = it.get("positioning")
   if positioning in _AUTHORITATIVE_POSITIONINGS:
       parts.append((f"{positioning}源", 2))
   ```

4. `recommend()` 签名改为 `since, markets, positionings, item_types, limit`，向 8787 下推同名新参数，删除 `kinds/channels`。
5. `rule` 改成 `dup_count×3 + 官方/机构源+2 + 重大事件+2 + 情绪方向+1 + 标的×0.5`。
6. 推荐条目保持原字段，不在后端注入来源简介；前端和资讯页用同一 join 逻辑。

### 2.5 修改 `workbench/web/js/pages/news.js`

#### 状态与字典

1. `data().dict` 改为 `{ sources: [] }`；标签枚举从 `/tag-options` 装入 `tagOptions`，初始结构为四个空数组。
2. 删除 `enums.kinds`、`enums.info_types`；情绪仍可保留页面静态映射，因为 API 值/中文展示不同。
3. `f` 改为：

   ```js
   f: { markets: [], positionings: [], item_types: [], sector_l1s: [],
        sentiments: [], sources: [], q: "", tickers: "", since: "24h",
        dedup: true, display: true },
   sectorOpen: false,
   sectorQ: "",
   requestSeq: 0,
   ```

4. 删除 `kinds/forms/event_types` 状态。保留 `sources` 作为来源详情和右栏反查写入的隐藏筛选。
5. 新增 computed：`sourceMap`、`visibleSectorL1`、`positionBars/positionMax`；`activeCount` 只统计最终筛选项和 `q/tickers`。

#### 查询与并发

1. `buildQuery()` 只生成 `markets/positionings/item_types/sector_l1s/sentiments/sources/q/tickers/since/dedup/display/limit/cursor`。
2. `load()` 请求从 `/v1/items` 改为 `/items`。开始请求时保存 `const seq = ++this.requestSeq`；响应或异常处理前检查 `seq === this.requestSeq`，防止快速筛选的旧响应回写。
3. `reload()` 继续先清空 `items/nextCursor`，再加载第一页；`load(nextCursor)` 追加逻辑不变。
4. 读取 `d.total_relation`：`lower_bound` 时总数文案显示“至少”；不得把截断扫描结果写成精确总数。
5. `clearAll()` 与 active count 同步清理最终字段，不再引用已删除键。

#### 来源 join

1. `loadDict()` 并行获取 `/tag-options` 与 `/v1/sources`；字典失败时不阻断信息流，标签 options 失败显示明确错误而不是空白筛选器。
2. `sourceMap` 以 `s.id` 为 key。新增 `sourceInfo(it)`，查找顺序为 `source_id -> source 字段（若能匹配 id） -> 降级对象`：

   ```js
   sourceInfo(it) {
     const s = this.sourceMap[it.source_id] || {};
     return {
       title: s.title || it.source || it.source_id || "未知来源",
       brief: s.brief || "暂无来源简介",
       positioning: s.positioning || it.positioning || "",
       markets: (s.markets && s.markets.length) ? s.markets : (it.markets || []),
     };
   }
   ```

3. `sourceTitle()` 改为复用 `sourceMap`，保留 stats/ID 兜底。
4. 明确结论：**推荐前端 join**。理由是两页本来就必须读取 `/v1/sources` 做筛选/字典，响应到达后 Vue 会自动更新卡片，且不污染纯代理与推荐响应。被否方案“后端给每条注入 brief”会让 `/v1/items` 代理、赛道包装器和 `/recommend` 三条路径重复做 join、扩大每页 payload，并把展示数据耦合进条目契约。

#### 筛选模板

1. 245-249 行旧 `kinds` “类型”组整体删除；250-254 行新 `item_types` 组保留并改取 `tagOptions.item_types`。
2. 分组顺序固定为市场 → 定位 → 类型 → 赛道 → 情绪。
3. 赛道区默认只显示两行 chips；按钮显示“展开全部 19 / 收起”。展开后显示本地搜索框，按 L1 子串过滤；已选 L1 即使不匹配搜索也置顶显示，避免选中项消失。
4. 删除“形态”组。`q/tickers/since/dedup/display` 留在工具栏；来源筛选继续由来源详情/右栏注入并以可移除 chip 展示。

#### 双框卡片及辅助方法

1. 297-321 行信息流卡片整体替换为第 3.1 节模板。
2. 新增 `sectorParts(sec)`：按 `>` 切分、trim、最多取 3 段；空路径返回空数组。模板对数组一律使用 `(it.xxx || [])`，避免旧数据缺键时报错。
3. 将标题与正文拆开：`it.title` 有值才渲染标题，正文无值显示“（无正文）”。继续保留 `text_src` 展开和素材篮动作。
4. `event_type/dup_count` 保留为内容框辅助标签，避免此次视觉重构丢失既有信息。
5. X 池作者显示作为 P1 可选增强：`author_handle` 或 `author_role` 任一非空才显示；handle 已带 `@` 时不重复添加。它只展示身份，不参与定位计算或筛选。

#### 右栏与来源详情

1. 在“类型分布”后新增“定位分布”，读取现有 `stats.positionings`；行可点击 `pickPositioning()` 回填筛选并放开 since，与 `pickMarket()` 行为一致。
2. 类型分布也改为可点击，新增 `pickItemType()`；这不会引入新后端能力。
3. 来源详情列改为：条目数、源 ID、来源名、简介、市场、定位、采集类型、健康、TTL、耗时、上轮新增、操作。旧 `kind` 保留作诊断，但表头不得再叫“类型”。
4. 搜索 placeholder 改为“搜索源 ID / 来源名 / 简介”；搜索逻辑现有三字段已覆盖。简介列允许换行，CSS 的 `nth-child` 同步调整。
5. `registerSubs()` 的路由守卫、`mounted/unmounted` 生命周期原样保留。

### 2.6 修改 `workbench/web/js/pages/article.js`

1. `dict` 改为 `{ sources: [] }`，增加 `tagOptions`；删除 `channels`。
2. `recoMarkets/recoChannels` 改为 `recoMarkets/recoPositionings/recoItemTypes`。
3. `loadDict()` 与资讯页一样获取 `/tag-options` 和 `/v1/sources`，保留全量来源对象；建议把公共 join helpers 放在 `window.WB.tags`，若不抽公共文件则必须保持同名同兜底规则。
4. `loadReco()` 改传 `markets/positionings/item_types`，删除 `channels`。加入 `recoRequestSeq` 防旧响应覆盖。
5. 推荐筛选模板改为市场/定位/类型三组；这里不重复赛道筛选，保持推荐页简洁，推荐结果仍展示赛道。
6. 282-298 行推荐卡片替换为第 3.2 节简化双框模板；保留价值分、原因、原文链接和“加入生成”。
7. `scoreParts()` 继续展示服务端原因；验收时必须出现“官方源 +2”或“机构源 +2”，不得再出现由 channel 推导的泛化“机构源”。
8. `registerSubs()` 的 `/article` 路由守卫原样保留。

### 2.7 修改 `workbench/web/css/app.css`

按第 4 节完整追加样式。旧 `.news-meta` 暂留给其他页面兼容，但新双框模板不再用它承载混合标签。同步调整来源表简介列的 `nth-child`。

### 2.8 修改 `workbench/web/index.html`

把 7、51-57 行全部 `?v=0903a` 统一改成 `?v=0903b`。即使只改了 CSS、news.js、article.js，也全部统一 bump，避免长期出现多套版本号。

### 2.9 不修改的文件

- `workbench/server/stats.py`：已有 `item_types/positionings/brief`，无需后端改动。
- `workbench/server/proxy.py`：纯 GET 代理与鉴权注入已经正确。
- `global-news-sources/sources/taxonomy.py`、`serve.py` 及整个 `global-news-sources/`：严格零修改。
- `data/` 与前三板块状态文件：本功能无需写入任何运行时 JSON。

### 2.10 测试文件（实施时新增）

在 `workbench/server/tests/` 增加：

- `test_tag_options.py`：断言 8/5/4/19 枚举的值、顺序和无重复。
- `test_items.py`：覆盖 L1 多选 OR、跨组 AND、空/缺失 sectors、L2/L3 路径、4000 条截断、游标 query 摘要校验、缓存命中。
- `test_reco.py`：覆盖官方/机构 +2，大V/快讯源/新闻源不加分，且不读取 channel。

## 3. 双框卡片的 HTML 结构草案

### 3.1 资讯页完整版

以下片段整体替换 `news.js` 当前 297-321 行。旧 serve 未重启时，`item_type/positioning/sectors` 缺失均有显式降级，不会抛异常。

```html
<div class="feed">
  <article v-for="it in items" :key="it.id" class="news-card">
    <div class="news-card-pair">
      <aside class="news-source-box">
        <div class="source-kicker">来源信息</div>
        <div class="source-name">{{ sourceInfo(it).title }}</div>
        <div class="source-tags">
          <span v-if="sourceInfo(it).positioning" class="badge blue">
            {{ sourceInfo(it).positioning }}
          </span>
          <span v-else class="badge legacy" title="重启 8787 后将下发新定位字段">
            定位待同步
          </span>
          <span v-for="m in sourceInfo(it).markets" :key="m" class="badge">{{ m }}</span>
        </div>
        <p class="source-brief">{{ sourceInfo(it).brief }}</p>
        <div v-if="it.author_handle || it.author_role" class="source-author">
          <span v-if="it.author_handle" class="mono">{{ authorHandle(it.author_handle) }}</span>
          <span v-if="it.author_role">{{ it.author_role }}</span>
        </div>
      </aside>

      <section class="news-content-box">
        <div class="content-head">
          <div class="item-tags">
            <span v-if="it.item_type" class="badge blue">{{ it.item_type }}</span>
            <span v-else class="badge legacy" title="旧 8787 进程尚未下发 item_type">
              类型待同步
            </span>
            <span v-for="(sec, si) in (it.sectors || []).slice(0, 3)" :key="sec + ':' + si"
                  class="sector-path" :title="sec">
              <span v-for="(part, pi) in sectorParts(sec)" :key="pi"
                    class="sector-level" :class="'l' + (pi + 1)">{{ part }}</span>
            </span>
            <span v-if="(it.sectors || []).length > 3" class="badge"
                  :title="it.sectors.slice(3).join('\n')">+{{ it.sectors.length - 3 }}</span>
            <span v-if="it.sentiment" class="badge" :class="sentimentBadge(it.sentiment)">
              {{ sentimentText(it.sentiment) }}
            </span>
            <span v-for="t in (it.tickers || [])" :key="t" class="badge mono">{{ t }}</span>
            <span v-if="it.event_type" class="badge">{{ it.event_type }}</span>
            <span v-if="it.dup_count > 1" class="badge yellow">同事件 ×{{ it.dup_count }}</span>
          </div>
          <time class="content-time">{{ it.time || '时间未知' }}</time>
        </div>

        <h3 v-if="it.title" class="news-item-title">{{ it.title }}</h3>
        <div class="news-text">{{ it.text || '（无正文）' }}</div>
        <div v-if="expanded[it.id] && it.text_src" class="news-src-text">{{ it.text_src }}</div>

        <div class="news-actions">
          <a v-if="it.url" :href="it.url" target="_blank" rel="noopener">原文链接 ↗</a>
          <span v-if="it.text_src" class="act" @click="expanded[it.id] = !expanded[it.id]">
            {{ expanded[it.id] ? '收起原文' : '查看原文(译前)' }}
          </span>
          <span class="act" @click="addMaterial(it)">＋加入素材篮</span>
        </div>
      </section>
    </div>
  </article>
</div>
```

赛道展示结论：使用一个 `sector-path` 包住 L1/L2/L3 三段，三段分别设最大宽度并 ellipsis，hover 的 `title` 展示完整原串。默认最多展示前三条路径；超过三条时模板应使用 `(it.sectors || []).slice(0, 3)`，并补 `<span class="badge" :title="it.sectors.slice(3).join('\n')">+{{ it.sectors.length - 3 }}</span>`。这比把整个 `宏观与政策>货币政策>xxx` 作为一个长 badge 更易扫读，也不会把开放 L3 误当成 L1。被否方案“只显示 L1”会丢掉关键热点；被否方案“整串强制截成固定字符数”无法看出层级边界。

### 3.2 `article.js` 推荐页简化版

```html
<div class="feed reco-feed">
  <article v-for="it in recoItems" :key="it.id" class="news-card">
    <div class="news-card-pair compact">
      <aside class="news-source-box">
        <div class="source-kicker">来源信息</div>
        <div class="source-name">{{ sourceInfo(it).title }}</div>
        <div class="source-tags">
          <span v-if="sourceInfo(it).positioning" class="badge blue">
            {{ sourceInfo(it).positioning }}
          </span>
          <span v-else class="badge legacy">定位待同步</span>
          <span v-for="m in sourceInfo(it).markets" :key="m" class="badge">{{ m }}</span>
        </div>
        <p class="source-brief">{{ sourceInfo(it).brief }}</p>
        <div v-if="it.author_handle || it.author_role" class="source-author">
          <span v-if="it.author_handle" class="mono">{{ authorHandle(it.author_handle) }}</span>
          <span v-if="it.author_role">{{ it.author_role }}</span>
        </div>
      </aside>

      <section class="news-content-box">
        <div class="content-head">
          <div class="item-tags">
            <span class="badge blue" :title="scoreParts(it)">价值 {{ it.score }}</span>
            <span v-if="it.item_type" class="badge blue">{{ it.item_type }}</span>
            <span v-else class="badge legacy">类型待同步</span>
            <span v-for="(sec, si) in (it.sectors || []).slice(0, 3)"
                  :key="sec + ':' + si" class="sector-path" :title="sec">
              <span v-for="(part, pi) in sectorParts(sec)" :key="pi"
                    class="sector-level" :class="'l' + (pi + 1)">{{ part }}</span>
            </span>
            <span v-if="it.sentiment" class="badge" :class="sentimentBadge(it.sentiment)">
              {{ sentimentText(it.sentiment) }}
            </span>
            <span v-for="t in (it.tickers || [])" :key="t" class="badge mono">{{ t }}</span>
          </div>
          <time class="content-time">{{ it.time || '时间未知' }}</time>
        </div>
        <h3 v-if="it.title" class="news-item-title">{{ it.title }}</h3>
        <div class="news-text">{{ it.text || '（无正文）' }}</div>
        <div class="score-reasons">{{ scoreParts(it) || '暂无加分项' }}</div>
        <div class="news-actions">
          <a v-if="it.url" :href="it.url" target="_blank" rel="noopener">原文链接 ↗</a>
          <span class="act" @click="addToGen(it)">＋加入生成</span>
        </div>
      </section>
    </div>
  </article>
</div>
```

推荐版的明确简化：不显示 `event_type/dup_count` 徽章，二者已经进入 `scoreParts`；保留类型、赛道、情绪、标的和时间。来源框的 join 与降级规则必须和资讯页完全一致。

## 4. CSS 增补清单

将以下源码追加到 `app.css` 信息流段落之后。全部颜色来自现有 oklch token；不引入新色值、阴影或 emoji。

```css
/* 双框信息流：外层仍是 1px 行分隔，内层按来源/内容分语义框 */
.news-card-pair {
  display: grid;
  grid-template-columns: 176px minmax(0, 1fr);
  gap: var(--s2);
  align-items: stretch;
}
.news-card-pair.compact {
  grid-template-columns: 164px minmax(0, 1fr);
}
.news-source-box,
.news-content-box {
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: var(--r-ctl);
  background: var(--bg-card);
}
.news-source-box {
  padding: var(--s3);
  background: var(--bg-panel);
}
.news-content-box {
  padding: var(--s3) var(--s4);
}
.news-card:hover .news-source-box,
.news-card:hover .news-content-box {
  border-color: var(--border-light);
}

/* 来源框 */
.source-kicker {
  margin-bottom: var(--s1);
  color: var(--text-mute);
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.source-name {
  color: var(--text);
  font-size: 13px;
  font-weight: 650;
  line-height: 1.4;
  word-break: break-word;
}
.source-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s1);
  margin-top: 7px;
}
.source-brief {
  margin-top: var(--s2);
  color: var(--text-dim);
  font-size: 11.5px;
  line-height: 1.55;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 4;
  overflow: hidden;
}
.source-author {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: var(--s2);
  padding-top: var(--s2);
  border-top: 1px solid var(--border);
  color: var(--text-mute);
  font-size: 11px;
}

/* 内容框头部与正文 */
.content-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s3);
  margin-bottom: var(--s2);
}
.item-tags {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s1);
}
.content-time {
  flex-shrink: 0;
  color: var(--text-mute);
  font-family: var(--mono);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.news-item-title {
  margin: 0 0 var(--s1);
  color: var(--text);
  font-size: 14px;
  font-weight: 650;
  line-height: 1.5;
}
.score-reasons {
  margin-top: var(--s2);
  color: var(--text-mute);
  font-size: 11.5px;
}
.badge.legacy {
  color: var(--text-mute);
  border-style: dashed;
}

/* 赛道路径：保留层级、限制单段宽度，完整值由 title 提示 */
.sector-path {
  display: inline-flex;
  min-width: 0;
  max-width: 270px;
  align-items: center;
  overflow: hidden;
  border: 1px solid color-mix(in oklch, var(--yellow) 42%, var(--border));
  border-radius: var(--r-pill);
  background: color-mix(in oklch, var(--yellow) 8%, transparent);
  color: var(--yellow);
  font-size: 11px;
  line-height: 1.7;
}
.sector-level {
  display: inline-block;
  overflow: hidden;
  padding: 1px 6px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sector-level.l1 { max-width: 92px; font-weight: 600; }
.sector-level.l2 { max-width: 92px; color: var(--text-dim); }
.sector-level.l3 { max-width: 72px; color: var(--text-mute); }
.sector-level + .sector-level::before {
  content: ">";
  margin-right: 6px;
  color: var(--text-mute);
}

/* 19 个 L1 chips 默认收成两行，展开后允许本地搜索 */
.sector-filter-box {
  max-height: 62px;
  overflow: hidden;
}
.sector-filter-box.open {
  max-height: none;
}
.sector-filter-tools {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s2);
  margin: 3px 0 7px;
}
.sector-filter-tools input[type=text] {
  min-width: 0;
  width: 132px;
}
.filter-toggle {
  color: var(--accent);
  font-size: 11.5px;
  cursor: pointer;
  white-space: nowrap;
}

/* 来源详情拆出“来源名/简介”后，简介列允许换行 */
table.reg td.source-brief-cell {
  min-width: 220px;
  max-width: 380px;
  white-space: normal;
  color: var(--text-dim);
}

@media (max-width: 1100px) {
  .news-card-pair,
  .news-card-pair.compact {
    grid-template-columns: 152px minmax(0, 1fr);
  }
}
@media (max-width: 760px) {
  .news-card-pair,
  .news-card-pair.compact {
    grid-template-columns: 1fr;
  }
  .source-brief {
    -webkit-line-clamp: 2;
  }
  .content-head {
    flex-direction: column-reverse;
    gap: var(--s1);
  }
  .sector-path {
    max-width: 100%;
  }
}
```

用途对应：

- `.news-card-pair/.news-source-box/.news-content-box`：建立并排双框，不改变 `.feed/.news-card` 的外层分隔语义。
- `.source-*`：让来源名、源级标签、brief、X 作者形成独立信息层级。
- `.content-*`：把条目标签与时间分开，标题与正文分开。
- `.sector-*`：把 L1/L2/L3 分段显示并限制长度。
- `.badge.legacy`：明确标记旧进程缺字段，而不是让用户误以为“无标签”。
- `.sector-filter-*`：19 个 L1 默认两行收口，展开后搜索。
- 两个 media query：中宽压缩来源框，窄屏改上下双框，避免横向挤压。

## 5. 筛选区最终分组

| 组名 | 数据源 | 交互 | 对应参数 |
|---|---|---|---|
| 市场 | `/wb-api/tag-options` 的 8 个封闭枚举，顺序为全球/美国/A股/香港/台湾/日本/韩国/土耳其 | 8 个 chips，组内多选 OR | 源侧 `/v1/items?markets=`，由 `/wb-api/items` 下推 |
| 定位 | `/wb-api/tag-options` 的 5 个封闭枚举 | 5 个 chips，组内多选 OR | 源侧 `positionings=`，下推 |
| 类型 | `/wb-api/tag-options` 的 4 个封闭枚举 | 4 个 chips，组内多选 OR；页面唯一名为“类型”的组 | 源侧 `item_types=`，下推 |
| 赛道 | `/wb-api/tag-options` 的 19 个封闭 L1 | chips 默认两行；展开全部后本地搜索；已选项置顶；组内多选 OR | **无源侧参数**；工作台 `/wb-api/items?sector_l1s=` 扫描过滤 |
| 情绪 | 页面展示映射 `bull/bear/neutral -> 利好/利空/中性` | 3 个 chips，组内多选 OR | 源侧 `sentiments=`，下推 |
| 关键词 | 用户输入 | 工具栏输入，回车应用 | 源侧 `q=`，下推 |
| 标的 | 用户输入 | 工具栏输入，逗号分隔，回车应用 | 源侧 `tickers=`，下推 |
| 时间 | 固定 `1h/4h/24h/3d/全部` | select，立即应用 | 源侧 `since=`，下推 |
| 来源 | `/v1/sources`；不占左栏主筛选 | 从来源详情或右栏点击注入，工具栏显示可移除 chip | 源侧 `sources=`，下推 |
| 展示选项 | 页面固定 | checkbox：折叠同事件、中文优先 | 源侧 `dedup/display`，下推 |

筛选逻辑统一为：同组多选 OR、不同组之间 AND。赛道 L1 与其他组也是 AND，由包装端点在源侧已下推过滤后的结果上再筛。

明确删除/不展示项：

- **删除 `kinds` 六值组**：它是旧采集形态，且造成两个“类型”重名 bug；相关 state、active count、query、clear 逻辑一并删除。
- **删除 `forms` 主筛选组**：结论是不保留。它是载体/抓取形态，用户选内容时价值低，且与条目类型重叠。代价是高级排障不能从资讯页按 form 筛；可继续通过源 CLI/API 或来源详情的“采集类型”诊断。
- **删除 `info_types` 前端枚举**：当前没有模板入口，且新“类型”已经是面向用户的投影。源 API 的兼容参数不等于 UI 必须暴露。
- **删除 `event_types` 幽灵状态**：当前无控件却参与 clear/query，容易形成不可见筛选。事件类型仍在卡片展示和推荐打分中；未来若正式开放，应作为独立需求重新加完整控件。
- **删除 channels UI 与推荐参数**：以定位五值完全替代。

赛道分页/total 口径：

- 未选赛道时，`/wb-api/items` 返回源侧原生响应，原 cursor 不改写。
- 选赛道时，工作台最多扫描 4000 条后过滤，用 `wbsec1:` 自有 cursor 对过滤数组分页。
- 扫描完整时 `total_relation=exact`；达到上限仍有上游页时 `total_relation=lower_bound`，UI 必须显示“至少 N 条（扫描上限 4000）”。
- 不允许把某一上游页过滤后的条数当全局 total，也不允许生成空页后仍给可点击 cursor。

## 6. 验证步骤清单

### 6.1 启动前静态与单元验证

1. 确认 `git diff --name-only` 只包含计划内的 workbench 文件、测试文件和 `workbench/web/index.html`；确认 `global-news-sources/`、`data/`、账本文件没有变化。
2. 运行 workbench 后端测试，重点检查枚举数为 8/5/4/19、赛道 cursor 摘要、4000 条截断、官方/机构加分。
3. 搜索残留：资讯页不得再出现 `enums.kinds/f.kinds/f.forms/info_types`；推荐链路不得再出现 `recoChannels/channels/_OFFICIAL`。

### 6.2 必须先重启 8787 数据站

1. 在当前运行 8787 的终端按 `Ctrl+C` 正常停止旧进程；不要同时启动第二个端口冲突进程。
2. 从仓库根目录重新运行：

   ```powershell
   py -3.11 cli.py sources serve --port 8787
   ```

3. 另开终端验证新进程响应：

   ```powershell
   Invoke-RestMethod 'http://127.0.0.1:8787/v1/items?limit=2&display=1'
   Invoke-RestMethod 'http://127.0.0.1:8787/v1/sources'
   ```

4. 检查至少一个新条目 JSON 出现 `item_type`、`positioning`；检查 sources 对象出现 `brief/positioning/markets`。若旧库存个别条目仍缺键，允许卡片显示“类型待同步/定位待同步”，但不能出现 JS 错误。

### 6.3 启动 8788 工作台

1. 运行：

   ```powershell
   py -3.11 cli.py workbench serve --port 8788
   ```

2. 打开 `http://127.0.0.1:8788/`，开发者工具确认 CSS/news.js/article.js 都命中 `v=0903b`，响应为 `Cache-Control: no-cache`，控制台无异常。
3. 请求 `/wb-api/tag-options`，人工核对 8/5/4/19 个值；请求 `/wb-api/items?sector_l1s=AI与算力&limit=20`，确认每条至少一条 sectors 路径以该 L1 开头。

### 6.4 资讯页人工验证

1. 筛选组顺序为市场/定位/类型/赛道/情绪；页面只有一个“类型”，无“形态/渠道”。
2. 各组选中/取消、清空单组、清空全部后，角标数量、URL query、结果同步；快速连续点击不被旧响应覆盖。
3. 展开赛道显示 19 个 L1，本地搜索有效，已选项不会因搜索消失；多选赛道为 OR，与市场/定位/类型为 AND。
4. 赛道结果超过扫描上限时显示“至少 N 条”，加载更多使用 `wbsec1:` cursor，无重复、无漏接、无假空页；改变任一筛选后旧 cursor 被清空。
5. 每条均为左来源框、右内容框：左边只放来源名、定位、源市场、brief；右边放类型、分层赛道、情绪、标的、时间、标题和正文。两边标签不再混在一条 `.news-meta`。
6. 长赛道显示为 L1/L2/L3 分段，单段 ellipsis，hover 可看完整路径；超过三条显示 `+N`。
7. X 池条目若有作者字段，显示一次规范化 handle 与 role；普通条目不留空白作者区。
8. `display=1` 时正文为译文，“查看原文(译前)”能展开/收起 `text_src`；无 `text_src` 不显示动作。
9. 用模拟/存量缺键条目验证降级：缺 `item_type/positioning/sectors/tickers/markets/title/text` 不报错，显示约定兜底。
10. 右栏新增“定位分布”；点击定位、市场、来源、标的、类型均能反查信息流。类型分布取新四值，不出现旧 flash 等值。
11. 来源详情表显示来源名、简介、市场、定位和“采集类型”；搜索源 ID/来源名/简介、各列正反排序正常。

### 6.5 图文页推荐信息子页人工验证

1. 筛选 chips 只有市场/定位/类型；请求 `/wb-api/recommend` 只含 `markets/positionings/item_types`，不含 `channels/kinds`。
2. 推荐卡片是双框简化版，来源 brief join 正常，类型/定位缺失时有降级，赛道长路径不撑破布局。
3. 准备 `positioning=官方`、`机构`、`大V` 各一条：前两者分数构成分别出现“官方源 +2”“机构源 +2”，大V不加这 2 分；即使条目仍带 legacy channel，也不得影响结果。
4. `scoreParts`、价值分、时间、原文链接和“加入生成”正常；加入后跳到内容生成且素材只增加一次。

### 6.6 回归验证

1. `news.js registerSubs()` 的 `/news` 守卫和 `article.js registerSubs()` 的 `/article` 守卫仍在；从资讯快速切到图文后，迟到请求不能覆盖左侧子菜单。
2. 资讯页“加载更多”继续按 cursor 追加，不覆盖首屏；普通无赛道筛选仍使用上游原生 cursor。
3. `addMaterial(it)` 与推荐页 `addToGen(it)` 均保持 `WB.basket` 去重和跨页同步。
4. 来源详情默认排序、点表头反向、搜索、单源“筛选”跳回 feed 均正常。
5. 右栏 stats 60 秒缓存行为不变；定位分布为空时显示空态而非报错。
6. 窄于 1100px 时右栏按旧规则隐藏，双框仍可用；窄于 760px 时来源框在上、内容框在下，无横向滚动。
7. 设置页数据源连接、顶栏健康灯、图文其他三个子页、视频/追踪页无视觉或路由回归。
8. 最后再次检查 `git diff --stat` 与 `git status --short`：不得出现 `global-news-sources/`、`data/`、`auto-publisher/` 变化；不得修改发布账本或触发任何发布命令。
