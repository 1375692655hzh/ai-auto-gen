# 工作台「X(Twitter) KOL 条目按账号展示」优化方案

> 文档性质：实施计划，不包含代码改动。审计基线为 2026-09-03 当前工作区；行号均指本文编写时的文件内容。目标是让 X 池条目按账号展示，同时保持板块四对前三板块只读、前端只访问同源 `/wb-api/*`、非 X 条目表现不变。

## 1. 现状审计

### 1.1 资讯页信息流

- `workbench/web/js/pages/news.js:37` 已有响应式 `expanded: {}`；当前仅在 `news.js:369-373` 控制 `text_src` 的“查看原文(译前)/收起原文”。正文 `it.text` 本身没有折叠状态。
- `news.js:175-181` 的 `loadDict()` 只请求 `/v1/sources`，并把源对象写入 `dict.sources`；`news.js:192-200` 的 `sourceInfo(id)`/`sourceTitle(id)` 也只按 `source_id` 查源级对象。这里不可能得到 131 个账号的 `name/role/note`，因此必须另开工作台端点，不能继续扩展 `loadDict()` 对 `/v1/sources` 的假设。
- 双框 `.nc-grid` 位于 `news.js:335-377`。左框在 `news.js:340` 用 `sourceTitle(it.source_id)` 显示池级标题；`news.js:343-344` 优先取 `sourceInfo(source_id).markets`，所以 X 条目会显示池源覆盖的六个市场，而没有使用条目已有的账号级 markets；`news.js:346-347` 显示池源 brief；`news.js:348-349` 才在 `.who` 再显示 `@author_handle + author_role`，造成账号身份与池级来源信息分离、handle 语义重复。
- 右框在 `news.js:352-375` 展示时间、条目级类型/赛道/情绪/标的等徽章，正文是 `news.js:368` 的 `.news-text`，没有截断；现有 `text_src` 展开逻辑不能同时承担正文展开，否则两个按钮会互相改变状态。
- `registerSubs()` 的路由守卫在 `news.js:226-239`，尤其是 `news.js:227-228` 的 `WB.shell` 与 `/news` 检查；本次不得改掉。五组筛选（市场、定位、类型、赛道、情绪）仍在 `news.js:274-304` 一带，赛道 L1/L2 分层辅助函数在 `news.js:206-212`，均保持。
- 右栏“产量最高的源”使用 `news.js:73-74` 的 `stats.top_sources`，点击执行 `news.js:215` 的 `pickSource(source_id)`；卡片模板在 `news.js:447-455`。因此 X 只会按 `twitter_kol_flash`、`twitter_kol_views` 两个池源显示。
- 定位分布卡位于 `news.js:437-445`，不得因新增 X 账号榜而替换或删除。

### 1.2 图文页“推荐信息”

- `workbench/web/js/pages/article.js:82-88` 同样只从 `/v1/sources` 汇总市场，当前没有账号字典。
- 推荐数据由 `article.js:90-104` 请求 `/recommend`；返回的是条目本身，因此已有的 `author_handle/author_role/markets/source` 可直接参与账号 join，不需要改推荐打分接口。
- 简化版双框位于 `article.js:293-329`。左框 `article.js:298-303` 仅显示 `it.source + positioning + it.markets + @handle`，没有账号简介、role、增强资料；右框正文 `article.js:321` 也不截断。
- `article.js:11-42` 当前 data 中没有展开字典；`article.js:51-70` 也有 `registerSubs()` 路由守卫（`article.js:52-53`），必须保留。

### 1.3 工作台后端与数据站代理

- `workbench/server/app.py:29-32` 用通配 GET `/wb-api/v1/{path:path}` 调 `proxy.forward()`；`app.py:35-40`、`app.py:70-106` 展示了本地聚合/只读视图端点的模式。新增 `/wb-api/x-accounts`、`/wb-api/x-profiles` 应是工作台本地 GET 端点，不应伪装成 `/v1/*` 数据站资源。
- `app.py:59-67` 的设置端点会写 `data/workbench/settings.json`；本方案新增的服务端 GET 端点不得写文件。Grok 缓存只由手动 CLI 写入。
- `workbench/server/views.py:18-25` 已集中声明仓库根和只读路径，`views.py:28-32` 的 `_read_json()` 是现有容错读取范式；适合在此增加 X 池/增强缓存的只读视图函数。
- `workbench/server/proxy.py:21-60` 明确只用 GET 转发到数据站并注入服务端保存的 Key；`proxy.py:71-93` 的 `fetch_json()` 是 stats/recommend 的服务端读通道。X 账号注册信息来自仓库 YAML、增强信息来自本地缓存，不经过 proxy，因此 `proxy.py` 本次不改。
- `workbench/server/stats.py:20-31` 最多抓 4 页 × 1000 条；`stats.py:38-45` 同时取 health/status/sources/items，并有 60 秒内存缓存（`stats.py:15-17,38-40`）。现有 `per_source` 与显示名在 `stats.py:62-65` 聚合，`top_sources` 在 `stats.py:101-102` 返回，天然只有两个 X 池源。
- 数据站的 `sources` 参数确实是源 id：`global-news-sources/sources/store.py:472-473` 对 `source_id IN (...)` 过滤；`q` 则在 `store.py:482-484` 对原始 `text/text_zh/title_zh` 做 LIKE。`serve.py:150-167` 将 `/v1/items` 的 `sources` 和 `q` 原样接入上述查询。

### 1.4 X 条目与池源注册

- 两个物理源的池级标题在 `global-news-sources/sources/builtin.py:144-155`，正是当前左框看到的“X大V快讯/观点(FxTwitter免登录池…)”。源级 markets/brief 在 `global-news-sources/sources/tags.py:31-32`，覆盖六个市场，只适合描述整个池。
- 基础池当前有 131 个 `accounts` 条目；字段实例见 `global-news-sources/config/twitter_pool.yaml:8-22`。当前工作区没有 `twitter_pool.local.yaml`。
- 抓取器在 `global-news-sources/fetchers/basic.py:439-448` 已把账号显示名写成 `source="X·<name>"`，写入 `author_role`、`author_handle`、账号级 `markets` 与 `lang`；其中 `basic.py:440` 还把 `@handle:` 前缀写入原始 `text`。因此本次是展示与补充元数据问题，不应修改抓取器或历史存储契约。

### 1.5 样式与静态资源版本

- `workbench/web/css/app.css:14-60` 已定义暗/亮两套 oklch 变量；新增样式只能使用 `var(--*)`/`color-mix(in oklch, ...)`，不引入硬编码主题色。
- `.news-text` 当前在 `app.css:186` 使用 `white-space: pre-wrap`；`.nc-grid/.nc-src/.nc-body` 在 `app.css:194-207`，已有 `.brief` 三行 clamp 和 1100px 单列响应式规则。新增类放在此 `.nc-*` 区块附近，并遵循 kebab 命名，例如 `.nc-account-line`、`.nc-content-text`、`.nc-expand-action`。
- `workbench/web/index.html:7,51-57` 的 CSS/JS 查询版本统一为 `0903b`。实施完成后所有这些引用一次性统一 bump 为 `0903c`，不能只改 news/article 两个脚本。

## 2. 池加载机制确认

以 `global-news-sources/fetchers/basic.py` 实码为唯一参照，工作台的读取结果必须保持以下语义：

1. 默认池路径由 `basic.py:315` 定为 `global-news-sources/config/twitter_pool.yaml`；抓取时也允许 conf 的 `pool_file` 覆盖（`basic.py:358-363`）。工作台没有源运行时 conf，固定读取仓库默认池即可，并在响应中只暴露 UI 所需字段。
2. `basic.py:363` 用 `yaml.safe_load(... ) or {}` 加载基础池。工作台也使用 PyYAML `safe_load`；项目已有 `pyyaml>=6.0`（`global-news-sources/requirements.txt:2`），不增加新依赖。
3. local 文件是基础池同目录的 `twitter_pool.local.yaml`（`basic.py:364-369`），已由仓库根 `.gitignore:50` 忽略。
4. 账号合并不是字段级 merge。`basic.py:370-374` 先以 `handle.lower()` 建基础字典，再逐个将 local 账号整个对象赋给同 key：同 handle 时 local **整条替换**基础条目，新 handle 追加；大小写不敏感，但源码合并阶段没有 `lstrip('@')`。工作台必须如实复制这一行为，不能把两个账号对象做 `dict.update()` 后保留基础字段。
5. `defaults`、`filters` 才做一层浅合并：仅当 local 的该段为 truthy 时，以基础字典为底、`merged.update(local_section)` 覆盖（`basic.py:375-379`）。X 账号 API 不下发这两段，但加载器应完成相同合并，以便计数/启用语义与抓取器一致。
6. local 解析/合并异常在 `basic.py:380-381` 被吞掉，基础池继续工作；随后只保留 `enabled` 默认为 true 且有 handle 的账号（`basic.py:382-387`）。工作台端点建议也降级到基础池，但额外通过服务端日志 warning 暴露 local 错误，不能让一个坏 local 文件拖垮资讯页。
7. 输出字典 key 在 API 边界统一规范为 `handle.lower().lstrip('@')`，对象内保留 YAML 中的原始 `handle`。这是前端 join 的规范，不改变上述“按 basic.py 合并”的顺序；若 local 写成 `@foo`，应先按源码合并完，再在输出阶段检测规范化 key 冲突并让后出现项获胜、记录 warning。

## 3. 改动清单

### 3.1 后端文件

#### `workbench/server/views.py`

新增只读常量与函数，保持该模块“只读视图”职责：

```python
TW_POOL = REPO / "global-news-sources" / "config" / "twitter_pool.yaml"
X_PROFILES = REPO / "data" / "workbench" / "x_profiles.json"

def load_x_pool() -> dict: ...
def x_accounts() -> dict[str, dict]: ...
def x_profiles() -> dict[str, dict]: ...
```

- `load_x_pool()` 精确实现第 2 节规则，只读 base/local，绝不回写 `global-news-sources`。
- `x_accounts()` 返回顶层 handle 字典，严格裁剪为 `{name, role, markets, note, homepage, tier, priority}`；key 为小写且无 `@`。即响应形态直接是：

```json
{
  "altinhisseler": {
    "name": "ALTIN HİSSELER",
    "role": "kol",
    "markets": ["土耳其"],
    "note": "BIST影响榜前列……",
    "homepage": "https://x.com/altinhisseler",
    "tier": "core",
    "priority": "high"
  }
}
```

- `x_profiles()` 容错读取缓存；文件缺失、空文件、JSON 损坏或 schema 不支持时返回 `{}`，而不是 500。只下发 `bio/followers/verified/location/enriched_at`，不把 provider 原始输出透给浏览器。

#### `workbench/server/app.py`

在 `/wb-api/v1/{path:path}` 之后、stats 之前增加两个显式 GET 路由：

```python
@app.get("/wb-api/x-accounts")
def x_accounts():
    return views.x_accounts()

@app.get("/wb-api/x-profiles")
def x_profiles():
    return views.x_profiles()
```

两者运行期只读文件、不访问外网、不启动任何 CLI。池基础文件缺失属于部署错误：`x-accounts` 返回可诊断的 500 JSON；local 错误则降级 base。`x-profiles` 缺失是正常状态，返回 200 `{}`。

#### `workbench/server/proxy.py`

不改。两个端点是工作台本地只读视图，不应代理到 8787；继续保证前端只访问同源 `/wb-api/*`。

#### `workbench/server/stats.py`

保留现有 `top_sources`，另聚合 X 账号 top10：

```python
per_x_account = Counter(
    norm(i.get("author_handle")) for i in items
    if i.get("source_id") in {"twitter_kol_flash", "twitter_kol_views"}
       and i.get("author_handle")
)
data["x_accounts"] = [[handle, count] for handle, count in per_x_account.most_common(10)]
```

这里只返回稳定 handle 和 count；显示名由前端已有 `xAccounts` join，避免 stats 重复解析 YAML。聚合使用现有最多 4000 条/60 秒缓存窗口，响应应继续携带 `truncated`，UI 在截断时不暗示它是全库绝对排名。

#### `workbench/server/x_profile_enricher.py`（新增）

新增与 FastAPI 运行期解耦的增强模块，负责：读取合并后账号、分批、构造 prompt、`subprocess.run(argv, shell=False)` 调外部 CLI、解析/校验、合并旧缓存、原子写入 `data/workbench/x_profiles.json`。模块不被 app 路由调用，只由 CLI 命令调用。

#### `cli.py`

遵守项目统一驱动契约，在现有 `workbench_cmd()`（`cli.py:293-325`）增加 `enrich-x-profiles` 分支，并在 `cli.py:523-531` 的 workbench 子命令区增加参数：

```text
python cli.py workbench enrich-x-profiles \
  --provider cursor-grok|grok-cli \
  [--batch-size 12] [--handles a,b] [--force] [--dry-run]
```

- `--dry-run` 只打印批次、prompt 大小、目标缓存路径，不调用外部 CLI、不写文件。
- 默认跳过已有且未过期的记录；`--force` 重查；`--handles` 用于先对 1～2 个账号冒烟。
- 返回码：0 全部成功；2 CLI 未登录/需人工认证；3 有批次经重试仍失败；4 CLI/PyYAML/池文件缺失。部分成功时保留成功结果并在终端列出失败 handle。

不推荐仅放一个可直接运行的 `scripts/enrich_x_profiles.py`：虽然实现快，但会绕开 `python cli.py <板块> <命令>` 的项目契约，也更容易让 FastAPI 端点误用它。若需要脚本文件，只能作为无逻辑薄包装，正式入口仍是上述 CLI。

### 3.2 前端文件

#### `workbench/web/js/pages/news.js`

1. data 新增 `xAccounts: {}`、`xProfiles: {}`、`bodyExpanded: {}`。保留原 `expanded: {}` 专用于 `text_src`，不改 `expanded[it.id]` 现有行为。
2. 新增 `loadXMeta()`，用 `Promise.allSettled` 独立请求 `/x-accounts` 和 `/x-profiles`。账号注册表失败时 X 卡仍用条目字段降级；增强缓存失败/缺失不得让页面报错。mounted 在原 `loadDict/loadStats/load` 旁调用它。
3. 新增纯函数：

```javascript
normHandle(v)              // String(v||'').trim().replace(/^@/, '').toLowerCase()
accountInfo(it)            // xAccounts[normHandle(it.author_handle)] || null
profileInfo(it)            // xProfiles[normHandle(it.author_handle)] || null
accountName(it)
accountRole(it)
accountBrief(it)
accountMarkets(it)
accountHomepage(it)
formatFollowers(n)
itemBody(it)
isLongBody(it)             // 约 300 字或显式换行超过 6 行
```

4. 左框用 `v-if="it.author_handle"` 走 X 专用模板；无 `author_handle` 的 `v-else` 原样保留现有 `sourceTitle/sourceInfo.markets/sourceInfo.brief/positioning` 展示。X 模板只渲染一组账号级 markets，绝不再访问池源 `sourceInfo(...).markets`。
5. X 模板结构固定为“显示名（可链接 homepage）→ `@handle + role`（可选 verified）→ 简介 → markets → 可选 followers/location”。不再另放池级标题，也不在第二处重复 handle。
6. 右框把正文改成 `.nc-content-text`；当 `isLongBody(it)` 且未展开时加 `.is-collapsed`，操作区新增“展开全文/收起”。正文状态使用 `bodyExpanded[it.id]`，译前原文继续使用 `expanded[it.id]`，两个按钮可独立组合。
7. 新增右栏“X账号产量”卡，读取 `stats.x_accounts`；点击 `pickXAccount(handle)` 时设置 `f.sources=["twitter_kol_flash","twitter_kol_views"]`、`f.q="@"+handle`、`f.since=""` 后 reload。不能把 handle 塞给 `sources` 参数。
8. 来源详情子页顶部增加一个轻量摘要条，显示“X 池账号 131”，按钮“查看 X 信息流”复用上述两源过滤；不把 131 个账号混入 `regRows`。

#### `workbench/web/js/pages/article.js`

- 同步新增 `xAccounts/xProfiles/bodyExpanded`、`loadXMeta()` 与账号字段 helper；可抽到共享 JS 的工作量大于收益，本轮允许两页各保留一组短纯函数，但字段优先级必须一致。
- `article.js:295-304` 的简化左框同样改成 X/非 X 两分支；X 分支按账号显示，非 X 分支保持 `it.source + positioning + markets`。
- `article.js:321` 正文使用与资讯页相同的 clamp 类和独立“展开全文/收起”按钮；价值分与“加入生成”行为不动。
- mounted 并行加载元数据；任何元数据端点失败都不阻断 `/recommend`。

#### `workbench/web/css/app.css`

在 `app.css:194-207` 的 `.nc-*` 区块附近新增 `.nc-account-line`、`.nc-account-role`、`.nc-account-extra`、`.nc-content-text`、`.nc-content-text.is-collapsed`、`.nc-content-fade`、`.nc-expand-action` 等 kebab 类。颜色全部引用现有 oklch token；不引入新的视觉体系，不改 `.nc-grid` 和响应式纵堆。

#### `workbench/web/index.html`

实施完成并验证后，将 `index.html:7,51-57` 的所有 `0903b` 统一改为 `0903c`，避免浏览器混用新 JS 与旧 CSS。

## 4. 左框字段优先级表

`author_handle` 是否非空是唯一分支条件。无 handle 就完整走现有非 X 源级模板；不能用 `source.startsWith("X·")` 猜测，以免误伤历史/异常数据。

| 最终字段 | 首选来源 | 兜底链 | 为空时行为 |
|---|---|---|---|
| 显示名 | `x_accounts[handle].name` | 条目 `source` 去掉首个 `X·` → 原样 `@author_handle` → `sourceTitle(source_id)` | 至少显示 handle/source_id，不留空标题 |
| handle | 条目 `author_handle`（显示时补一个 `@`，先去掉已有 `@`） | `x_accounts` 对象内 handle（若 API 后续保留） | 无 handle 即走非 X 模板 |
| role 徽章 | 条目 `author_role` | pool `role` | 不渲染徽章；不写“未知” |
| 账号简介 | pool `note` | Grok cache `bio` | 整段不渲染；不回退池源 brief |
| markets | 条目非空 `markets` | pool `markets` | 不渲染市场徽章；绝不回退 `sourceInfo(source_id).markets` |
| homepage | pool `homepage` | `https://x.com/<handle>` | 没 handle 时不加链接；链接 `target=_blank rel=noopener` |
| followers | Grok cache `followers`（非负整数） | 无 | 不渲染；格式化为本地化 `1.2万/35.6万/120万` 或 `Intl.NumberFormat('zh-CN', {notation:'compact'})`，title 保留精确数值 |
| verified | Grok cache `verified`（true/false/null） | 无 | 仅 true 显示中性“已认证”小徽章；false/null 不显示，避免把“未查到”误判为未认证 |
| location | Grok cache `location` | 无 | 有值时作为次级文字或账号行 title；默认不占独立徽章，防止左框过密 |
| positioning | 非 X 条目继续用 `it.positioning` | 无 | X 专用左框不重复展示；右框/筛选语义保持不变 |

明确去重规则：X 左框只出现一次 handle、一次 role、一次 markets；`pool.note` 与 `grok.bio` 是择一关系而非上下堆叠；池级 title/brief/markets 均不进入 X 左框。

## 5. 长文截断方案

### 5.1 JS 状态与判定

- `itemBody(it)` 统一拼出页面当前展示的 `title + " — " + text`，避免长度判定和模板文本不一致。
- `isLongBody(it)` 使用近似规则：去除首尾空白后字符数 `> 300`，或按 `\r?\n` 分割后的非尾随行数 `> 6`。这是“约 300 字或 6 行”的稳定无 DOM 判定；验收夹具覆盖中文、英文、带换行文本。
- 资讯页用 `bodyExpanded[it.id]`；推荐页同名独立字典。Vue 3 对动态对象 key 可响应，无需 `$set`。
- 仅 `isLongBody(it)` 为 true 时显示按钮和 collapsed 类；短文本不出现无意义按钮。

### 5.2 CSS

建议结构：

```html
<div class="nc-content-wrap" :class="{'is-collapsed': isLongBody(it) && !bodyExpanded[it.id]}">
  <div class="nc-content-text">{{ itemBody(it) }}</div>
  <span class="nc-content-fade" aria-hidden="true"></span>
</div>
```

样式伪代码：

```css
.nc-content-text {
  font-size: 13.5px;
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.nc-content-wrap.is-collapsed .nc-content-text {
  overflow: hidden;
  max-height: calc(1.65em * 6); /* 非 WebKit/失效时的高度兜底 */
}
@supports (-webkit-line-clamp: 6) {
  .nc-content-wrap.is-collapsed .nc-content-text {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 6;
    max-height: none;
  }
}
.nc-content-wrap.is-collapsed .nc-content-fade {
  /* 底部轻渐变使用 var(--bg-card)/transparent；pointer-events:none */
}
```

兼容注意：`-webkit-line-clamp` 单独写无效，必须同时有 `display:-webkit-box` 与 `-webkit-box-orient:vertical`。`white-space: pre-wrap` 可以保留用户换行，但其与匿名 flex/box 布局在不同 Chromium/WebKit 版本的断行高度存在差异，因此 `max-height: calc(line-height × 6)` 必须作为基础 fallback，再用 `@supports` 覆盖；渐变放在外层 wrapper 的绝对定位元素/伪元素上，不要放进文本 box，以免被 clamp 一起裁掉。展开态移除 clamp、max-height 和渐变。按钮应是可键盘聚焦的 `<button type="button">` 或现有视觉兼容的 action button，并设置 `aria-expanded`。

现有 `.news-text` 可保留给其他页面；本轮两处卡片改用新 `.nc-content-text`，避免全局给所有 `.news-text` 强制截断。`text_src` 的 `.news-src-text` 不受正文折叠影响。

## 6. 增强脚本设计

### 6.1 边界与批处理

- 手动运行，不挂到 FastAPI 启动、GET 端点、sources refresh 或页面刷新。
- 默认批大小 12，允许 10～15；131 个基础账号约 11 批。批次串行执行，避免搜索配额/限流；单批失败后退避一次，再拆为 5～6 个重试。仍失败则记录本批失败、继续后续批次。
- 输入 handle 来自第 2 节合并后的 enabled 账号；统一去 `@`、小写去重，但 prompt 同时提供 pool 的显示名/homepage，减少同名误匹配。
- 只要求可公开核验资料；不能猜测。粉丝数是时点值，允许近似但必须输出整数和查询时间。找不到时输出 null。
- 旧缓存按 handle 合并：本次成功覆盖该 handle；失败不删除旧记录；已不在池中的记录移入顶层 `orphaned` 或保留但端点不下发，推荐前者便于审计。
- 写入采用同目录临时文件 + `Path.replace()` 原子替换，目标只能是 `data/workbench/x_profiles.json`。

### 6.2 Prompt 模板

每批把 `ACCOUNTS_JSON` 替换为 10～15 个最小对象：

```text
你是 X/Twitter 公开账号资料核验器。请使用可用的 X Search/x-search 与网页搜索，逐一核验下面账号的当前公开资料。

输入账号：
ACCOUNTS_JSON

要求：
1. 每个输入 handle 恰好返回一条；handle 必须原样返回（不带 @），不得遗漏、增删或改名。
2. bio 为账号当前公开简介的简洁转述，最多 240 字；不要编造，不要把近期推文当 bio。
3. followers 为查询时可见的粉丝数整数；只能确认数量级时仍给最接近的整数，并在 bio 中不要解释。无法可靠确认填 null。
4. verified 为当前是否显示 X 认证标记：true/false；无法查看填 null。不要推断认证类型。
5. location 为主页公开 location 字段；空白或无法确认填 null。
6. 只输出 JSON 数组，不要 Markdown 围栏、说明、来源列表或前后缀。

严格 schema：
[
  {
    "handle": "string",
    "bio": "string|null",
    "followers": 0,
    "verified": true,
    "location": "string|null"
  }
]
```

实际校验 schema 允许 `bio/followers/verified/location` 为 null；followers 必须为 `integer >= 0`，verified 必须为 boolean/null，禁止字符串 `"yes"`。模型返回的简介可保留原语言；前端以 pool 中文 note 优先，所以不会挤掉已有人工录入说明。

### 6.3 缓存格式

```json
{
  "schema_version": 1,
  "generated_at": "2026-09-03T18:30:00+08:00",
  "provider": "grok-cli",
  "profiles": {
    "tuncaytursucu": {
      "bio": "……",
      "followers": 120000,
      "verified": true,
      "location": "İstanbul, Türkiye",
      "enriched_at": "2026-09-03T18:29:12+08:00"
    }
  },
  "errors": [
    {"handles": ["example"], "error": "invalid_json"}
  ]
}
```

每条必须有自己的 `enriched_at`，不能只依赖文件级 `generated_at`。API 只返回 `profiles` 中仍在账号池里的白名单字段。

### 6.4 两种 Grok 调用形态

#### A. Cursor Agent 调 Cursor 的 Grok 模型（内置 x-search）

执行前先认证并确认当前账号实际暴露的模型 id：

```powershell
cursor-agent.cmd status
cursor-agent.cmd --list-models | Select-String -Pattern "grok"
```

当前机器审计时 `cursor-agent --list-models` 返回“Authentication required”，因此实施实测必须先完成 `cursor-agent login`；不要在代码中硬编码凭据。若列表显示的 id 为 `grok-4`，单批完整调用形态为：

```powershell
cursor-agent.cmd -p --model grok-4 --mode ask --output-format text --workspace "E:\ai-gen-article-publish" "<将上方 Prompt 模板中的 ACCOUNTS_JSON 替换为本批 JSON>"
```

脚本中对应 `subprocess.run(["cursor-agent.cmd", "-p", "--model", model_id, "--mode", "ask", "--output-format", "text", "--workspace", str(repo), prompt], capture_output=True, text=True, timeout=...)`。不要加 `--force/--yolo`；本任务只需搜索和返回文本。模型 id 必须以 `--list-models` 实测结果为准，若不是 `grok-4`，由 `--model` 参数覆盖，不在脚本里猜别名。

#### B. xAI Grok Build CLI（内置 web search/x-search）

本机 `grok --help` 已确认支持 `--single/-p`、`--model`、`--output-format`、`--json-schema`、`--permission-mode`、`--no-subagents`、`--max-turns`。单批完整调用形态为：

```powershell
grok.exe --single "<将上方 Prompt 模板中的 ACCOUNTS_JSON 替换为本批 JSON>" --model grok-4 --output-format plain --permission-mode plan --no-subagents --max-turns 1 --cwd "E:\ai-gen-article-publish"
```

脚本的优先实现再加 `--json-schema <压缩后的 schema JSON>`，利用 CLI 原生结构化输出；若该模式在实测中使 x-search 不可用，则退回上述 plain + 本地严格解析。禁止 `--always-approve`。同样通过参数允许覆盖模型 id。

### 6.5 非纯 JSON 的提取与容错

解析器按以下顺序工作，每一步都保留原 stdout 的截断摘要到终端诊断，但不把原始长响应写进缓存：

1. 去 UTF-8 BOM、ANSI 控制序列和首尾空白。
2. 先 `json.loads(stdout)`；若 CLI 的 `--output-format json` 返回外层事件/消息 envelope，递归查找第一个“可解析成目标数组”的字符串字段或数组字段。
3. 剥离 Markdown 围栏：用 `(?s)\x60{3}(?:json)?\s*(.*?)\s*\x60{3}` 匹配开闭各三个反引号的 JSON 代码围栏，对每个捕获内容尝试解析。
4. 用字符串感知的括号平衡扫描提取第一个完整 `[...]`；不能简单 `find('[')/rfind(']')`，因为 bio 可能含括号。
5. 轻量修复只允许去掉对象/数组闭合前的 trailing comma：`,\s*([}\]]) -> \1`，修复后再次解析；不得用单引号全局替换双引号，避免破坏人名/bio。
6. 最后尝试 NDJSON：逐行去可选逗号、逐个解析 `{...}`，合成数组。仍失败则判本批失败并按更小批次重试，不用正则直接“抠字段”制造半可信数据。
7. 解析成功后做 schema 与输入集合校验：handle 规范化后必须与本批一一对应；重复、额外、遗漏、followers 非整数、verified 非 bool/null 均作为该记录错误。允许逐条收下合格记录，但失败 handle 必须进入重试/错误清单。

### 6.6 降级策略

- `x_profiles.json` 不存在/损坏：`GET /wb-api/x-profiles` 返回 `{}`；两页仍凭条目 + `x-accounts` 展示 name/handle/role/note/markets。
- `/x-accounts` 暂时失败：X 卡用 `it.source` 去掉 `X·`、`it.author_handle`、`it.author_role`、`it.markets` 渲染；只是没有 pool note/homepage/tier，不影响正文。
- 两个端点都失败：仍按条目字段展示，不回退到池级六市场；只有真正无 `author_handle` 的非 X 条目才走原源级模板。
- Grok 数据陈旧：仍可显示，但 followers 的 title/次级文字可带 `enriched_at`；建议默认 30 天过期，由手动 CLI 更新，不在请求时刷新。

## 7. 评估结论

### 7.1 右栏“产量最高的源”是否拆账号级 top

**结论：做，但不拆掉/替换现有源榜；新增独立“X账号产量 Top 10”。**

理由：源榜用于观察 110 个物理源健康与产量，改成账号口径会破坏跨源比较；但 X 池占用两个物理源，完全看不到 131 个账号分布，又与本次目标冲突。`stats.py` 已经把最多 4000 条加载在内存里，按 `author_handle` 多做一个 Counter 成本很低。点击反查应同时设两个 X 源 id，并使用 `q=@handle`：抓取器在 `basic.py:440` 确保原始 text 有 `@handle:`，数据站 q 又会查原始 text（`store.py:482-484`）；不能把 handle 当 `sources` 参数。前端只过滤当前已加载 100 条会漏项，所以不采用纯前端过滤。

### 7.2 来源详情注册表是否加入 131 个账号

**结论：不把 131 账号注册成来源行；做一个轻量“X 池账号 131”摘要入口。**

理由：这 131 个账号不是 sources registry 的独立物理源，没有各自 ttl/health/本轮耗时，硬塞进 110 源表会制造伪字段并破坏排序。第一阶段只在来源详情顶部显示合并后 enabled 数量、两个池源说明及“查看 X 信息流”按钮；账号身份已经在每条卡片和 X Top10 可见。暂不做 131 行折叠明细/新子页，避免为一个展示修复扩张信息架构。以后若出现账号启停/健康管理需求，再以独立“账号池”子页立项。

### 7.3 `article.js` 推荐信息是否同步

**结论：做，与资讯页同批交付。**

理由：推荐接口返回同一条目模型，若只修资讯页，用户把素材流转到“推荐信息”后又会看到池/账号信息不一致；共享两个 GET 端点和 CSS 后，额外改动小。推荐页保留简化密度，但字段优先级、去重和正文展开行为必须一致。

## 8. 验证步骤

### 8.1 后端/API

1. 启动工作台：`python cli.py workbench serve --port 8788`；请求 `/wb-api/x-accounts`，确认 HTTP 200、顶层为 handle 字典、基础池当前返回 131 个 enabled 账号，key 全部小写无 `@`，每项仅含白名单字段。
2. 临时使用测试 fixture（不要改真实池）覆盖以下合并单测：local 新增账号；同 handle 不同大小写整条替换；local 条目缺 note 时不会继承基础 note；defaults/filters 浅覆盖；disabled/空 handle 被过滤；坏 local 降级基础池。测试结束不产生仓库外写入。
3. 确认 GET 两端点前后 `global-news-sources/config/twitter_pool*.yaml` 的 hash/mtime 不变，且服务器没有调用 Grok/Cursor 子进程。
4. 删除或改名缓存的验证必须针对测试临时路径/fixture；真实运行可先将现有缓存复制到 `E:\tmp` 后再验证。缓存缺失时 `/wb-api/x-profiles` 应返回 200 `{}`，不是 404/500。

### 8.2 Grok 增强脚本：Cursor-Grok 路径

1. `cursor-agent.cmd status`；未登录则人工执行 `cursor-agent.cmd login`。运行 `cursor-agent.cmd --list-models | Select-String grok`，把实际模型 id 传给命令。
2. 先执行：`python cli.py workbench enrich-x-profiles --provider cursor-grok --handles altinhisseler,TuncayTursucu --batch-size 2 --dry-run`，确认不写缓存。
3. 去掉 `--dry-run` 实跑；确认 stdout 即便带说明或 Markdown JSON 围栏，也能由提取器得到两条，handle 一一对应，followers 是整数/null、verified 是 bool/null，每条有 `enriched_at`。
4. 用 parser 单测分别喂入：纯数组、Markdown fence、前后说明、JSON envelope、trailing comma、NDJSON、截断 JSON、额外 handle、遗漏 handle。前五种应按规则成功；截断/集合不一致必须失败并触发小批重试，不能静默写脏数据。

### 8.3 Grok 增强脚本：Grok CLI 路径

1. `grok.exe --help` 确认命令可用并完成其登录状态检查；先用 2 个 handle 跑 `--provider grok-cli --dry-run`。
2. 实跑：`python cli.py workbench enrich-x-profiles --provider grok-cli --handles altinhisseler,TuncayTursucu --batch-size 2`。
3. 分别实测 `--json-schema` 结构化输出和 plain fallback；确认开启结构化约束时 web/x-search 仍可用。若不可用，保留 plain + 本地 schema 校验路径，并在 CLI 输出明确说明采用的路径。
4. 比较两路径对同一账号的 handle、数量类型和非空字段，不要求文字完全一致；抽查 X 主页验证 bio/followers/verified/location 没有串号。131 账号全量前先将批大小固定在 12，观察限流后再决定是否调整。
5. 全量完成后校验：profiles key 是池账号子集；无重复；所有成功项有 ISO 8601 `enriched_at`；失败项列在 errors；再次无 `--force` 运行应幂等跳过未过期项。

### 8.4 前端展示与降级

1. 选取 flash/views 各至少 3 个账号，确认左框显示各自 name、唯一 `@handle`、role、pool note、账号级 markets；不再出现池级长标题和六市场全景。
2. 验证字段兜底：手工 fixture 依次缺 name/note/markets/role/profile，严格符合第 4 节；note 存在时不同时显示 Grok bio。
3. 缓存缺失降级：让测试环境的 `x_profiles` 路径指向不存在文件，硬刷新资讯页和推荐页；只凭录入信息仍可完整渲染，控制台无未处理异常。再让 `/x-accounts` 返回失败，确认条目自带 `source/author_handle/author_role/markets` 仍能渲染且不出现池级 markets。
4. 非 X 回归：抽查普通新闻/机构/官方源，源名、positioning、源级 markets、brief 与改动前一致。
5. 长文：准备 299/300/301 字、6/7 个显式行、英文长单词、含 emoji/URL、同时有 `text_src` 的用例；确认临界值、六行 clamp、渐变、展开/收起和译前原文按钮互不干扰。窄于 1100px 时双框仍纵堆，展开正文无跳层/横向溢出。
6. 键盘/可访问性：Tab 可聚焦展开按钮，Enter/Space 切换，`aria-expanded` 正确，链接均有 `rel=noopener`。
7. X Top10：确认仍保留“产量最高的源”和“定位分布”；点击账号后请求参数包含两个 X source id 与 URL 编码后的 `q=@handle`，不是 `sources=<handle>`，结果不只限前端已加载的 100 条。
8. 来源详情：仍显示 110 个源的原注册表语义；仅多一条 X 池摘要，不出现 131 个伪 source 行。

### 8.5 不回退项与发布前检查

- `news.js`、`article.js` 的 `registerSubs()` 路由守卫仍在，跨页迟到回调不能覆盖当前子导航。
- `.nc-grid` 双框结构、1100px 响应式纵堆仍在。
- 条目赛道 L1/L2 分层徽章和 `+n` 收口仍在。
- 资讯筛选区五组（市场/定位/类型/赛道/情绪）仍在且行为不变。
- 右栏“定位分布”卡仍在；原市场/类型/源/标的统计不回退。
- `proxy.py` 仍只 GET；工作台没有写 global-news-sources、run.json、state.json 等前三板块文件。
- 唯一新增运行时写入是手动 CLI 原子写 `data/workbench/x_profiles.json`；FastAPI GET 不写缓存。
- 浏览器无 JS 错误后，统一把 `index.html` 全部资源版本由 `0903b` bump 到 `0903c`，再做一次无缓存硬刷新验证。

建议实施顺序：先完成只读 pool loader 与两个 API → 两页账号 join/降级 → 正文 clamp → stats X Top10 与来源详情摘要 → 手动增强 CLI → 全量验证与 `0903c` bump。每一步都可独立验证，缓存增强不是账号展示上线的前置条件。
