# 图文页四子页面规划方案

## 0. 现状摸底结论

结论先行：保留顶层 `#/article`，用工作台现成的左侧子菜单机制将旧三栏页拆为「推荐信息 / 内容生成 / 内容发布 / 自动化任务」四个子页面。四页共享同一条业务主线：推荐条目进入素材选择，素材与生成配置形成工作台草稿，草稿形成发布计划，成熟的配置再固化为自动化任务。本轮只产出方案文档，不修改任何业务代码。

| 核对项 | 源码确认结果 | 对本方案的约束 |
|---|---|---|
| 子页面机制 | `workbench/web/js/pages/news.js` 在 `mounted()` 调 `WB.shell.setSubs(...)`，切页用 `onPick`，离开页面在 `unmounted()` 清空；壳层另有 `WB.shell.setSub(id)` | `article.js` 后续应沿用同一生命周期注册四个子页，不另造页签组件 |
| 旧图文页 | `workbench/web/js/pages/article.js` 仍是「素材篮 / 工作流与运行 / 产物与队列」三栏草版，未注册子页面；生成、推入队列、发布均为 disabled 桩 | 旧能力拆入四页，不在旧三栏上继续叠功能 |
| 路由现状 | `workbench/web/js/app.js` 只识别完整 hash `#/article`，子页状态目前只存在壳层内存 | 实施时扩展工作台壳的 hash-query 解析；规范地址为 `#/article?sub=<id>` |
| 资讯底座 | `/wb-api/v1/{path}` 代理数据站；`/wb-api/v1/items` 有资讯条目、时间与标签，`/wb-api/v1/sources` 提供来源字典；`/wb-api/stats` 聚合来源、市场、类型、标的和健康统计 | 推荐页不复制资讯库，只读取、筛选和排序 |
| 推荐现状 | `GET /wb-api/recommend` 已存在，支持 `since/markets/kinds/channels/limit`；按同事件热度、机构源、重大事件、情绪方向、标的数透明打分，返回 `score`、`score_parts`、`rule` | 价值排序已有 V1 基础；来源、更多标签、排序维度需扩展现有端点，不另建重复端点 |
| 工作流视图 | `GET /wb-api/flows` 扫描工作流 YAML；`GET /wb-api/runs` 读取 `data/runs/*/*/run.json`；`GET /wb-api/artifacts` 与 `/artifacts/file` 提供生成产物及待发队列只读镜像 | 历史与产物可立即展示；真正执行只能由工作台后端 subprocess 调 `python cli.py ...` |
| 草稿现状 | `GET/POST/DELETE /wb-api/drafts` 已存在，写 `data/workbench/drafts.json`；字段已有标题、正文、素材、模块、模板与时间 | 继续复用并扩展草稿模型，不把草稿写入前三板块目录 |
| 发布现状 | `GET /wb-api/ledger` 只读 `auto-publisher/autopub/state.json`；`/artifacts` 响应中的 `queue` 只读 `auto-publisher/autopub/articles/` | 发布页可展示队列和记录，但绝不手编账本，也不由工作台写待发队列 |
| 自动化现状 | `GET/POST/DELETE /wb-api/automation` 已存在，写 `data/workbench/automation.json`；调度执行仍为桩 | 先完成任务配置闭环，再接调度器；自动任务不能绕过发布确认闸口 |
| 设计系统 | `app.css` 明定禁 emoji、单 accent、4pt 间距阶梯、数字 `tabular-nums`，并采用 1px 分隔的数据列表 | 四页只复用既有 token；图标使用单色 SVG，时间、分数、计数、状态码使用等宽数字 |
| 总契约 | `AGENTS.md` 要求物理动作一律 subprocess 调 `python cli.py`；工作台对前三板块只读；发布先 `--draft`，真发须用户确认 | 新能力只改工作台层；XAI、Bit 仅留桩；任何执行不得直接 import 内部模块 |

现有 API 的统一前缀以源码为准是 `/wb-api`。下文把当前已可调用的能力标为【现有】，仅在工作台层规划但尚未实现的能力标为【需新增】，对当前端点加参数或字段标为【需扩展】。

---

## 1. 四个子页面逐一规划

### 1.1 推荐信息（`sub=recommend`）

#### 页面目的

从选定来源和回溯时间范围内筛出候选信息，按「综合价值 / 重要性 / 最新」排序，并以标签继续收窄。页面回答两个问题：最近哪些信息值得写，为什么值得写。选中的条目可一次性带入内容生成页。

#### 布局区块

```text
+----------------------------------------------------------------------------------+
| 推荐信息                          已选 3 条              [带入内容生成]             |
+----------------------+-----------------------------------------+-----------------+
| 筛选器               | 推荐信息流                              | 选择篮          |
| 回溯: 1h/4h/24h/3d   | 排序: 综合价值 | 重要性 | 最新          | [1] 条目标题     |
| 来源: 多选            |-----------------------------------------| [2] 条目标题     |
| 市场/类型/渠道        | 86.5  标题与摘要                        | [3] 条目标题     |
| 情绪/事件/标的        | 时间 来源 标签                         |                 |
| [清空] [应用]         | 推荐原因: 同事件热度 + 机构源 + ...     | [清空] [带入]   |
|                      | [查看原文] [加入选择]                   |                 |
+----------------------+-----------------------------------------+-----------------+
```

#### 数据来源

| 区块 | 数据来源 | 状态与说明 |
|---|---|---|
| 来源、市场、类型、渠道字典 | `GET /wb-api/v1/sources`，辅以 `GET /wb-api/stats` | 【现有】来源注册表和聚合统计 |
| 推荐信息流、综合价值 | `GET /wb-api/recommend` | 【现有】透明规则分数；【需扩展】增加 `sources/info_types/event_types/sentiments/tickers/sort/cursor`，并把 `value_score`、`importance_score` 分列返回 |
| 条目详情与翻页兜底 | `GET /wb-api/v1/items?...` | 【现有】按时间与标签查询真实条目 |
| 当前选择篮 | 页面内存 + `localStorage` 的现有 `WB.basket` | 【现有】同浏览器持久；带入草稿后由服务端草稿保存兜底 |
| 带入内容生成 | `POST /wb-api/drafts` | 【现有】新建或更新草稿的 `items`；【需扩展】保存完整的 `selection_snapshot` |

推荐排序定义应保持可解释：`综合价值` 默认沿用当前 `score`，`重要性` 单独聚合事件级别、来源权威度和同事件覆盖数，`最新` 按条目时间倒序。UI 必须展示分数组成，不把模型黑盒分数伪装为客观事实。

#### 交互流

1. 进入页面，默认回溯 24 小时，加载来源字典与综合价值 Top 50。
2. 用户多选来源及标签，切换回溯范围；点击「应用」更新 URL query 并重新请求。
3. 用户切换排序，展开「推荐原因」，检查原文或加入选择篮；重复条目按 `id` 去重。
4. 点击「带入内容生成」：若无草稿则由现有草稿端点创建草稿，若 URL 已有 `draft_id` 则合并到该草稿；随后跳转 `#/article?sub=generate&draft_id=<id>`。
5. 数据站不可达时保留筛选条件，展示连接错误与重试，不把空结果误报为「没有重要信息」。

#### 本期留桩点

- 个性化推荐、用户反馈学习、LLM 重排、跨用户协同不实现。
- `价值` 与 `重要性` 的 V2 权重配置先固定为服务端规则，页面只展示解释，不提供自由调权。
- 事件关系图、相似事件合并编辑、自动事实核验不实现。
- 来源、标签、时间筛选做实；自定义关注主题和保存筛选方案先留入口。

### 1.2 内容生成（`sub=generate`）

#### 页面目的

把素材、生成模块、编排方式和固定模板放进一个可实时编辑的工作区，同时提供历史运行记录和工作台草稿。页面必须忠实呈现用户公式：

```text
实时编辑
= 信息选择
+ 生成模块（信息检索 / 快照抓取 / 技术分析 / 聚合分析）
+ 排列组合
+ 固定模板
```

这里的「实时编辑」是状态实时可见、可保存、可重排，不等同于每次按键都调用 LLM。昂贵或有副作用的生成必须显式点击运行。

#### 布局区块

```text
+----------------------------------------------------------------------------------+
| 内容生成     草稿: AI 芯片复盘      已保存 14:32       [保存] [送至内容发布]       |
+-------------------+--------------------------------------------+-----------------+
| 历史与草稿        | 实时编辑画布                               | 生成配置        |
| [草稿] [运行历史] | 1 信息选择       6 条 [增删/排序]           | 工作流 YAML     |
| 草稿 A            | 2 生成模块                                 | 固定模板        |
| 草稿 B            |   [信息检索] [快照抓取]                    | 标题/语气/长度  |
|-------------------|   [技术分析] [聚合分析]                    |                 |
| morning-paper     | 3 排列组合                                 | [预检]          |
| 2026-09-03 done   |   素材 -> 快照 -> 聚合 -> 技术 -> 成文      | [开始生成(桩)]  |
| 2026-09-02 waiting| 4 正文编辑 / 预览                          |                 |
|                   |   Markdown 编辑区                          |                 |
+-------------------+--------------------------------------------+-----------------+
```

#### 数据来源

| 区块 | 数据来源 | 状态与说明 |
|---|---|---|
| 草稿列表与编辑内容 | `GET/POST/DELETE /wb-api/drafts` | 【现有】写 `data/workbench/drafts.json`；【需扩展】增加 `status/arrangement/workflow/selection_snapshot/version` |
| 信息选择 | 草稿 `items`；也可从 `GET /wb-api/v1/items` 补选 | 【现有】不复制资讯全文，只保存必要快照和源条目 ID |
| 工作流与固定模板 | `GET /wb-api/flows` | 【现有】只读 YAML 元数据；模板选择值保存进草稿 |
| 历史记录 | `GET /wb-api/runs` | 【现有】只读 `run.json` 状态机，包括 `done/waiting_review/stopped` 与步骤、产物 |
| 生成产物 | `GET /wb-api/artifacts`、`GET /wb-api/artifacts/file?path=...` | 【现有】只读预览，不改产物文件 |
| 生成任务 | `POST /wb-api/generation/jobs`、`GET /wb-api/generation/jobs/{job_id}` | 【需新增】工作台任务镜像落 `data/workbench/generation-jobs.json`；可接入时仅 subprocess 调 `python cli.py flows run ...` |

`arrangement` 建议保存为有序节点数组，而非自由文本，例如 `[{id:"retrieve", enabled:true, order:1}, ...]`。四个生成模块是可启停节点；固定模板是最终约束，不与工作流 YAML 内容混写。

#### 交互流

1. 从推荐页带入时按 `draft_id` 打开草稿并定位信息选择；直接进入则打开最近草稿或新建空草稿。
2. 用户增删、拖排素材，启停四个模块，调整模块顺序，选择工作流与固定模板。
3. 正文区允许直接编辑；失焦或 30 秒自动保存一次，显式「保存」立即写入草稿，并使用 `version` 防止覆盖冲突。
4. 点击「预检」只校验素材、模块依赖、模板和工作流可用性，不调用 LLM。
5. 点击「开始生成」在后续阶段创建生成任务；退出码 `0` 显示完成，`2` 显示待人工审核并链接产物，`3/4` 显示业务失败或配置缺失。若现有 CLI 无法消费工作台素材包，该按钮继续保持桩，不要求修改 `ai-workflow`。
6. 用户可从运行历史导入某个产物到正文，但导入后只修改工作台草稿。
7. 点击「送至内容发布」先保存草稿，将状态标为 `ready_for_publish`，再跳转 `#/article?sub=publish&draft_id=<id>`。

#### 本期留桩点

- 四个生成模块先做选择、排序、参数表单和依赖校验；模块级真实执行按现有 CLI 可消费能力逐步启用。
- 拖拽编排可先降级为「上移 / 下移」，节点分支、条件判断和可视化 DAG 留桩。
- Markdown 实时预览、协同编辑、版本对比、自动保存恢复先预留数据字段。
- 固定模板本期只选择既有 flow/template 标识，不做在线 YAML 编辑器。
- 生成按钮必须在工作台 subprocess 适配完成后开放，禁止前端直调内部 Python 模块。

### 1.3 内容发布（`sub=publish`）

#### 页面目的

统一浏览工作台草稿、既有待发队列与发布记录。点击稿件可回到内容生成页继续编辑；确认内容后，在下方形成发布计划，选择发布时间、发布账号和发布方式。XAI 与 Bit 浏览器本期只保留选择器和说明，不实现发布通道。

#### 布局区块

```text
+----------------------------------------------------------------------------------+
| 内容发布             [草稿 12] [待发队列 3] [发布记录 86]                       |
+----------------------+-----------------------------------------------------------+
| 稿件/记录列表        | 稿件详情                                                   |
| 状态 来源 更新时间   | 标题、摘要、素材、正文预览                                 |
| 草稿 A               | [返回内容生成继续编辑] [确认内容并创建发布计划]             |
| queue-file.md        |-----------------------------------------------------------|
| 已发布 / 失败 / 未确认| 发布设置                                                   |
|                      | 发布时间 [立即/预约]  账号 [请选择]                        |
|                      | 发布方式 [XAI(桩)] [Bit浏览器(桩)]                         |
|                      | [保存发布计划]                                             |
|                      | 闸口 1: [--draft 验证] -> 查看结果 -> [人工确认真发]         |
+----------------------+-----------------------------------------------------------+
```

#### 数据来源

| 区块 | 数据来源 | 状态与说明 |
|---|---|---|
| 工作台草稿 | `GET /wb-api/drafts` | 【现有】来自 `data/workbench/drafts.json` |
| 既有待发队列 | `GET /wb-api/artifacts` 响应中的 `queue` | 【现有】只读扫描 `auto-publisher/autopub/articles/`，工作台不得向该目录写文件 |
| 发布记录与统计 | `GET /wb-api/ledger` | 【现有】只读账本；`uncertain` 必须突出显示并阻止自动重试 |
| 发布计划 | `GET/POST/PATCH/DELETE /wb-api/publish/plans...` | 【需新增】只写 `data/workbench/publication-plans.json` |
| 发布时间、账号、方式 | `GET /wb-api/publish/options` | 【需新增】账号只保存非敏感引用；方式固定返回 `xai`、`bit` 且 `available:false` |
| dry-run 与真发状态 | `/wb-api/publish/plans/{id}/dry-run`、`/confirm`、`GET /wb-api/publish/executions/{id}` | 【需新增】本期返回不可用/留桩；后续仅由工作台 subprocess 驱动既有 CLI |

草稿、待发队列、发布账本是三个不同事实域，不应混成一个可写列表。工作台草稿只在 `data/workbench/`；既有队列与账本只读。一个工作台草稿可以建立发布计划，但在没有合规的既有 CLI 入队契约前，不得由工作台偷偷写 `autopub/articles/`。

#### 交互流

1. 默认显示工作台草稿；可切换既有待发队列或发布记录，并按状态、平台、时间过滤。
2. 点击工作台草稿展示预览；点击「继续编辑」跳到 `#/article?sub=generate&draft_id=<id>`。
3. 点击「确认内容」创建发布计划快照，填写预约时间、账号引用、平台和发布方式。发布方式下拉展示「XAI / xAI-Grok 系 API」与「Bit / 比特浏览器 RPA」，两者均标注“本期未接入”。
4. 方式不可用时只允许保存计划，不显示可误触的真发按钮。
5. 后续通道可用后，第一步只能执行 `python cli.py publish run --draft ...`。UI 将命令摘要、目标账号、平台、稿件 hash、截图/校验结果列给用户。
6. 仅当该计划最近一次 dry-run 成功、稿件 hash 未变化、用户在确认对话框再次核对账号与平台后，才解锁「确认真发」。真发调用去掉 `--draft` 的同一 CLI 路径。
7. subprocess 返回 `2` 时提示登录/验证码/人工审核并停止；`uncertain` 时要求用户到平台后台核实，禁止自动重试；账本始终由 autopub 自己写，工作台只刷新读取。

#### 本期留桩点

- XAI 和 Bit 浏览器的鉴权、账号发现、登录态检测、API/RPA 调用全部不实现。
- 预约调度、批量平台发布、失败重试策略、平台格式适配不实现。
- 发布计划 CRUD 可以先落地；dry-run、真发按钮保持禁用并解释依赖条件。
- 不做从工作台草稿写入 `auto-publisher/autopub/articles/` 的旁路；后续须有正式 CLI 契约后再启用。
- 不提供编辑、修复、删除 `state.json` 的入口。

### 1.4 自动化任务（`sub=automation`）

#### 页面目的

把已经验证过的选材、生成和发布配置固化成可复用的定时任务。页面必须忠实呈现用户公式：

```text
自动化
= 建立任务
+ 建立工作流
+ 选择时间
+ 内容发布
```

自动化首先是「配置模板 + 执行状态机」，不是默认无人值守真发。受发布红线约束，任务可自动运行到 dry-run / 等待确认，但不得越过人工真发确认。

#### 布局区块

```text
+----------------------------------------------------------------------------------+
| 自动化任务                                      [新建任务] [仅看启用]             |
+----------------------+-----------------------------------------------------------+
| 任务列表             | 四步配置器                                                  |
| 每日早报 08:00       | 1 建立任务: 名称、说明、市场、回溯窗口                      |
| 周度复盘 Fri 18:00   | 2 建立工作流: 素材规则 + 四模块 + 排列组合 + 固定模板        |
| 状态: 等待确认       | 3 选择时间: 时区、频率、时间、错过执行策略                  |
| 最近/下次运行        | 4 内容发布: 账号、平台、XAI/Bit(桩)、停在 dry-run           |
| [日志] [复制]        | [校验配置] [保存停用] [启用]                               |
+----------------------+-----------------------------------------------------------+
| 执行记录: scheduled -> gathering -> generating -> dry_run -> waiting_confirmation |
+----------------------------------------------------------------------------------+
```

#### 数据来源

| 区块 | 数据来源 | 状态与说明 |
|---|---|---|
| 任务列表、新建、删除 | `GET/POST/DELETE /wb-api/automation` | 【现有】写 `data/workbench/automation.json`，调度仍为桩 |
| 编辑、启停 | `PATCH /wb-api/automation/{id}`、`POST /wb-api/automation/{id}/toggle` | 【需新增】仍只写 `automation.json` |
| 工作流选择 | `GET /wb-api/flows` | 【现有】只读工作流元数据；任务只保存引用和快照 |
| 推荐/选材规则 | `/wb-api/recommend` 与 `/wb-api/v1/*` 的参数模型 | 【现有 + 需扩展】保存筛选规则，不提前复制一批会过期的条目 |
| 发布时间与方式 | `GET /wb-api/publish/options` | 【需新增】复用发布页同一契约，XAI/Bit 均为桩 |
| 配置校验与运行记录 | `POST /wb-api/automation/{id}/validate`、`GET /wb-api/automation/{id}/runs` | 【需新增】校验结果/执行镜像落 `data/workbench/automation-runs.json` |
| 生成与发布事实 | `GET /wb-api/runs`、`GET /wb-api/ledger` | 【现有】只读关联展示，不篡改源状态 |

#### 交互流

1. 点击「新建任务」，按四步配置器完成名称、选材/工作流、时区与 cron 语义、发布计划。
2. 「建立工作流」复用内容生成页的模块、排列组合与模板组件；可从一个已保存草稿提取配置，但不固化草稿正文。
3. 「内容发布」复用发布页的账号/平台/方式选择器，默认终点固定为 `dry_run`。
4. 点击「校验配置」检查来源可达、flow 存在、时区/时间合法、账号引用存在、发布方式是否可用；只读检查，不运行任务。
5. 保存时默认 `enabled:false`。仅校验通过后允许启用；XAI/Bit 均未接入时，允许启用“生成至草稿”任务，不允许启用“发布”任务。
6. 后续调度器触发时，状态依次为 `scheduled -> gathering -> generating -> dry_run -> waiting_confirmation`。只有用户在内容发布页确认后才能进入 `publishing`。
7. 任务停用只影响后续触发，不终止正在执行的 subprocess；终止能力需单独设计并留审计记录。

#### 本期留桩点

- cron 调度器、开机补跑、并发锁、超时/重试、通知不实现。
- 自动选材可保存规则，但真实定时抓取与生成留桩。
- XAI/Bit 自动发布不实现；即使后续实现，也默认停在 `waiting_confirmation`。
- 复制任务、运行一次、暂停运行中的任务、运行日志下载先预留按钮与状态字段。
- 多时区、节假日日历、交易日条件先显示为「后续支持」。

---

## 2. 子页面跳转联动设计

### 2.1 子页面与共享对象

| 起点 | 动作 | 终点 | 传递内容 |
|---|---|---|---|
| 推荐信息 | 选中信息后「带入内容生成」 | 内容生成 | `draft_id` + 已选条目 ID；完整必要快照落草稿 |
| 内容生成 | 「保存」 | 内容生成 | 同一 `draft_id`、递增 `version` |
| 内容生成 | 「送至内容发布」 | 内容发布 | `draft_id`；发布页从服务端重新读取，不在 query 放正文 |
| 内容发布 | 点击稿件「继续编辑」 | 内容生成 | `draft_id` + `from=publish` |
| 内容发布 | 创建计划 | 内容发布 | `plan_id`；计划引用 `draft_id` 与不可变 `content_hash` |
| 自动化任务 | 从草稿提取配置 | 自动化任务 | `draft_id` 只用于一次性读取模块/编排/模板，任务保存自己的快照 |
| 自动化任务 | 编辑选材规则 | 推荐信息 | `task_id` + `return=automation`；返回时只更新任务规则 |
| 自动化任务 | 编辑工作流 | 内容生成 | `task_id` + `mode=workflow-template`；不覆盖普通草稿正文 |
| 自动化任务 | 查看等待确认的执行 | 内容发布 | `task_id` + `execution_id` + `plan_id` |

### 2.2 路由 query 规范

```text
#/article?sub=recommend&since=24h&markets=US,CN
#/article?sub=generate&draft_id=d0903143201
#/article?sub=publish&draft_id=d0903143201
#/article?sub=publish&plan_id=p0903150042
#/article?sub=automation&task_id=a0903080000
```

- `sub` 合法值固定为 `recommend/generate/publish/automation`，未知值回退 `recommend`。
- query 只携带定位信息和可分享的轻量筛选，不放正文、账号凭据或 API Key。
- 壳层实施时需把主路由与 query 分开解析；`WB.shell.setSubs([...], activeId)` 同步左侧高亮，`onPick` 用 `history.replaceState` 或 hash 更新写回 `sub`。
- 页面内部切换使用 `v-show` 可保留临时输入；刷新后的权威状态来自服务端 JSON，不能只依赖组件内存。

### 2.3 状态分层与冲突处理

```text
轻量筛选/定位        -> hash query
未提交选择篮         -> localStorage: wb_materials（现有）
可恢复编辑状态       -> data/workbench/drafts.json
发布计划与内容 hash  -> data/workbench/publication-plans.json
自动化定义/执行镜像  -> data/workbench/automation.json / automation-runs.json
生成、队列、账本事实 -> 既有只读接口（禁止工作台改源文件）
```

- 推荐条目带入草稿时保存 `item_id/title/text/time/source/url/tags` 的必要快照，同时保留 `item_id` 便于重新获取；原库内容变化不应静默改写已成稿依据。
- 草稿保存携带 `version`。版本不一致返回 `409` 和服务端当前版本，由用户选择覆盖或另存，不做静默最后写入获胜。
- 发布计划创建时计算 `content_hash`。草稿后续修改会让计划显示「内容已变化」，必须重新确认并重新 dry-run。
- 自动化任务保存的是筛选规则、flow 引用、模块编排和发布计划模板，不引用易变的页面临时状态。
- `state.json` 的 `published/failed/uncertain` 始终以 `/wb-api/ledger` 为唯一展示事实；`uncertain` 不允许重试按钮。

---

## 3. 需新增的后端端点清单

本节只列新端点，不重复当前已有的 `/recommend`、`/drafts`、`/automation`、`/flows`、`/runs`、`/artifacts`、`/ledger`。共规划 **14 个 method + path 端点**，全部位于 `workbench/server/`；落盘只允许 `data/workbench/*.json`。涉及物理动作时只允许 subprocess 调仓库根 `python cli.py ...`，绝不直接 import 三板块内部模块。

另外需要扩展、但不计入新增数量的现有契约：

- `GET /wb-api/recommend` 增加 `sources/info_types/event_types/sentiments/tickers/sort/cursor`，响应增加 `value_score/importance_score/reasons/next_cursor`。
- `POST /wb-api/drafts` 更新白名单增加 `status/arrangement/workflow/selection_snapshot/version`，冲突返回 `409`。
- 现有 `POST /wb-api/automation` 的模型增加 `source_rule/workflow/arrangement/timezone/publish_plan_template/stop_at`。

### 3.1 生成任务（2 个）

| # | 方法与路径 | 请求参数 | 返回 JSON 形状 | 落盘与阶段 |
|---:|---|---|---|---|
| 1 | `POST /wb-api/generation/jobs` | body: `draft_id, workflow, modules[], arrangement[], template, idempotency_key` | `{"job":{"id":"g...","status":"queued","draft_id":"d...","command_preview":["python","cli.py","flows","run","morning-paper"]}}` | `data/workbench/generation-jobs.json`；先做预检/排队桩，CLI 能消费素材契约后才允许 subprocess |
| 2 | `GET /wb-api/generation/jobs/{job_id}` | path: `job_id` | `{"job":{"id":"g...","status":"waiting_review","exit_code":2,"run_ref":{"flow":"morning-paper","date":"2026-09-03"},"artifacts":[]}}` | 读 `generation-jobs.json`，并只读关联 `/runs`、`/artifacts`；不改 `run.json` |

`POST` 使用 `idempotency_key` 防止双击重复生成；状态枚举为 `queued/running/waiting_review/done/failed/config_missing`，分别映射 CLI 退出码与工作台排队状态。

### 3.2 发布计划与执行闸口（8 个）

| # | 方法与路径 | 请求参数 | 返回 JSON 形状 | 落盘与阶段 |
|---:|---|---|---|---|
| 3 | `GET /wb-api/publish/options` | query 可选 `platform` | `{"methods":[{"id":"xai","title":"XAI","available":false},{"id":"bit","title":"Bit浏览器","available":false}],"accounts":[{"id":"acc1","platform":"xueqiu","label":"主账号","method":"bit","available":false}]}` | 读 `data/workbench/publish-options.json`；不得保存 cookie、密码、API Key；本期方式均不可用 |
| 4 | `GET /wb-api/publish/plans` | query: `draft_id,status,limit,cursor` | `{"plans":[{"id":"p...","draft_id":"d...","status":"configured","scheduled_at":"2026-09-04T08:00:00+08:00"}],"next_cursor":null}` | 读 `data/workbench/publication-plans.json` |
| 5 | `POST /wb-api/publish/plans` | body: `draft_id,scheduled_at,timezone,platforms[],account_ids[],method,stop_at` | `{"plan":{"id":"p...","status":"configured","content_hash":"sha256:...","method":"bit","method_available":false}}` | 写 `publication-plans.json`；从 `drafts.json` 生成内容 hash，不写待发队列 |
| 6 | `PATCH /wb-api/publish/plans/{plan_id}` | body 为可更新字段及 `version` | `{"plan":{"id":"p...","version":3,"status":"configured"}}`；冲突为 `{"error":"version_conflict","current_version":3}` | 写 `publication-plans.json`；稿件变化时清除旧 dry-run 资格 |
| 7 | `DELETE /wb-api/publish/plans/{plan_id}` | path: `plan_id`，query 可选 `version` | `{"deleted":true,"id":"p..."}` | 写 `publication-plans.json`；只删计划，不删草稿、队列或账本 |
| 8 | `POST /wb-api/publish/plans/{plan_id}/dry-run` | body: `confirm_content_hash,idempotency_key` | 本期 `501 {"error":"method_not_available","method":"bit"}`；后续 `202 {"execution":{"id":"e...","phase":"dry_run","status":"running"}}` | 后续写 `data/workbench/publish-executions.json`，且只可 subprocess 执行带 `--draft` 的 CLI |
| 9 | `POST /wb-api/publish/plans/{plan_id}/confirm` | body: `dry_run_execution_id,confirm_content_hash,confirmation_token,idempotency_key` | `202 {"execution":{"id":"e...","phase":"publish","status":"running"}}` 或 `409 {"error":"dry_run_required"}` | 后续写 `publish-executions.json`；校验同稿件 hash、最近 dry-run 成功与一次性确认 token 后，才可 subprocess 去掉 `--draft` |
| 10 | `GET /wb-api/publish/executions/{execution_id}` | path: `execution_id` | `{"execution":{"id":"e...","phase":"dry_run","status":"needs_human","exit_code":2,"ledger_refresh_required":true,"message":"需要登录或验证码"}}` | 读 `publish-executions.json`，发布结果再从【现有】`/ledger` 刷新；不写 `state.json` |

`confirmation_token` 只能由用户看完 dry-run 结果后的确认对话生成，短时有效且一次性。预约时间到达也只触发 dry-run；没有新的人工确认，不得自动调用真发。

### 3.3 自动化任务补齐（4 个）

| # | 方法与路径 | 请求参数 | 返回 JSON 形状 | 落盘与阶段 |
|---:|---|---|---|---|
| 11 | `PATCH /wb-api/automation/{task_id}` | body: `version` 加任务四段模型的任意子集 | `{"task":{"id":"a...","version":4,"enabled":false,"validation":"stale"}}` | 写 `data/workbench/automation.json`；更新后强制重新校验 |
| 12 | `POST /wb-api/automation/{task_id}/validate` | body 可选 `now` 供测试下次运行时间 | `{"valid":false,"checks":[{"code":"flow_exists","ok":true},{"code":"publish_method_available","ok":false}],"next_run_at":"2026-09-04T08:00:00+08:00"}` | 校验结果可写回 `automation.json`；只读查询 flows、数据源健康和发布选项 |
| 13 | `POST /wb-api/automation/{task_id}/toggle` | body: `enabled,version` | `{"task":{"id":"a...","enabled":true,"version":5},"warning":"任务只会运行到 waiting_confirmation"}` | 写 `automation.json`；发布方式不可用时，仅 `stop_at=draft` 的任务可启用 |
| 14 | `GET /wb-api/automation/{task_id}/runs` | query: `limit,cursor` | `{"runs":[{"id":"ar...","task_id":"a...","status":"waiting_confirmation","started_at":"...","plan_id":"p..."}],"next_cursor":null}` | 读 `data/workbench/automation-runs.json`，只读关联既有 `/runs` 与 `/ledger` |

建议统一错误形状：`{"error":"machine_code","message":"中文说明","hint":"下一步","details":{}}`。所有时间写 RFC 3339 含时区，所有列表提供稳定 ID；路径参数严格白名单，文件访问沿用 `views.py` 的越界防护思路。

---

## 4. 实施顺序建议

| 阶段 | 先做什么 | 后做什么 / 明确不做 | 可验证里程碑 |
|---|---|---|---|
| P0 契约冻结 | 冻结四个 `sub` ID、hash-query、草稿/发布计划/任务 JSON Schema、14 个新端点形状；补接口契约测试样例 | 不接 LLM、不接发布、不写前三板块 | 评审样例能完整走通「条目 ID -> draft_id -> plan_id -> task_id」，所有落盘路径均在 `data/workbench/` |
| P1 四页导航与只读镜像 | 在未来实现中用 `WB.shell.setSubs` 注册四页；拆出推荐、生成、发布、自动化视图；接 `/v1/*`、`/stats`、`/flows`、`/runs`、`/artifacts`、`/ledger` | XAI/Bit 按钮保持禁用；不触发 subprocess | 刷新任一 `#/article?sub=...` 能恢复子页；旧数据可读；离开图文页子菜单被清空 |
| P2 推荐与草稿闭环 | 扩展 `/recommend` 筛选/双分数；补草稿 `selection_snapshot/arrangement/version/status`；完成推荐带入、编辑、保存、返回编辑 | 生成模块只做配置和预检 | 选 3 条推荐后刷新页面仍能按 `draft_id` 恢复；并发旧版本保存得到 `409` |
| P3 发布计划与安全闸口 UI | 实现 options 与 publication plan CRUD；显示队列和账本只读镜像；完成内容 hash、方式不可用提示和 `uncertain` 熔断展示 | 不写 `autopub/articles/`，不实现 XAI/Bit，不开放真发 | 可从草稿创建发布计划；修改草稿后计划自动失效；仓库账本文件字节级不变 |
| P4 自动化配置闭环 | 补自动化 PATCH/validate/toggle/runs；四步配置复用推荐、生成、发布组件；默认停用 | 不实现常驻调度器；发布方式不可用时不允许发布型任务启用 | 能保存、复制（前端组合现有 POST）、校验、启停“生成至草稿”任务；发布型任务给出明确阻断原因 |
| P5 生成执行适配 | 仅在现有 `cli.py flows run` 能消费所需输入契约时，实现 generation jobs 与 subprocess 状态映射；处理退出码 0/2/3/4 | 不改 `ai-workflow` 代码来迁就工作台；不直接 import 引擎 | 一次测试运行生成任务镜像；exit 2 正确停在 `waiting_review`；`run.json` 只由既有引擎写 |
| P6 发布通道专项 | 分别评审 XAI/Grok API 与 Bit 浏览器 RPA 的安全、账号和能力契约；先实现 dry-run 适配与证据展示 | 本阶段仍不默认开放真发；Chrome/Bit 操作期间明确提示用户勿手动干预 | 任一方式仅执行带 `--draft` 命令；登录/验证码返回 needs_human；不产生 published 账本记录 |
| P7 人工确认真发 | 增加短时一次性确认 token、稿件 hash 复核、幂等键、审计记录；确认后才允许去掉 `--draft` | 不为定时任务提供绕闸开关；`uncertain` 永不自动重试 | 篡改稿件、过期 token、无成功 dry-run 均返回 409；合法确认只触发一次，账本仍仅由 autopub 更新 |
| P8 调度器 | 在工作台层实现单实例锁、错过策略、审计与恢复；任务自动运行至 draft/dry-run/waiting_confirmation | 不扩散写入前三板块，不把密钥写入任务 JSON | 重启后不重复执行同一时间槽；到点任务停在约定闸口；所有执行可由 `task_id` 追溯 |
