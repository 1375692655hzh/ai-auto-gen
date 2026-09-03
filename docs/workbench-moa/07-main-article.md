# 图文页四子页方案 —— 主控(ZCode 对话模型)

> MoA 第三份。任务原文见用户消息；操作上下文：workbench 板块现状(8788 SPA + WB.shell 子菜单 + stats/ledger/flows/runs/artifacts 只读视图)。

## 总体结构

`article.js` 从旧三栏草版改为四子页容器：`mounted` 注册 4 个 `WB.shell` 子菜单(推荐信息/内容生成/内容发布/自动化任务)，组件内 `tab` + `v-show` 切换；四子页共享组件级 state(`selected[]` 已选信息、`editing` 草稿 id)，跳转 = 设 state + 切 tab + `WB.shell.setSub` 同步高亮(同 news.js 的 srcFilter 模式)。

## 子页1 推荐信息

- **目的**: 价值排序的信息池，是内容生成的素材入口。
- **布局**: 顶部工具条(回溯范围 select: 1h/4h/24h/3d/全部) + 标签筛选行(市场/类型/渠道 chips，复用 .chip) + 推荐列表(行式: 价值分 badge → 标题摘要 → 来源/时间/同事件×N/情绪 → 操作[加入生成])。
- **数据**: 新增 `GET /wb-api/recommend?since=&markets=&kinds=&channels=` —— 服务端复用 stats.py 的 items 抓取与 60s 缓存，按可解释规则打分排序:
  `score = dup_count×3(簇热度) + 机构/交易所源+2 + event_type∈{macro,policy,earnings}+2 + 情绪非中性+1 + tickers数×0.5`
  返回 items + 每条的 score 与 score_parts(UI 可展开"为什么推荐")。
- **留桩**: "选的源"= 推荐源收藏夹(本期默认全源，收藏功能留桩)。
- **联动**: [加入生成] → push 进 `selected[]` → 跳【内容生成】。

## 子页2 内容生成

- **布局三栏**: 左=信息选择(已选信息列表，可移除/上移下移)；中=生成模块排列组合(四张模块卡: 信息检索/快照抓取/技术分析/聚合分析，勾选+排序) + 固定模板下拉(来自 /wb-api/flows 真实工作流列表)；右=实时编辑预览(textarea + 字数统计) + [生成]桩按钮(提示走 `python cli.py gen run`) + [存草稿]真实按钮。
- **历史与草稿**: 左栏底部两节: 草稿(data/workbench/drafts.json 真实 CRUD，点击载入编辑器) / 历史记录(/wb-api/runs 只读，点开展示产物)。
- **新增端点**: `GET/POST/PUT/DELETE /wb-api/drafts`(config.py 原子写同款)。
- **留桩**: 四个模块的真实执行编排(本期只做选择与排列的 UI 状态)；LLM 真生成。

## 子页3 内容发布

- **布局上下两段**: 上=草稿列表(同 drafts 数据，操作[继续编辑]→ 载入并跳【内容生成】)；中=发布面板(选中草稿后展开): 发布时间(立即/定时 datetime-local)、发布账号(复用追踪页平台清单 14 个 checkbox)、发布方式(radio: XAI API / Bit 浏览器自动化，本期留桩置灰)；下=发布记录(/wb-api/ledger 真实账本: 时间/平台/文章/结果/链接)。
- **留桩**: [确认发布]置灰桩 + 红线提示(真发走 `python cli.py publish run --draft` 先行)。"推入待发队列"因红线 7(工作台只写 data/workbench/)本期不做，面板注明。

## 子页4 自动化任务

- **布局**: 左=任务列表(data/workbench/automation.json 真实 CRUD)；右=建任务四步表单(纵向步骤条): ①建立任务(名称/备注) ②建立工作流(选模板 + 模块组合沿用内容生成的勾选态) ③选择时间(每天/每周 + 时刻) ④内容发布(产物去向: 存草稿/推队列/直接发——后两者桩)。
- **新增端点**: `GET/POST/DELETE /wb-api/automation`。
- **留桩**: 真实调度(未来接 Windows 任务计划，对齐 bin/refresh_task.bat 模式)，页面注明。

## 端点汇总

| 端点 | 方法 | 数据 |
|---|---|---|
| /wb-api/recommend | GET | 数据站 items 打分排序(复用 stats 抓取缓存) |
| /wb-api/drafts | GET/POST/PUT/DELETE | data/workbench/drafts.json |
| /wb-api/automation | GET/POST/DELETE | data/workbench/automation.json |

## 实施顺序

后端三端点 → article.js 容器+四骨架 → 推荐信息(全真) → 内容生成+草稿(全真) → 内容发布(账本全真+发布桩) → 自动化(任务全真+调度桩)。
