# 18-gemini-yttrack.md — 工作台视频页【热点追踪】MoA 独立答卷(gemini/agy)

> MoA 同题并行 2026-09-05,任务同 16 号文件。本篇为 gemini 岗位(agy/claude-opus-4-6-thinking,内部经 Antigravity 独立评审交叉验证)的独立答卷原文。
>
> 另:同轮 **cursor 岗答卷失败**——引擎侧内容安全过滤器拦截(`[1301][系统检测到输入或生成内容可能包含不安全或敏感内容…]`),未产出任何方案内容,非静默丢弃,特此留痕。

---

agy（claude-opus-4-6-thinking）的独立评审返回了，其中"账号库独立文件"的论证指出了一个我原判断低估的竞态（采集器长事务回写共享账号文件会覆盖 track.js 侧增删），我采纳其方案 B；快照合并单文件与状态文件防重入两案一并采纳并微调参数。以下是完整实施方案。

---

# 视频页七子页改造 +【热点追踪】实施方案（YouTube 频道追踪 · 24h 播放增量榜）

> 适用范围：`E:\ai-gen-article-publish` 板块四工作台（`workbench/`）。本期落地 7 个子页骨架 + 完整实现【热点追踪】【追踪账号】两个子页，其余 5 个子页为占位空页。全程遵守红线：workbench 对三板块只读、板块四唯一写口为 `data/workbench/` 自有 JSON、外呼只发生在 CLI 进程、SPA 免构建。

---

## 0. 改造总览与本期范围

| 子页 id | 标题 | 本期内容 |
|---|---|---|
| `hot` | 热点追踪 | **完整实现**：已启用频道的视频 24h Δviews 增量榜（表格 + 筛选 + 手动采集） |
| `analysis` | 视频分析 | 占位空页（"后续版本接入"卡片） |
| `script` | 脚本生成 | 占位空页 |
| `produce` | 视频制作 | **现有内容整体迁入**（项目列表 + mp4 播放，逻辑零改动） |
| `templates` | 模板仓库 | 占位空页 |
| `materials` | 素材仓库 | 占位空页 |
| `channels` | 追踪账号 | **完整实现**：YouTube 频道增删 + 启停 + 解析状态管理 |

数据通路（对齐 x_surge.py 现成范式"CLI 才外呼、服务器零外呼"）：

```
schtasks(每4h) ─┐
                ├─> py -3.11 cli.py workbench refresh-yt-track
页面「立即采集」─┘      │ (唯一外呼点: YouTube Data API v3)
                       v
        data/workbench/yt_channels.json   账号库(启用/停用/解析状态)
        data/workbench/yt_videos.json     视频表+快照时序(合并单文件)
        data/workbench/yt_refresh.json    采集运行状态/防重入/上轮报告
                       ^ 只读
        app.py /wb-api/yt/* 端点(纯读缓存+本地JSON读写, 零外呼)
                       ^
        video.js 七子页(hash路由内 tab + v-show)
```

---

## 1. 数据模型（全部落盘 `data/workbench/`，无数据库）

### 1.1 YouTube 账号库：`yt_channels.json`（新建，独立于 tracked_accounts.json）

行结构（JSON 数组，经 `config.load_rows/save_rows` 原子读写）：

```json
[
  {
    "id": "y0905143022",
    "input": "@Fedeconomics",
    "kind": "handle",
    "handle": "@Fedeconomics",
    "channel_id": "UCxxxx...",
    "title": "频道显示名",
    "note": "宏观 · 美债",
    "enabled": true,
    "resolve_status": "resolved",
    "resolve_error": "",
    "subs": 412000,
    "uploads_pid": "UUxxxx...",
    "last_discover_at": "2026-09-05 08:00:11",
    "last_error": "",
    "added_at": "2026-09-05 14:30:22"
  }
]
```

**与 `tracked_accounts.json` 的共存/迁移策略（本次权衡结论：两库并存，不迁移）**

- `tracked_accounts.json`（现文件，当前为空数组 `[]`）继续作为"全平台账号通讯录"，归 track.js 主页面管，**本期一行代码不改**；`yt_channels.json` 是"YouTube 追踪订阅库"，归视频页【追踪账号】子页管。用户意图"账号库放在【追踪账号】里"指视频页子页面，由本文件承载，语义不受损。
- 不复用单库的原因（交叉验证后定案）：① `track.js` 的删除走**数组下标**（`DELETE /wb-api/track/accounts/{idx}`，app.py L133-138 的 `load→pop(idx)→save` 全量回写），而采集器是一轮 30–120 秒的长事务，若共用文件，采集器收尾 save 会把事务期间用户在 track.js 的增删覆盖掉；track.js 本期禁改、无法加 id 感知，竞态无解。② 旧端点 POST 只写 4 字段，视频页需要的 `enabled/channel_id/resolve_status` 等字段加进共享文件后，track.js 的全量回写同样会截断这些扩展字段。独立文件后采集器只读写自己的文件，零冲突、零迁移（旧行无 schema 变更）。
- 代价与缓解：同一频道可能在两处重复登记 → 采集器按 `channel_id` 去重（同 id 多行只采一行）；track.js 主页面看不到视频页加的频道 → 在【追踪账号】子页加一句说明文案即可。未来若 track.js 升级为 id 化操作，可一次性合并迁移（字段超集，向前兼容）。

### 1.2 视频表 + 快照表：`yt_videos.json`（合并单文件，video_id 为键）

采用 x_engagement.json 同构形状（元数据内联在时序节点旁，一次原子落盘，避免两文件跨文件事务）：

```json
{
  "version": 1,
  "updated_at": "2026-09-05 12:00:31",
  "videos": {
    "dQw4w9WgXcQ": {
      "ch": "UCxxxx...",
      "title": "...",
      "published": 1757000000,
      "duration_s": 754,
      "is_short": false,
      "tags": ["fed", "rates"],
      "first_seen": 1757080000,
      "series": [
        {"ts": 1757080000, "v": 12034, "l": 512, "c": 87}
      ]
    }
  }
}
```

保留策略（`yt_track.py` 常量 + `_prune()`，学 x_surge.py L85-97）：

| 常量 | 值 | 说明 |
|---|---|---|
| `SNAPSHOT_RETAIN_D` | 28 | series 单点保留 28 天（覆盖 Δ24h/Δ7d 口径 + 4 倍容差；grok 建议 90d 只做参考，28d 已满足本期榜单位并守住文件体积） |
| `MAX_POINTS` | 64 | 单视频快照点上限，超出丢最旧 |
| `MAX_VIDEOS_PER_CHANNEL` | 30 | 发现阶段每频道只纳管最近 30 条（进 28d 快照窗） |
| `MAX_VIDEOS_TOTAL` | 8000 | 全库视频硬顶，超出按最后快照时间淘汰最旧（x_surge 同款） |
| `MAX_CHANNELS` | 300 | 启用频道硬顶，超出拒绝采集并在 yt_refresh.json 报错 |

体积估算（150 频道）：150×30=4500 视频 × 实际 ~40 点 × ~50B ≈ **6–9MB**，`build_view` 全量 parse 约 100–300ms（本地单用户可接受）；若实测超 20MB，压缩预案见 §6。

### 1.3 采集运行状态：`yt_refresh.json`

```json
{
  "running": true, "pid": 12345, "started_at": "2026-09-05 12:00:00",
  "last": {
    "finished_at": "2026-09-05 12:01:21", "exit": 0,
    "report": {"channels_enabled": 42, "resolved": 2, "discover_new": 17,
               "snapshotted": 812, "skipped_cooldown": 1304, "quota_units_est": 176,
               "errors": 1, "circuit_break": false}
  }
}
```

同时承担**防重入锁**（§2.5）：`running=true` 且 `started_at` 距今 <10min 且 pid 存活 → 拒绝新一轮。

### 1.4 `settings.json` 增段（API key 存放）

`config.py DEFAULTS` 增：

```python
"yt": {"api_key": ""},    # YouTube Data API v3 key, 仅存服务端
```

- `public_view()` 增打码：`v["yt"]["api_key"]=""`，附 `has_key` / `key_tail`（后 4 位）——与 `source.api_key`、`translate.api_key` 完全同模式（config.py L66-79）。
- `apply_patch()` 的空 key 保持逻辑：循环元组 `("source", "translate")` 扩为 `("source", "translate", "yt")`（config.py L85）。
- key 泄露面：`settings.json` 在 gitignored 的 `data/` 下；响应打码；前端 password 输入框。

---

## 2. 采集器：`workbench/server/yt_track.py`（新模块）+ CLI 挂载

### 2.1 模块职责与函数清单

```python
# 只读面(app.py 调, 零外呼)
load_store() -> dict                    # 损坏容错返回空库(对齐 x_surge.load_engage)
parse_channel_input(text) -> dict|None  # 纯本地归一化: @handle/youtube.com/@h|/channel/UC..|/c/x|/user/x|裸UC..|裸handle
build_view(pub, form, channel_id, sort, limit) -> dict   # 热点榜数据面(§5 口径)
read_status() -> dict                   # yt_refresh.json + pid 探活

# 采集面(仅 CLI 进程调)
resolve_channel(row, key) -> None       # channels.list(forHandle/forUsername, 1单位) 回填 channel_id/title/subs
collect(force=False, dry_run=False) -> dict   # 主流程, 返回报告并落 yt_refresh.json
_prune(store) -> None                   # 28d/64点/30条每频道/8000总量
```

`parse_channel_input` 识别规则：URL 正则提取 `/(?:channel\/(UC[\w-]{22})|@([\w.-]+)|c\/([\w.-]+)|user\/([\w.-]+))/`；裸 `UC[\w-]{22}` 判 channel_id；`@x` 或纯字母数字串判 handle；解析不出返回 None（端点回 400）。

### 2.2 `collect()` 主流程（一轮）

1. **防重入 guard**：读 yt_refresh.json，`running` 且 pid 存活（`os.kill(pid, 0)` 探活，Windows 兼容；异常=已死）且 `started_at` <10min → 返回 `{skipped: "already_running"}`；否则原子写 `running:true + pid + started_at`（`tempfile.mkstemp + os.replace`，全项目统一原子写）。10min 视为僵尸强制接管。
2. **key 检查**：`config.load()["yt"]["api_key"]` 为空 → 写状态文件 `exit:4` 并 **exit 4**（配置缺失，对齐 AGENTS.md 退出码契约）。
3. **解析 pending**：对所有 `enabled && resolve_status=="pending"` 行逐个 `resolve_channel`（`GET channels?part=snippet,statistics,contentDetails&forHandle=@x&key=...`，1 单位/个）。`/user/` 走 `forUsername`；`/c/` 先 forHandle 后 forUsername；都不中 → `resolve_status=failed + resolve_error`（**不做 search.list 兜底**：一次 100 单位 = 100 个频道一天的发现开销，失败让用户改输入重试更可控）。已 resolved 行顺带刷新 handle/title/subs（防改名，channel_id 为主键不受影响）。
4. **发现新视频**：对 resolved 且 enabled 频道，`GET playlistItems?part=snippet,contentDetails&playlistId=UU...&maxResults=50&publishedAfter=<now-7d RFC3339>&key=...`（1 单位/页；uploads 列表 id 用 **UC→UU 推导技巧** 省一次 channels.list，若 404 则调一次 `channels?part=contentDetails&id=UC..` 取权威 uploads id 回填 `uploads_pid`）；翻页直到页内最旧条目早于 publishedAfter 或见底，**每频道上限 3 页**。新 video_id 且该频道 28d 窗内视频数 <30 → 写入 videos 段。
5. **刷新统计 + 追加快照**：对"到期"视频（`published` 距今 ≤48h **全部**；更老的距上次快照 ≥12h）按 **50 个/批** 调 `GET videos?part=snippet,statistics,contentDetails&id=a,b,c..&key=...`（1 单位/批）。每视频 append `{"ts": now, "v": viewCount, "l": likeCount, "c": commentCount}`（int 解析失败记 None；隐藏计数时 v 可能缺 → None 照存）。同时刷新 title/duration/tags（**只覆盖元数据字段，绝不回填历史快照点**——口径审计的前提）。
6. **收尾**：`_prune` → 原子写 yt_videos.json → 状态文件写 `running:false + last 报告`。
7. **熔断**：任一响应 403 且 `reason=="quotaExceeded"` 或连续 3 次网络失败 → 立即收尾落盘已采数据，报告 `circuit_break:true`，CLI **exit 3**。

### 2.3 配额账（免费 10000 单位/天）

| 场景 | 计算 | 单位 |
|---|---|---|
| 稳态一轮 @150 频道 | 发现 ~150–200（多数频道 1 页）+ 统计 ~1100 条到期 /50 ≈ 22 + 解析 ~2 | ~180–220/轮 |
| 每天 6 轮（4h 节奏，分层冷却后实际外呼低于上界） | ×6 | **~1100–1300/天 ≈ 12%** |
| 冷启动首轮 @150 频道 | 解析 150 + 发现 ~375 + 统计 4500 条/50=90 | ~620（单轮完成无压力） |
| @300 频道满配 | 稳态翻倍 | ~25%，仍安全 |

与 grok 参考"每天 1–2 次"的偏离说明：4h 节奏让 Δ24h 的取点容差缩到 ±4h、日速更准，且分层冷却（≤48h 每轮 / 更老 12h）使单位成本仍在配额零头；想更省可将计划任务改 `/sc hour /mo 12`（12h 节奏，Δ24h 容差 ±8h 仍可用）。

### 2.4 无 key 降级表现

| 位置 | 表现 |
|---|---|
| `POST /wb-api/yt/collect` | 直接 400 `{error:"未配置 YouTube API Key", hint:"到 设置 → YouTube 追踪 填写"}`，不 spawn |
| `GET /wb-api/yt/hot` | 正常返回空榜 + `meta.configured:false`，页面顶部常驻引导横幅（链接 `#/settings`） |
| `GET /wb-api/yt/channels` | `meta.configured:false`；仍可添加频道（`resolve_status:"pending"`），列表解析状态列显示"待解析（未配 Key）" |
| `cli.py workbench refresh-yt-track` | exit 4，stderr 提示配置方法 |
| schtasks 定时轮 | 每轮空转 exit 4，日志记一行，无外呼无副作用 |

### 2.5 增量调度挂载

- **CLI**：`cli.py` 的 `workbench_cmd()`（L378）增分支 `args.sub == "refresh-yt-track"`：`sys.path.insert(0, str(WB)); from server import yt_track; rep = yt_track.collect(force=args.force, dry_run=args.dry_run)`；exit 映射 0/3(熔断)/4(无 key)。argparse（L640 旁）注册 `--force`（忽略快照冷却全量重采）、`--dry-run`（只做本地解析+打印采集计划，零外呼，验证用）、`--json`。
- **计划任务**：新建 `bin/yttrack_task.bat`，逐行仿 `bin/xsurge_task.bat`（cd /d %~dp0..、PYTHONUTF8=1、py -3.11 与 python 双路兜底、日志 `>> data\yttrack_task.log`）。登记命令写进 bat 注释：
  `schtasks /create /tn "aag-yttrack-refresh" /tr "<项目路径>\bin\yttrack_task.bat" /sc hour /mo 4 /f`
- **手动「立即采集」**：`POST /wb-api/yt/collect` 用 `subprocess.Popen` 异步 spawn 同一条 CLI 命令（**红线合规**：与 sources 启停同属"subprocess 调 cli.py"许可路径），立即返回；前端 3–5s 轮询 `GET /wb-api/yt/collect` 状态。不用同步 `subprocess.run`：一轮 30–120s 会卡死浏览器请求（sources enable 的 30s 同步模式只适用秒级操作）。防撞车：spawn 前服务端先查 yt_refresh.json guard，busy 时回 409；CLI 侧 guard 兜底 schtasks 与按钮同时触发的窗口。

---

## 3. 后端 API 新端点清单（app.py create_app 内新增闭包，风格对齐现有端点）

| # | 方法/路径 | 参数 / Body | 返回 shape |
|---|---|---|---|
| 1 | `GET /wb-api/yt/channels` | — | `{channels:[{id,input,kind,handle,channel_id,title,note,enabled,resolve_status,resolve_error,subs,videos_28d,last_snap_at,last_error,added_at}], meta:{configured,total,enabled_n,pending_n,failed_n}}` |
| 2 | `POST /wb-api/yt/channels` | `{input, note?, enabled?=true}` | 成功 `{added:{...行}, channels:[...]}`；空/非法 input → 400 `{error}`；重复（同 channel_id 或同归一化 handle）→ 409 `{error:"该频道已在追踪列表", existing_id}` |
| 3 | `POST /wb-api/yt/channels/{cid}/enabled` | `{on: bool}` | `{id, enabled}`（按 id 定位，未命中 404；本端点纯写 JSON，零外呼） |
| 4 | `DELETE /wb-api/yt/channels/{cid}` | — | `{removed: 1, channels:[...]}`（按 id；不删 yt_videos.json 历史数据，仅停止采集与榜单归属） |
| 5 | `GET /wb-api/yt/hot` | `pub=24h\|48h\|7d\|28d\|all`(发布窗，默认 7d)、`form=all\|short\|long`、`channel=<channel_id>`、`sort=delta24h\|delta7d\|rate\|views\|time`(默认 delta24h)、`limit<=300` | `{items:[{video_id,url,title,channel_id,channel_title,handle,published_at,age_h,duration_s,is_short,views,likes,comments,delta_24h,delta_7d,rate_per_day,first24_views,cold,snap_n,last_snap_at}], total, meta:{updated_at,data_age_min,cold_start,configured,enabled_channels,rule}}` |
| 6 | `GET /wb-api/yt/status` | — | `{configured, running, started_at, stale:bool, last:{finished_at,exit,report}}` |
| 7 | `POST /wb-api/yt/collect` | `{force?=false}` | 已在跑 → 409 `{error:"采集进行中", started_at}`；无 key → 400；否则 spawn 后 202 `{started:true}` |

实现要点：全部走 `config.load_rows/save_rows("yt_channels.json")` / 模块内 `load_store/_save_store`；#5/#6 纯读；#2/#3/#4 本地 JSON 原子写；**无任何端点直接外呼**（外呼只在 #7 spawn 的 CLI 进程内）。现有 `/wb-api/videos`（views.videos()）原样保留供【视频制作】子页使用。

---

## 4. 前端改造（`workbench/web/js/pages/video.js` 单文件重构 + index.html 版本号）

### 4.1 七子页骨架（学 news.js / article.js 模式）

- `data()` 增 `tab: "hot"`（默认落热点追踪）；`SUBS` 常量数组声明 7 项（id/title/inline SVG icon，仿 news.js 的 `I()` helper）。
- `mounted()`：先执行现有 `/videos` 拉取（供 produce 子页），再 `registerSubs()`：
  ```js
  registerSubs() {
    if (!WB.shell) return;
    if (!location.hash.replace(/^#/, "").startsWith("/video")) return;  // 迟到回调守卫
    WB.shell.setSubs([...七项...], this.tab);   // 每项 onPick: () => { this.tab = id; }
  }
  ```
  `unmounted()` 调 `WB.shell.setSubs([])`。
- 模板：现文件 `.two-col` 整块包进 `<div v-show="tab==='produce'">`（内容零改动），其余 6 个子页各一个顶层 `<div v-show="tab==='...'">`；5 个占位子页统一渲染 `notice` + 空 card（"该子页将在后续版本接入"）。
- `workbench/web/index.html`：video.js 引用版本号 `?v=0908b` → `?v=0908c`（防旧 JS 缓存混载，对齐现有 no-cache 策略）。

### 4.2 【热点追踪】子页（主视角）

- **引导横幅区**（按 `meta` 三态）：未配 Key → "未配置 YouTube API Key，到 设置 → YouTube 追踪 填写后才能采集"；冷启动（`meta.cold_start` 或行级 `cold`）→ "快照冷启动中：增速需第 2 轮采集（约 4 小时后），当前先按累计播放排序参考"；正常 → 数据龄条"快照更新于 X 分钟前 · 启用频道 N 个"。
- **工具栏**：发布窗下拉（24h/48h/7d/28d/全部，默认 7d）、类型（全部/Shorts/长视频）、频道下拉（来自 /yt/channels 的 enabled 行）、排序五选（Δ24h↓/Δ7d↓/日速↓/累计播放↓/最新发布）、`刷新` 按钮（重拉 /yt/hot）、`立即采集` 按钮（POST /yt/collect → 置 busy → 3s 轮询 /yt/status 至 `running:false` → 重拉榜单 + toast 上轮报告摘要）。
- **主表格**（`tbl` 样式复用）：`# | 频道 | 标题(↗ youtube.com/watch?v=) | 发布时间 | 时长·Shorts徽章 | 累计播放 | Δ24h | 日速/天 | Δ7d | 点赞 | 评论`；Δ 列 null 显示 `—(冷)` 并 title 说明；排序切换走服务端 `sort` 参数重拉（对齐 x-surge 页做法，前端不做本地排序）。
- **空态**：无启用频道 → 引导去【追踪账号】；有频道无数据 → "首轮采集尚未运行，点「立即采集」"；接口错误 → err-box（WB.api 已规范化 {error,hint}）。

### 4.3 【追踪账号】子页

- **添加表单**：单输入框（接受 `@handle` / 频道主页 URL 粘贴 / 裸 UC id）+ 备注 + "保存后立即启用追踪" checkbox（默认勾选）→ `POST /yt/channels`；409 时 toast "该频道已在列表"。
- **列表表格**：`启用(switch 开关, 复用 news.js 来源详情的 .switch 样式与 toggleEnabled 交互) | 频道(标题 + @handle) | 解析状态徽章(待解析/已解析/失败+原因title) | 订阅数(标注"取整参考") | 28d视频数 | 最近快照 | 备注 | 删除`。
- **说明文案**："频道解析与首次数据在下一轮采集完成（定时每 4h，或点热点追踪页「立即采集」）；此处清单与「追踪」主页面的账号通讯录相互独立。"
- 删除二次确认（`confirm()` 即可，对齐单文件 SPA 风格）。

---

## 5. 派生指标口径定义（build_view 服务端统一计算，前端只展示）

| 指标 | 定义 | 边界处理 |
|---|---|---|
| `delta_24h` | `v(最新点) − v(最接近 now−24h 的点)`，取点容差 **[now−32h, now−16h]** | 窗内无点 或 点数<2 → null，`cold:true` |
| `delta_7d` | 同上，基准 now−7d，容差 **[now−8d, now−6d]** | 同上 |
| `rate_per_day` | `(v_last − v_prev) / span_days`（最近两点，span ≥ 30min 防抖，学 x_surge 5min 防抖的比例） | span 不足 → null；即"折合日速"，grok 参考同口径 |
| `first24_views` | 发布后 24h 表现：`v(首个 ts ≥ published+24h 的点) − v(首个点)` | 仅当首点 ts ≤ published+6h 才给值（首日窗口内纳管），否则 null（口径：未捕获首日） |
| `is_short` | `duration_s ≤ 180`（2024-10 起 Shorts 上限 3min；≤60s 为经典 Short，前端徽章不区分） | duration 缺失 → null，form 筛选时归入"全部" |
| `age_h` | `(now − published)/3600` | published 解析失败 → 排除出榜单并计 meta |
| 排序 | 默认 `delta_24h` 降序；null 一律沉底，平分按累计 views 降序（x_surge sort_key 同风格） | `views` 排序用最新点累计值；`time` 用 published 降序 |

**口径变更注记（2026-08-24 起 YouTube 播放计数改"开始播放即计"）**：快照只 append 不回填，每个点的 v 都是当时口径的原始累计值；口径切换日之后的斜率与历史不可直接比，`meta.rule` 固定透出该说明，前端表格脚注展示。订阅数为公开接口取整值，禁止当精确净增展示（列名就叫"订阅(取整)"）。

---

## 6. 风险与边界

| 风险 | 影响 | 对策 |
|---|---|---|
| quota 超限（403 quotaExceeded） | 当天后续轮全灭 | 配额账上界 ~25%（300 频道满配）；运行期熔断（§2.2 第 7 步）+ exit 3 + 页面 meta 提示；MAX_CHANNELS=300 硬顶 |
| 快照冷启动无增速 | 上线首日 Δ 列全空 | 行级 `cold` 标记 + 页面横幅明示"第 2 轮起有增速"；冷启动期榜单自动按累计 views 呈现（不排序丢失） |
| 口径变更 / 隐藏计数 | 斜率断裂、v 缺失 | 只 append 不回填 + rule 透出；v=None 的点照存，派生指标跳过 None 点 |
| 空库表现 | 前端卡死/报错 | `load_store()` 损坏容错返回空库；build_view 空库返回 `{items:[], meta:{cold_start:true}}`；前端三态空态文案 |
| 文件膨胀 | 读取变慢 | 28d/64 点/30 条每频道/8000 总量四重 prune，估算 ≤9MB；预案：若实测 >20MB，先把 series 截到 14d（Δ7d 口径不受损），仍不够再按频道分片 `yt_videos/<UC前6>.json` |
| 防重入失灵（PID 复用） | 双采集并发写坏缓存 | PID 探活 + started_at 10min 僵尸过期双条件；JSON 全程原子写（os.replace），最坏丢一轮不损库 |
| handle 改名 / 频道删视频 | 数据归属漂移 | 主键 channel_id；每轮解析顺带刷新 handle/title；删除视频 404 时保留历史快照并标 last_error |
| track.js 共存 | （已规避） | 两库独立 + channel_id 去重；两处重复登记同一频道只采一行 |
| key 泄露 | 配额被盗用 | settings.json 服务端存放 + public_view 打码 + password 输入框；data/ 已 gitignore |
| ToS | 账号风险 | 只走官方 Data API v3，**不引 Playwright/爬网页**（grok 参考明确告诫） |

---

## 7. 实施步骤清单（每步可独立验证）

| 步 | 内容 | 验证方式 |
|---|---|---|
| 1 | `config.py`：DEFAULTS 增 `yt` 段 + public_view 打码 + apply_patch 空key保持 | `py -3.11 -c` 调 `public_view(load())` 确认 has_key/key_tail；`PUT /wb-api/settings` 存 key 后 GET 回显为空 + 尾4位 |
| 2 | `settings.js` 增 "YouTube 追踪" 卡片（password 框 + 保存，仿 translate 卡） | 设置页填 key → data/workbench/settings.json 出现 yt.api_key，页面刷新后显示已配置尾4位 |
| 3 | `yt_track.py` 骨架：常量/load_store/_save_store/_prune/parse_channel_input（纯函数） | `py -3.11 -c` 冒烟：parse_channel_input 对 6 种输入形态的归一化断言；_prune 对超限假数据收敛 |
| 4 | cli.py 注册 `workbench refresh-yt-track`（--force/--dry-run/--json，exit 4 无key） | 无 key 时 `py -3.11 cli.py workbench refresh-yt-track --dry-run` exit 4；写 key 后 --dry-run 打印采集计划且零外呼（可抓包确认） |
| 5 | 端点 #1–#4（channels CRUD + enabled，零外呼） | `curl` 增/查/启停/删各一发；同时回归 track.js 主页面增删不受影响（两库独立） |
| 6 | `collect()` 主体（guard/解析/发现/快照/熔断）+ yt_refresh.json | 配真 key 跑一轮：检查 yt_channels.json 回填 channel_id/title、yt_videos.json 出现 series 首点、报告 quota_units_est 合理；连点两次验证 409 防重入 |
| 7 | 端点 #5–#7（hot/status/collect） | 用第 6 步真实数据 curl /yt/hot 各 sort/筛选组合；无数据账号下确认空态 shape |
| 8 | 第二轮采集（或 --force 提前触发）后验证派生指标 | 人工比对任一视频 YouTube 页面播放量与 Δ24h/日速自洽；冷启动标记消失 |
| 9 | video.js 七子页重构（produce 迁入 + 5 占位）+ index.html 版本 bump | 浏览器：7 个子页切换正常、 produce 项目列表与 mp4 播放回归无差、离开视频页左栏菜单清空 |
| 10 | hot/channels 两子页完整 UI + 交互 | 浏览器全链路：添加→启用→立即采集→榜单出现→停用后该频道行从榜单位消失；无 key 横幅与空态文案 |
| 11 | `bin/yttrack_task.bat` + schtasks 登记 | `schtasks /query /tn aag-yttrack-refresh`；手动 run 一次后 `data\yttrack_task.log` 与 yt_refresh.json 更新 |

依赖关系：1→2、3→4→6、5 依赖 3；7→9→10 可与 6 并行推进。

---

## 附：关键决策交叉验证说明

- **来自 Antigravity CLI（claude-opus-4-6-thinking）的独立评审**（对同一仓库只读分析）：①账号库推荐独立 `yt_channels.json`（B 案），核心理由是 track.js 下标 DELETE 的 load-modify-save 全量回写会覆盖视频页/采集器对共享行的字段更新，且 track.js 本期禁改无法修复；②快照推荐合并单文件、video_id 为键、28d 保留；③「立即采集」推荐 Popen 异步 + 状态文件轮询、锁用"状态文件 + PID 探活 + 过期时间"而非文件锁（Windows 语义差异）。
- **分歧点**：我初判倾向复用 tracked_accounts.json 单库（用户心智统一），agy 判定竞态风险不可接受。**综合判断采纳 B 案**：采集器 30–120 秒长事务的收尾回写窗口确实可能吞掉用户在 track.js 的增删，该风险在"本期禁改 track.js"约束下无低成本解；独立文件同时把迁移成本降为零。快照节奏上 agy 建议 4h/48 点，我按 Δ24h 取点容差与 7d 口径复算后定为 **4h 调度 + 12h 老视频冷却 + 64 点上限**（48 点在长冷却下会提前挤掉 7d 前的取点）。防重入、合并单文件两案直接采纳。
