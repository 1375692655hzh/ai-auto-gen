# 08-cursor-tags — 前端工作台匹配源侧新标签体系(双标签制)更改计划

> 岗位：方案设计岗(cursor 引擎)。**只出计划，不动代码。**
> 依据commit：源侧 `0188415`(2026-09-03 双标签制, 单一真相 `global-news-sources/sources/taxonomy.py`)。
> 本计划所有改动均在 `workbench/` 与 `workbench/web/` 内, 不动 `global-news-sources/` 任何文件;
> workbench 对三板块保持只读, 只写 `data/workbench/*.json`(本期甚至不需要写)。

---

## 0. 名词对齐(全文统一)

| 层 | 标签 | 值域 | 载体字段 |
|---|---|---|---|
| 源级 | 市场 | 8值封闭 | `/v1/sources` 源对象 `.markets` |
| 源级 | 定位 | 5值封闭(官方/机构/大V/快讯源/新闻源) | 源对象 `.positioning` / 条目 `.positioning`(X池按 author_role 派生) |
| 源级 | 简介 | 一句话 | 源对象 `.brief` |
| 条目级 | 市场 | 8值封闭 | 条目 `.markets[]` |
| 条目级 | 类型 | 4值封闭(聚合/快讯/资讯/分析) | 条目 `.item_type` |
| 条目级 | 赛道 | L1(19封闭)>L2(封闭)>L3(开放≤12字) | 条目 `.sectors[]`("L1>L2[>L3]") |
| 条目级 | 情绪/标的/事件 | bull/bear/neutral 等 | `.sentiment` `.tickers[]` `.event_type` `.dup_count` |

旧体系字段(条目 `.kind` `.channel` `.form`、源 `.channel`)在新 UI 中**不再作为筛选维度出现**; 服务端兼容保留, 前端删除入口。

---

## 1. 现状审计(已读码确认, 行号为 HEAD)

### 1.1 `workbench/web/js/pages/news.js`(458 行)

**已对新体系的部分(保留)**:
- `enums.item_types` 四值、`enums.positionings` 五值(L20-25)。
- `f.positionings` / `f.item_types` / `f.sentiments` 已进 `buildQuery`(L103-117), serve 侧 `/v1/items` 已支持 `item_types`/`positionings` 过滤(serve.py L151-166, store.query L441-448 实参确认)。
- 右栏「类型分布」已用 `stats.item_types`(L52, 模板 L369-378)。
- 来源详情表已有 `positioning` 列与 `brief` 展示(L426-443)。

**Bug 与旧体系残留(要改)**:
1. **双"类型"组重名 bug(必修)**: 模板 L245-254 两个相邻 `.filter-group` 标题都是"类型"——第一组 `enums.kinds` 六值(flash/peer_article/calendar/market/announcement/evidence)是旧 kind 形态, 第二组才是新 `item_types` 四值。
2. `enums.kinds`/`enums.info_types`(L18-22)残留; `f.kinds`/`f.forms`/`dict.forms`(L16, L28)残留; "形态"筛选组(L265-269)是抓取形态(rss/api…), 属源属性, 新体系下对内容筛选无意义。
3. `buildQuery`/`clearAll`/`activeCount` 仍携带 `kinds`/`forms`(L42, L105, L137)。
4. **条目卡片全徽章堆一条 `.news-meta`**(L299-310): 时间/来源/市场×n/类型/定位/赛道×n/情绪/事件/同事件 9 类徽章混排, 长赛道("宏观与政策>货币政策>xxx")直接撑爆换行。
5. **无赛道筛选**(serve/store 均无 sectors 过滤参数, store.query 签名已确认无 sectors 入参)——这是新体系下必须补的维度, 且只能在 workbench 侧做(见 §5.4)。
6. 右栏无「定位分布」卡(`stats.positionings` 服务端已聚合, stats.py L98, 前端未消费)。

### 1.2 `workbench/server/stats.py`(108 行)

- 已聚合 `item_types`(L97)、`positionings`(L98); `sources_detail` 已带 `positioning`/`brief`(L78)。
- 缺 `sectors_l1` 分布聚合(赛道筛选 chips 收口与潜在看板要用, 见 §5.4)。
- `kinds`/`channels` 聚合(L95-96)前端右栏并未消费(右栏只用 markets/item_types/top_sources/tickers), 可留可删——**建议保留**(零成本, 调试有用), 不列入改动。

### 1.3 `workbench/server/reco.py` + `app.py` recommend 路由

- `_OFFICIAL = {"exchange","media_official","data_vendor","broker_research"}`(reco.py L15)是**旧 channel 枚举**, 与新定位映射关系: exchange/media_official→官方, broker_research/data_vendor(*)→机构, 但 data_vendor 的 flash 源→快讯源会被旧规则误判加分。必须切 `positioning ∈ {官方, 机构}`。
- `recommend()`(L36-50)与 `app.py` L130-137 路由参数为 `since/markets/kinds/channels/limit`, 无 `positionings`/`item_types` 透传。
- 打分文案 "机构源"(L25)与 rule 串(L50)需同步新口径。

### 1.4 `workbench/web/js/pages/article.js`(542 行)

- `dict = {markets, channels}`(L15), `loadDict` 从 `/v1/sources` 聚合 `s.channel`(L80-90)——legacy 字段。
- 推荐信息子页筛选只有 市场 + 渠道 两组 chips(L266-275), `loadReco` 传 `channels`(L98)。
- 推荐卡片(L282-298)与资讯页同款堆徽章, 且无 item_type/positioning/sector 展示。

### 1.5 `workbench/web/css/app.css`

现有可复用类齐全(行号实测): `.card`(L117) `.badge + .green/.red/.yellow/.blue`(L139-145) `.chip + .on`(L156-162) `.filter-group`(L168) `.feed-toolbar`(L172) `.news-card/.news-meta/.news-text/.news-src-text/.news-actions/.tickers`(L179-193) `.bars/.bar-row/.bar-track/.bar-fill + .clickable`(L228-242) `.stat-mini-grid/.stat-mini`(L216-224) `.reg/.pill/.tbl`。双框卡片需新增少量类(见 §4), 风格沿用 oklch 变量与现有命名(kebab, 语义前缀)。

### 1.6 运行态注意

**当前 8787 serve 进程是旧代码**, 下发条目无 `item_type`/`positioning`/`author_*` 键——前端改造完成后必须重启 8787 才能看到效果(写入 §7 验证步骤第 1 步)。store.query 为 `SELECT *`, 重启后 `author_role/author_handle/text_src` 等列自然随行返回, 前端无需白名单。

---

## 2. 关键决策(先拍板, 后施工)

### 2.1 源简介 brief 的注入方式: **前端 join**(结论)

两个候选:

| 方案 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| A 前端 join ✅ | news.js `loadDict()` 已拉全量 `/v1/sources` 存 `dict.sources`; 加 `sourceInfo(id)` 查表方法, 模板里取 `.brief/.positioning/.markets` | 零后端改动; 数据现成(110 源字典常驻内存); 与现有 `sourceTitle()`(L169-174)模式完全一致; X 池条目 `author_handle` 本就随行 | 数据站挂时无 brief(此时 feed 本身也空, 无实际损失) |
| B 后端注入 | workbench 新增 `/wb-api/items` 包装: 拉 sources→按 source_id 注入 brief 再下发 | 前端模板干净 | 每条目冗余 brief 字符串(100 条/页 × ~40 字); 新增代理端点要维护 cursor/dedup/display 全参数透传; 违背"proxy 尽量薄"现状 |

**结论: A**。兜底链: `dict.sources` → `stats.sources`(sources_detail 也带 brief/positioning, stats.py L78) → 仅显示来源名。`sourceInfo(id)` 一次性实现, 模板与方法都走它。

### 2.2 reco "机构源"判断: 切 positioning

- `_OFFICIAL` 集合废弃, 改 `_TRUSTED_POS = {"官方", "机构"}`, `score_of` 里 `if it.get("positioning") in _TRUSTED_POS: parts.append(("官方/机构源", 2))`。
- 注意 X 池条目 positioning 由 `ROLE_TO_POSITIONING` 派生(taxonomy.py L57-61), media→新闻源/company→机构/分析师→大V, 口径自动正确, 无需特判。
- rule 文案改: `"dup_count×3 + 官方/机构源+2 + 重大事件+2 + 情绪方向+1 + 标的×0.5"`。

### 2.3 赛道筛选的执行层: **workbench 前端客户端过滤**(结论)

serve `/v1/items` 与 store.query 均无 sectors 参数(已核实签名), 且约束禁止改源侧。候选:

- **A(采纳)**: 赛道 L1 筛选在前端对已加载条目过滤——`computed feedItems()` 按 `f.sectors`(L1 多选)过滤 `items`(条目 sectors 任一路径首段命中即中)。配合"加载更多"自然生效; UI 在赛道组旁标注 `(作用于已加载条目)`。改动小、零服务端风险。
- B(不采纳, 记 follow-up): workbench 加服务端包装端点全量拉取后过滤分页。复杂度高收益低——L1 过滤是探索性操作, 用户通常会配合市场/时间窗先收窄, 已加载 100~数百条内过滤足够。
- follow-up(不改源侧本期不做): 若日后要全库赛道过滤, 正确位置是源侧 store.query 加 `sectors_l1` 参数(`LIKE 'L1>%'` 前缀匹配), 提 issue 给板块一。

### 2.4 赛道 L1 十九个 chips 的收口: **高频 top6 + 折叠展开**

- stats.py 新增 `sectors_l1` 聚合(见 §3.2), news.js 据此取 **top6 高频 L1** 常驻显示; 其余 13 个收进 `<span class="act">展开全部(19)</span>` 切换的折叠区(`showAllSectors` 布尔 data)。
- 19 值枚举前端硬编码(封闭值域, 对齐 taxonomy.py `L1_L2` 键序), 命名 `enums.sectors_l1`; 硬编码可接受是因为值域封闭且源侧漂移已被 `norm_sector` 收容——存量数据重启后即是正典。
- 每个 chip 带计数: `宏观与政策 37`(计数来自 stats.sectors_l1, 无计数显示 0 灰显亦可, 从简不灰)。

### 2.5 赛道标签的截断/分层展示(需求4)

条目 sectors 是 `"L1>L2[>L3]"` 字符串数组。展示策略:

- **主显示 = 分层两粒徽章**: 第一粒 `badge yellow` 显示 L1; 第二粒 `badge`(无色)显示 `L2` 或 `L2>L3`(末段路径), 全路径放 `:title` tooltip。
- **数量收口**: sectors 最多展开 2 条路径(4 粒徽章), 超出显示 `+n` 灰徽章, tooltip 列全量。
- 实现为 method `sectorParts(sec)` → `[l1, rest]`, 与 `visibleSectors(it)` → 前 2 条 + 剩余数。模板三个 `v-for` 内联即可, 不加组件。
- 理由: L1 是分类信号(一眼分区), L2/L3 是精度信息(需要时 hover); 全路径平铺是现行爆版的根因。

### 2.6 X 池作者 handle(需求3, 可选增强——采纳, 成本极低)

来源框底部: `v-if="it.author_handle"` 显示 `<span class="mono">@{{ it.author_handle }}</span>` + `author_role` 小 badge(灰)。条目 JSON 已随行(store L85 列确认), 纯模板增项。

---

## 3. 改动清单(文件级, 到函数/模板块)

### 3.1 `workbench/web/js/pages/news.js`(改动最大)

**data()**:
- 删 `enums.kinds`、`enums.info_types`(L18-22)。
- `enums` 增 `sectors_l1`: 19 值数组 `[["宏观与政策","宏观与政策"],…]`(按 taxonomy.py L104-123 键序, 单字符串数组亦可, 与现有二元组风格保持一致用二元组)。
- 删 `dict.forms`(L16); `dict` 增 `sectorsTop: []`(stats 聚合的高频 L1)。
- 删 `f.kinds`、`f.forms`(L28); `f` 增 `sectors: []`(L1 多选)。
- 增 `showAllSectors: false`。

**computed**:
- `activeCount`(L41-44): 数组改 `["markets","positionings","item_types","sentiments","sources","sectors"]`(删 kinds/forms, 增 sectors)。
- 增 `feedItems()`: `f.sectors.length ? this.items.filter(it => (it.sectors||[]).some(s => this.f.sectors.includes(String(s).split(">")[0]))) : this.items`。
- 增 `sectorBars()`: `this.stats ? this.stats.sectors_l1.slice(0, 8) : []`(右栏备选, 见 §6 决策: 右栏加定位分布卡, 赛道卡不加, 防右栏过长)。
- `typeBars`(L52)不动。

**methods**:
- `buildQuery`(L103-117): 删循环数组里 `kinds`/`forms`; **注意: sectors 不进 query**(客户端过滤, §2.3)。
- `clearAll`(L136-141): 同步删 kinds/forms、增 `this.f.sectors = []`。
- `loadDict`(L149-161): 删 `fm`(forms)聚合; 返回 `dict = {markets, positionings, sources, sectorsTop: []}`。
- 增 `sourceInfo(id)`: 先查 `dict.sources`, 再查 `stats.sources`, 返回源对象或 `null`(sourceTitle 重构为 `sourceInfo(id)?.title || id` 的薄封装, 保持向后兼容)。
- 增 `sectorParts(sec)`: `const p = String(sec).split(">"); return [p[0] || "", p.slice(1).join(">")]`。
- 增 `visibleSectors(it)`: `return (it.sectors || []).slice(0, 2)`; 增 `sectorsRest(it)`: 剩余条数。
- 增 `pickPositioning(p)`: `this.f.positionings = [p]; this.f.since = ""; this.reload()`(右栏定位条点击反查, 仿 pickMarket L180)。
- `loadStats`(L162-167)成功后: `this.dict.sectorsTop = (this.stats.sectors_l1 || []).slice(0, 6).map(r => r[0])`。
- `registerSubs`(L191-205)、`srcFilter`、`sortReg`、`pillClass` 等**一律不动**(路由守卫修复不回退)。

**模板(信息筛选子页)**:
- 左栏筛选卡(L237-271)整段重组, 最终分组见 §5: 删 kinds 组(修重名 bug)、删 forms 组; 新增定位组前移、赛道组(带折叠)。
- 中栏 feed `v-for="it in items"` 改 `v-for="it in feedItems"`; 卡片 `.news-card` 内部(L298-320)整体替换为 §3.5 双框结构。
- 右栏(L331-407): 「类型分布」卡之后插入「定位分布」卡(`sectorBars` 同款 bars 结构, 数据 `stats.positionings`, 行 `clickable` → `pickPositioning(r[0])`)。

**模板(来源详情子页)**:
- 定位列保留; "说明"列 `s.brief || s.title` 保留; **kind 列改名"形态"**(`<th>类型`→`<th>形态`, 消除与新"类型"的语义撞车); 其余不动。

### 3.2 `workbench/server/stats.py`

- `aggregate()` 的 `data` 字典(L86-104)增一行:
  ```python
  "sectors_l1": count(lambda i: [str(s).split(">")[0] for s in (i.get("sectors") or [])]),
  ```
  放在 `"item_types"` 之后。其余不动。60s 缓存逻辑不变。

### 3.3 `workbench/server/reco.py`

- 模块常量: 删 `_OFFICIAL`, 增 `_TRUSTED_POS = {"官方", "机构"}`。
- `score_of`: channel 判断改 `if it.get("positioning") in _TRUSTED_POS: parts.append(("官方/机构源", 2))`。
- `recommend(since, markets, kinds, channels, limit)` 签名增 `positionings: str = "", item_types: str = ""`; urlencode 字典同步透传(serve 已支持); rule 串更新为 §2.2 文案。
- `kinds`/`channels` 入参保留(向后兼容, 前端不再传)。

### 3.4 `workbench/server/app.py`

- recommend 路由(L130-137)签名增 `positionings: str = "", item_types: str = ""`, 调用改 `reco.recommend(since, markets, kinds, channels, positionings, item_types, limit)`(建议同步把 reco.recommend 改关键字调用防错位)。

### 3.5 `workbench/web/js/pages/article.js`(推荐信息子页)

- data: `dict` 改 `{markets: [], positionings: []}`; 删 `recoChannels`, 增 `recoPositionings: []`、`recoItemTypes: []`; `enums`(从简: 局部常量)positionings 五值 + item_types 四值, 与 news.js 同源手写。
- `loadDict`(L80-90): 删 channel 聚合, 增 `s.positioning` 聚合。
- `loadReco`(L91-105): 删 `channels` 传参, 增 `positionings`/`item_types` 传参。
- 模板筛选卡(L265-276): "渠道"组删除, 替换为「定位」组(enums.positionings chips → `recoToggle('recoPositionings', v)`)+「类型」组(item_types chips → `recoToggle('recoItemTypes', v)`); 市场组不动。
- 推荐卡片(L282-298)与资讯页双框对齐的**简化版**: 同一 `.nc-grid` 结构, 左框只放 来源名+定位+市场(不放 brief, 推荐场景密度优先), 右框 meta 行首粒固定为 `价值 {{it.score}}` 蓝 badge(title=scoreParts), 其余徽章同资讯页条目级规则; `scoreParts` 文本行保留。
- 其余子页(生成/发布/自动化)零改动。

### 3.6 `workbench/web/css/app.css`

新增类(全部追加在 `.tickers` 规则附近, 变量沿用 `--border/--bg/--bg-card/--text-mute/--text-dim/--accent/--accent-weak/--s2/--s3/--r-panel/--mono`):

```css
/* 双框信息流卡片(2026-09-03 双标签制) */
.nc-grid    { display: grid; grid-template-columns: 188px minmax(0, 1fr); gap: var(--s3); }
.nc-src     { border: 1px solid var(--border); border-radius: var(--r-panel);
              background: var(--bg); padding: 8px 10px; align-self: start;
              display: flex; flex-direction: column; gap: 6px; }
.nc-src .name { font-size: 12.5px; font-weight: 600; }
.nc-src .brief { font-size: 11.5px; color: var(--text-mute); line-height: 1.5;
                 display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.nc-src .who { font-family: var(--mono); font-size: 11px; color: var(--text-dim); }
.nc-body    { min-width: 0; }
.nc-badges  { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 5px; }
.nc-time    { font-family: var(--mono); font-size: 11px; color: var(--text-mute); margin-right: 2px; }
@media (max-width: 1280px) { .nc-grid { grid-template-columns: 1fr; } }   /* 窄屏左右框纵堆 */
```

`.news-meta` 保留(article 简化卡与存量其它处仍可用); `.news-card` 容器不变, 双框是其内部布局, hover 等既有行为不回归。

### 3.7 `workbench/web/index.html`

- 全部 `?v=0903a` → `?v=0903b`(7 处: app.css + 6 个 js)。静态资源虽有 `Cache-Control: no-cache`, 版本号双保险惯例保持。

---

## 4. 双框卡片 HTML 结构草案(news.js feed 卡片, 直接照抄级)

```html
<div v-for="it in feedItems" :key="it.id" class="news-card">
  <div class="nc-grid">
    <!-- 左框: 来源信息(源级标签 + 简介 + X作者) -->
    <div class="nc-src">
      <div class="name">{{ sourceTitle(it.source_id) }}</div>
      <div class="nc-badges" style="margin-bottom:0">
        <span v-if="it.positioning" class="badge blue">{{ it.positioning }}</span>
        <span v-for="m in (sourceInfo(it.source_id)?.markets || it.markets || [])" class="badge">{{ m }}</span>
      </div>
      <div class="brief" v-if="sourceInfo(it.source_id)?.brief">{{ sourceInfo(it.source_id).brief }}</div>
      <div class="who" v-if="it.author_handle">@{{ it.author_handle }}
        <span v-if="it.author_role" class="badge">{{ it.author_role }}</span></div>
    </div>
    <!-- 右框: 内容信息(条目级标签 + 时间点 + 标题正文 + 操作) -->
    <div class="nc-body">
      <div class="nc-badges">
        <span class="nc-time">{{ it.time }}</span>
        <span v-if="it.item_type" class="badge blue">{{ it.item_type }}</span>
        <template v-for="sec in visibleSectors(it)">
          <span class="badge yellow" :title="sec">{{ sectorParts(sec)[0] }}</span>
          <span v-if="sectorParts(sec)[1]" class="badge" :title="sec">{{ sectorParts(sec)[1] }}</span>
        </template>
        <span v-if="sectorsRest(it)" class="badge" :title="(it.sectors||[]).join('\n')">+{{ sectorsRest(it) }}</span>
        <span v-if="it.sentiment" class="badge" :class="sentimentBadge(it.sentiment)">{{ sentimentText(it.sentiment) }}</span>
        <span v-for="t in it.tickers" class="badge">{{ t }}</span>
        <span v-if="it.event_type" class="badge">{{ it.event_type }}</span>
        <span v-if="it.dup_count > 1" class="badge yellow">同事件 ×{{ it.dup_count }}</span>
      </div>
      <div class="news-text">{{ it.title ? it.title + ' — ' : '' }}{{ it.text }}</div>
      <div class="news-src-text" v-if="expanded[it.id] && it.text_src">{{ it.text_src }}</div>
      <div class="news-actions">
        <a v-if="it.url" :href="it.url" target="_blank" rel="noopener">原文链接 ↗</a>
        <span class="act" v-if="it.text_src" @click="expanded[it.id] = !expanded[it.id]">
          {{ expanded[it.id] ? '收起原文' : '查看原文(译前)' }}</span>
        <span class="act" @click="addMaterial(it)">＋加入素材篮</span>
      </div>
    </div>
  </div>
</div>
```

要点:
- 来源框市场徽章优先取**源对象 markets**(源级标签, 需求2 语义); 条目 markets 兜底(X 池账号无源对象时)。
- tickers 从原来的 `.tickers` 独立行收进条目级徽章行(它就是条目级标签), 删模板 L313 旧行与 CSS 无冲突(.tickers 类保留不用即可)。
- article.js 简化版: 左框仅 name+positioning+markets 三行, 右框首粒 `价值 x.x` 蓝 badge。

---

## 5. 筛选区最终分组(资讯页左栏, 需求5)

| 序 | 组 | 数据 | 交互 | 说明 |
|---|---|---|---|---|
| 1 | 市场(8) | `dict.markets`(/v1/sources 动态) | 多选 chips → `f.markets` | 保留原样; 重启后源对象已是新 8 值 |
| 2 | 定位(5) | `enums.positionings` | 多选 → `f.positionings` | 从第 4 位前移至第 2 位(源级维挨着市场) |
| 3 | 类型(4) | `enums.item_types` | 多选 → `f.item_types` | **唯一的"类型"组**(删 kinds 六值组 = 修重名 bug) |
| 4 | 赛道 L1(19) | 常驻 top6(`dict.sectorsTop`)+ 折叠其余 13 | 多选 → `f.sectors`(客户端过滤) | 组标题 `赛道 <span class="muted">作用于已加载</span>` + 尾部 `展开全部(19)/收起` act 链接 |
| 5 | 情绪(3) | `enums.sentiments` | 多选 → `f.sentiments` | 保留 |
| 6 | 事件(3) | 新增 `enums.event_types = [["macro","宏观"],["policy","政策"],["earnings","财报"]]` | 多选 → `f.event_types`(改数组) | 现 data 已有 `event_types` 字符串但无 UI; serve 支持 `event_types` 参数。改多选数组, buildQuery/clearAll 同步。**若求最小改动可本期不做, 标注可选** |

**删除**: kinds 六值组、形态(forms)组。`enums.info_types` 删(从未有 UI)。
**保留不动**: 搜索框 q、时间窗 since、折叠同事件 dedup、中文优先 display、标的过滤 tickers 输入框、来源 chips(f.sources 露出)、清空全部按钮。

---

## 6. 右栏与来源详情(补充决策)

- **右栏加「定位分布」卡: 加**。`stats.positionings` 现成, 插在「类型分布」之后, 五行 bars, `clickable → pickPositioning`。右栏总长 +1 卡可接受(1280px 以下右栏本就隐藏, app.css L337)。
- 右栏**不加**赛道分布卡(19 行太长; 赛道探索走左栏筛选)。
- 来源详情表: positioning/brief 列已存在, 仅"类型"列表头改"形态"(§3.1), 其余不动。

---

## 7. 验证步骤清单(按序执行)

**前置(关键, 缺了前面全白测)**:
1. 重启数据站 8787: 停掉旧 serve 进程 → `python cli.py sources serve` 重起(任务计划触发的是 refresh, serve 是常驻进程, 需人工重启)。
2. `curl -H "Authorization: Bearer <key>" "http://127.0.0.1:8787/v1/items?limit=3"` 确认返回条目含 `item_type`/`positioning`/`sectors` 键; 不含则查 serve 进程是否真重启。
3. `curl …/v1/sources?limit=…` 抽 3 个源确认 `positioning`/`brief` 非空、markets 为新 8 值(无"美股/港股")。

**workbench 起服务**:
4. `python -m workbench.server`(或既有启动方式, 8788), 浏览器硬刷(Ctrl+F5)。

**资讯页**:
5. 筛选区只剩一个"类型"组(4 值), 无"形态"组; 市场 chips 为新 8 值。
6. 卡片双框渲染: 左框来源名+定位+市场+简介(X 条目有 @handle), 右框条目徽章不混来源徽章; 长赛道显示为两粒徽章, hover 见全路径; sectors 多于 2 条出 `+n`。
7. 各组筛选单独与组合点选, 条目数变化合理; 赛道筛选只影响已加载条目且组旁有提示; "清空全部"后 feed 复原。
8. 右栏「定位分布」出现且点击反查; 「类型分布」仍正常。
9. 来源详情子页: 表头"形态", 定位列有值, 「筛选」跳回 feed 且左菜单高亮正常(registerSubs 不回退, 迟到的 load 回调不串页——切页快速来回点一次验证)。
10. 英文条目(display=1 默认)显示译文, "查看原文(译前)"展开 text_src。

**图文页**:
11. 推荐信息子页: 渠道 chips 消失, 定位/类型 chips 生效; 官方/机构源条目"为什么推荐"含 `官方/机构源 +2`(原"机构源"文案不再出现); 打分规则文案为新串。
12. 推荐卡片为简化双框, "＋加入生成"→ 内容生成页素材篮链路不变。

**回归**:
13. `python cli.py doctor --json` 全绿; workbench 其它页(视频/追踪/设置)打开无控制台报错(app.css 追加类不影响)。
14. `git status` 确认改动仅限: `workbench/web/js/pages/news.js`、`workbench/web/js/pages/article.js`、`workbench/web/css/app.css`、`workbench/web/index.html`、`workbench/server/stats.py`、`workbench/server/reco.py`、`workbench/server/app.py` 七个文件; `global-news-sources/` 零改动。

---

## 8. 风险与备注

1. **重启窗口期**: 8787 未重启时, 条目无 item_type/positioning, 新 UI 徽章与筛选为空但**不报错**(全部 `v-if` 防御), 属可接受降级; 验证清单第 1-2 步即防此坑。
2. **存量数据赛道漂移**: store 重启读库时存量 sectors 若未过 `norm_sector`(取决于 tagger 写库路径), 前端 `sectorParts` 对非法 L1 原样显示, 不影响渲染; L1 筛选只命中正典值。如发现大面积漂移, 属板块一数据治理, 不在本计划。
3. **sectors_top 时序**: `dict.sectorsTop` 依赖 loadStats 完成; stats 失败时赛道组折叠为 19 值全量平铺(`showAllSectors` 默认 false 时显示 `enums.sectors_l1` 前 6 兜底——实现取 `sectorsTop.length ? sectorsTop : enums.sectors_l1.slice(0,6)`)。
4. **reco 兼容**: `/wb-api/recommend` 新参数有默认值, 旧前端缓存页面(no-cache 下概率极低)不会 422。
5. 事件组(§5 第 6 组)标注可选: 做则 data/buildQuery/clearAll 三处同步把 `event_types` 从字符串改数组, 工作量约 15 行; 不做则把 `f.event_types` 残留字段一并删除, 别留死键。
