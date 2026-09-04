# 16-codex-yttrack.md — 工作台视频页【热点追踪】MoA 独立答卷(codex)

> MoA 同题并行 2026-09-05,任务:视频页七子页(热点追踪/视频分析/脚本生成/视频制作/模板仓库/素材仓库/追踪账号),先做【热点追踪】(追踪 YouTube 账号视频数据,24h 内按播放量排序,定时快照差分)+【追踪账号】(账号库启停),其余子页占位。本篇为 codex 独立答卷原文,合成裁决见 18 号文件执行记录。

---

仓库现状已核验完毕（config.py 的 `load_rows/save_rows`/打码回显、app.py 路由与 subprocess 模式、x_surge.py 的"CLI 才外呼"快照架构、news.js 的 setSubs 子页模式、track.js 与 tracked_accounts.json 行结构、css 现成的 `.switch/.tbl/.badge/.acct-grid` 均已确认）。以下为完整实施方案文档。

# 工作台·视频页【热点追踪】+【追踪账号】实施方案

> 范围：本期只做视频页 7 子页改造骨架 + **【热点追踪】【追踪账号】两个子页的完整功能**（YouTube 账号视频数据追踪，24h 播放榜）；其余 5 个子页（视频分析/脚本生成/模板仓库/素材仓库 + 视频制作迁移）为占位或迁移既有内容。不引数据库、不引 npm、不建后台线程，全部落盘 `data/workbench/` 自有 JSON。

## 0. 总体架构决策（对齐既有红线）

| 决策 | 内容 | 依据 |
|---|---|---|
| 数据库 | 不引入，3 个 JSON 文件（账号/视频/快照），原子写 | 复用 `config.load_rows/save_rows`；同 x_engagement.json 模式 |
| 外呼边界 | **采集只在 CLI 进程外呼**（`workbench refresh-yt-track`），app.py 端点零外呼只读缓存 | x_surge.py 架构红线逐字沿用 |
| "立即采集" | 前端按钮 → `POST /wb-api/yt/collect` → **subprocess 调 `py -3.11 cli.py workbench refresh-yt-track --json`**（timeout 300s） | app.py `/wb-api/sources/{sid}/enabled` 的 subprocess 模式 |
| API | YouTube **Data API v3 only**，禁网页爬取 | 任务参考材料（ToS 风险） |
| 追踪账号存储 | 与 `tracked_accounts.json` **分文件共存**，见 §1.6 | track.js 本期不动（任务约束） |
| 主表视角 | 未采集的新视频也出现在榜上（互动字段 null 沉底），快照是可选 join | x_surge.build_view 同款哲学，冷启动不白屏 |

## 1. 数据模型（①）

### 1.1 落盘文件总览（全部 `data/workbench/` 下，gitignored）

| 文件 | 角色 | 读写方 |
|---|---|---|
| `yt_channels.json` | 追踪账号库（视频页【追踪账号】子页的增删启停对象） | app.py 读写；采集器读+回写状态 |
| `yt_videos.json` | 视频表（元数据 + 最新统计内联） | 采集器写；app.py 只读 |
| `yt_snapshots.json` | 统计时序快照（Δviews 的唯一来源） | 采集器写；app.py 只读 |
| `settings.json` | 增 `youtube.api_key` 段 | config.py 原有原子写 |

### 1.2 `yt_channels.json` —— 账号行结构

```json
{
  "version": 1,
  "updated_at": "2026-09-05 09:00:00",
  "channels": [
    {
      "cid": "UCX6OQ3DkcsbYNE6H8uQQuVA",
      "input": "https://www.youtube.com/@FedWatch",
      "handle": "@FedWatch",
      "channel_id": "UCX6OQ3DkcsbYNE6H8uQQuVA",
      "title": "FedWatch",
      "note": "宏观/美联储",
      "enabled": true,
      "status": "ok",
      "error": "",
      "subscribers": 1230000,
      "video_count": 342,
      "uploads_playlist": "UUX6OQ3DkcsbYNE6H8uQQuVA",
      "imported_from": "",
      "added_at": "2026-09-05 09:00:00",
      "resolved_at": "2026-09-05 09:05:00",
      "last_collected_at": "2026-09-05 10:00:00"
    }
  ]
}
```

**输入解析规则**（纯函数 `parse_channel_input(s) -> {kind, value}`，可离线单测）：

| 输入形态 | 识别 | 解析方式（消耗配额） |
|---|---|---|
| `UC` + 22 位 `[\w-]` | channel_id | 直接入库，status=pending 待首轮回填元数据 |
| `@handle`（3–30 位 `[\w.-]`） | handle | `channels.list?forHandle=@x`（1 单位） |
| `youtube.com/channel/UC…` | channel_id | 同上 |
| `youtube.com/@handle` | handle | 同上 |
| `youtube.com/c/Name`、`/user/Name`（遗留） | legacy | `search.list?type=channel`（**100 单位**）一次性，结果缓存进行内；UI 提示优先粘贴 UC 链接 |
| 裸文本 | 拒绝 | 前端提示"请粘贴频道主页链接、@handle 或 UC 开头的频道 ID" |

### 1.3 `yt_videos.json` —— 视频表

以 `video_id` 为键的 dict（与 x_engagement 的 statuses 同构，避免列表全量扫描）：

```json
{
  "version": 1,
  "updated_at": "2026-09-05 10:00:00",
  "videos": {
    "dQw4w9WgXcQ": {
      "video_id": "dQw4w9WgXcQ",
      "channel_id": "UC…",
      "title": "…",
      "published_at": "2026-09-04T08:00:00Z",
      "duration_s": 512,
      "is_short": false,
      "tags": ["fed", "rates"],
      "description_head": "前 300 字",
      "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg",
      "title_history": [{"title": "旧标题", "first_seen": "…", "last_seen": "…"}],
      "status": "ok",
      "first_seen_at": "…",
      "last_stats_at": "…",
      "last_views": 152300, "last_likes": 4300, "last_comments": 210
    }
  }
}
```

### 1.4 `yt_snapshots.json` —— 快照表

```json
{
  "version": 1,
  "caliber": "count-on-start-2026-08-24",
  "updated_at": "…",
  "last_collect_at": "2026-09-05 10:00:00",
  "series": {
    "dQw4w9WgXcQ": [
      {"ts": 1757000000, "v": 152300, "l": 4300, "c": 210}
    ]
  }
}
```

**保留与降采样**（写盘前 `_prune()`，复制 x_surge 的思路）：
- 分档采样间隔：发布 ≤48h → 60min；≤7d → 6h；≤30d → 24h；≤90d → 7d；>90d 不再采样。
- `MAX_POINTS = 160`/视频：超限时 48h 内全保，更老按**本地日历日保留最接近 08:00 的一个点**（日界锚点，保证 Δ7d/Δ30d 可算），其余丢最旧。
- `MAX_VIDEOS = 5000` 硬顶：超出按最久未采样淘汰；age > 120d 的视频连快照整体清除。
- 写盘用紧凑分隔符 + tempfile 原子 replace（同 `_save_engage`）。
- 体积估算：100 账号 × 90 天窗口 ≈ 2000 视频 × ≤160 点 × ~55B ≈ **<18MB**，单用户本地可接受；热点页只内联读 `last_views`，时序仅派生指标时展开。

### 1.5 `settings.json` 新增段

```json
"youtube": { "api_key": "", "collect_cooldown_min": 5 }
```
- `config.DEFAULTS` 增该段；`public_view()` 打码回显 `has_key` / `key_tail`；`apply_patch` 的"留空=保持不变"白名单从 `("source","translate")` 扩到含 `"youtube"`。

### 1.6 与 `tracked_accounts.json` 的共存/迁移策略

| 项 | 决策 |
|---|---|
| 共存 | `tracked_accounts.json` 保持原样（track.js 主页面"追踪"继续用它，**本期一行不改**）；视频页【追踪账号】子页读写独立的 `yt_channels.json` |
| 不合并的理由 | 旧行 `{platform, account, note, added_at}` 无 `enabled`/`channel_id`/状态字段；app.py 的 track 增删按**数组下标**定位，混合后启停/删除会串行；两库采集器语义不同（X 互动 vs YouTube Data API） |
| 迁移 | 提供 `POST /wb-api/yt/channels/import`：扫 `tracked_accounts.json` 中 `platform=="YouTube"` 且 `account` 可被 `parse_channel_input` 识别的行 → 追加进 `yt_channels.json` 并写 `imported_from:"tracked_accounts"`。**只复制不删源**，已导入的（按 input 去重）跳过，返回 `{imported:[…], skipped:[…]}` |
| 未来 | 若"追踪"主页面后续聚合各平台指标，再议合并；本期两 UI 各管各文件，无写冲突（不同文件+原子写） |

## 2. 采集器（②）—— 新模块 `workbench/server/yt_track.py`

### 2.1 模块形状（对齐 x_surge.py）

```
parse_channel_input(s)          # 纯函数, 离线可测
resolve_channel(rows, key)      # 对 status=pending 的行做 forHandle/search 解析
collect(force=False) -> dict    # 一轮采集, 返回并 print 一行 JSON 报告
load_snapshots()/save_snapshots()/_prune()   # 缓存读写+保留策略(同 _save_engage)
hot_view(range, sort, kind, channel, q, limit) -> dict   # 服务器读缓存视图, 零外呼
```

HTTP 用 `urllib.request`（零新依赖，同 x_surge/x_profile_enricher）；**不引** google-api-python-client。

### 2.2 一轮 `collect(force)` 流程

1. **前置**：取 key（`settings.json.youtube.api_key` 优先，env `YOUTUBE_API_KEY` 兜底）；无 key → 报告 `{"ok":0,"error":"no_api_key","hint":"设置页配置 YouTube Data API Key"}` 退出码 4。
2. **冷却**：`force=False` 且距 `last_collect_at` < `collect_cooldown_min`(默认 5min) → 直接返回 skip 报告（防前端按钮与计划任务双跑）。
3. **解析**：对 pending 行做 `resolve_channel`（forHandle 1 单位/个；仅首次）。
4. **账号元数据**：enabled 且 status=ok 的 channel_id 按 50 个一批 `channels.list?part=snippet,statistics,contentDetails`（1 单位/批）→ 回填 title/subscribers/uploads_playlist；`enabled=false` 的完全跳过。
5. **新视频发现**：每频道拉 `playlistItems.list`（uploads 播放列表，**只取第 1 页 50 条**，1 单位/频道；按 publishedAt 倒序天然增量），新 video_id 落入 yt_videos（元数据先空，等步骤 6 回填）。
6. **统计刷新候选集**：(a) 新视频；(b) `now−last_stats_at` 大于其**分档间隔**的已有视频（≤48h 档 1h / ≤7d 档 6h / ≤30d 档 24h / ≤90d 档 7d —— 复刻 x_surge 分层冷却）。按 50 个一批 `videos.list?part=snippet,statistics,contentDetails`（1 单位/批）。API 返回空缺的 id → 该视频 `status="unavailable"`。
7. **追加快照 + 改标题检测**：每个成功视频 append `{ts,v,l,c}`；`snippet.title` 与存量不同 → 旧标题推入 `title_history`。仅对 `published_at` 距今 ≤90d 的视频采样（>90d 只在 videos.list 被动刷新）。
8. `_prune()` → 原子落盘三件（channels 状态 / videos / snapshots）→ print 报告：`{"accounts": n_enabled, "resolve_ok": …, "new_videos": …, "refreshed": …, "failed": …, "quota_used_estimate": …, "cooldown_skip": bool, "quota_exceeded": bool, "cache": "…\\yt_snapshots.json"}`。
9. **熔断**：任一请求命中 403 `quotaExceeded` → 立即中止本轮（保留旧快照），报告 `quota_exceeded:true`，CLI 退出码 3（同 x_surge circuit_break 语义）。

### 2.3 配额预算（免费 10,000 单位/日）

| 调用 | 单价 | 100 账号一轮估算 |
|---|---|---|
| channels.list（50/批） | 1 | 2 |
| playlistItems.list（1 页/频道） | 1 | 100 |
| videos.list（50 id/批） | 1 | 6–10（候选集 ≈300–500 个：48h 全量 + 到期分档） |
| search.list（仅遗留 URL 一次性） | 100 | 0（常规轮） |

**一轮 ≈ 110 单位** → 60min 节奏 ≈ 2,700 单位/日（安全）；30min ≈ 5,400（仍安全）。默认 60min。**禁用 search.list 于常规轮**；UI 添加账号引导粘贴 `/@handle` 或 UC 链接。

### 2.4 调度挂载

- `cli.py`：`workbench` 子命令组新增 `refresh-yt-track`（`--force` 忽略冷却 / `--json`），实现照抄 `refresh-x-surge` 分支（`sys.path.insert(0, str(WB)); from server import yt_track`）。
- 新建 `bin/yttrack_task.bat`（逐行复制 xsurge_task.bat，改子命令名与日志 `data\yttrack_task.log`），注册：
  `schtasks /create /tn "aag-yttrack-refresh" /tr "<项目路径>\bin\yttrack_task.bat" /sc minute /mo 60 /f`
- workbench serve 进程**不起任何线程**做采集（app.py 保持纯读 + subprocess 触发）。

### 2.5 无 key 降级表现（逐层）

| 层 | 表现 |
|---|---|
| 采集器 | 拒跑并出 no_api_key 报告；**已落盘缓存完好** |
| `POST /yt/channels` | 照常入库，`status="pending"`，首轮采集再解析 |
| `GET /wb-api/yt/hot` | 正常 200，`meta.has_key:false`，rows 可能为空；前端热点页顶部出 notice 卡："未配置 YouTube Data API Key → 设置页粘贴 → `python cli.py workbench refresh-yt-track`"（样式同 track.js 现有 notice） |
| 设置页 | key 输入框 + has_key/key_tail 状态（照抄 source.api_key 模式） |

## 3. 后端 API 新端点清单（③，风格对齐 app.py：函数路由 + JSONResponse 错误）

| 方法/路径 | 参数 | 返回 shape |
|---|---|---|
| `GET /wb-api/yt/hot` | `range=24h\|48h\|7d\|30d\|all`（发布时间窗，默认 24h）；`sort=views\|views24h\|views7d\|likes\|newest`（默认 views）；`kind=all\|short\|long`；`channel=<cid>`；`q=<标题子串>`；`limit=100` | `{meta:{has_key, has_data, cold_start, last_collect_at, caliber}, rows:[{video_id,title,channel_id,channel_title,published_at,age_h,is_short,duration_s,views,views_24h,views_7d,likes,comments,thumbnail,url,delta_credible}]}`（null/不可信排序沉底，同 x_surge） |
| `GET /wb-api/yt/channels` | — | `{channels:[…1.2 行结构…], meta:{has_key, last_collect_at}}` |
| `POST /wb-api/yt/channels` | `{input, note}` | 400=输入不可识别；否则 `{channels}`（新行 status=pending，cid=临时 id） |
| `POST /wb-api/yt/channels/{cid}/enabled` | `{on:bool}` | `{cid, enabled}`（本地写，零配额） |
| `DELETE /wb-api/yt/channels/{cid}` | — | `{channels}`（删行；**保留**该频道已采视频/快照为孤儿数据不再刷新，防误删丢历史） |
| `POST /wb-api/yt/channels/import` | — | `{imported:[…], skipped:[…]}`（§1.6） |
| `POST /wb-api/yt/collect` | — | subprocess 调 `cli.py workbench refresh-yt-track --json`（timeout 300s，解析 stdout 末行 JSON）；504=超时；`{report}` 或 `{error}` |
| `GET /wb-api/yt/video/{vid}` | — | `{video, series:[{ts,v,l,c}], title_history}`（详情抽屉/迷你曲线用；本期可选） |

实现要点：hot 端点组装进 `yt_track.hot_view()`，app.py 里只留 10 行薄壳（照 `x_surge_view` 写法）；全部只读 `data/workbench/yt_*.json`，除 channels 三个写端点与 collect 外零副作用。

## 4. 前端（④）

### 4.1 `video.js` 7 子页改造结构

```
data(): { tab:"hot",
          hot:{rows:[],meta:null,loading,f:{range:"24h",sort:"views",kind:"all",channel:"",q:"",limit:100},collecting},
          ch:{list:[],showForm:false,form:{input:"",note:""}},
          prod:{videos:[],sel,error} }
methods: registerSubs()  // 照 news.js: hash 以 /video 开头才注册, setSubs 七项(id/title/icon/onPick: tab=…)
         loadHot()/loadChannels()/doCollect()/toggleCh(i,on)/addChannel()/delChannel(i)/importLegacy()
         fmtViews(n)/fmtDelta(n,credible)/ageText(published_at)
mounted: registerSubs(); loadChannels(); loadHot();
unmounted: WB.shell.setSubs([])
template: 7 个顶层 <div v-show="tab==='…'">
```

子页清单与内容：`hot` 热点追踪（完整）｜`analysis` 视频分析（占位）｜`script` 脚本生成（占位）｜`prod` 视频制作（**原项目列表+mp4 播放两栏原样迁入**）｜`templates` 模板仓库（占位）｜`assets` 素材仓库（占位）｜`tracked` 追踪账号（完整）。
占位页样式：muted 卡 + "后续版本规划" + 相关 cli 命令提示（复用 `stub-wrap/stub-tip`）。`index.html` 的 `?v=` 版本参数随改动 bump。

### 4.2 热点追踪页主视角

- **工具栏**：窗口 select（24h 默认/48h/7d/30d/全部）｜类型（全部/Shorts/长视频）｜频道下拉（来自 `/yt/channels`，含"全部"）｜搜索框（标题）｜**立即采集**按钮（loading 态 + "最近采集 xx 前"）。排序两档主视角：`发布窗内按累计播放`（默认，对应"24h 内按播放量排序"）与 `按 Δ24h 增量`（增速榜）。
- **表格**（复用 `.tbl`）：缩略图（`mqdefault` 外链，lazy）｜标题（新窗口开 YouTube）｜频道｜发布时间+age｜类型徽章（`.badge blue`=Shorts）｜累计播放｜**Δ24h**（ credible=false 显示"—"并沉底）｜Δ7d｜点赞｜评论。行点击 → 详情抽屉（/yt/video/{vid} 快照迷你条形，本期可后置）。
- **空态三分**（互斥）：无 key → 配置引导卡；有 key 冷启动（`meta.cold_start`=任一行快照点 <2）→ "快照累计中，第二天起出增速，当前按累计播放排序"提示 + 正常表格（Δ 列全"—"）；真无数据 → "先到【追踪账号】添加并启用频道"。

### 4.3 追踪账号页

- 卡片网格复用 `.acct-grid`；每卡：频道名 + handle｜订阅数（注"公开口径取整"）｜状态 pill（ok=绿/pending=黄/error=红，复用 `pillClass` 思路）｜**`.switch` 启停开关**（已有现成样式，busy 态防连点）｜删除（confirm 后调 DELETE）。
- 添加表单：录入框（接受链接/@handle/UC）+ 备注 + 保存；保存后若 `meta.has_key` 则自动触发一次 `POST /yt/collect` 让新账号尽快出数据。
- 底部"从旧追踪清单导入 YouTube 账号"按钮 → `/channels/import`，toast 汇报 imported/skipped。

## 5. 派生指标口径定义（⑤）

| 指标 | 定义 |
|---|---|
| `Δviews_24h` | `last_views − series 中 ts ≤ now−24h 的最近一点.v`；无该点（全部点都晚于 now−24h）→ 取首点并 `delta_credible=false`（span<20h 一律视为不可信，前端"—"沉底）。Δ7d/Δ30d 同构（锚点由 08:00 日界降采样保证存在） |
| `age_h` | now − published_at（小时，1 位小数） |
| 首发后 24h 表现 `views_first_24h` | 距 `published_at+24h` 最近的快照点 − 首个快照点；首点晚于发布+24h 时标 `first_point_late`（视频分析页消费，本期只落数不展示） |
| Shorts vs 长视频 | `is_short = duration_s ≤ 180`（YouTube 2024-10 起 Shorts 上限 3 分钟；历史 60s 上限期视频按时长口径近似，不回溯修正） |
| 日均增速 | `Δviews / Δt天`（所选窗两端点斜率），排序备选项，本期不出 UI |
| 订阅数 | 公开 API 整数化口径，**仅展示，禁用于净增计算** |
| 播放计数口径 | YouTube 2026-08-24 起"开始播放即计"：`yt_snapshots.caliber` 记录口径代次；口径再变时 bump，跨代次数据前端加"口径断点"提示，不做跨代斜率对比 |

## 6. 风险与边界（⑥）

1. **Quota**：默认 60min 节奏 ≈2,700/日；403 quotaExceeded 全局熔断保旧数据、退出码 3；计划任务日志（`data\yttrack_task.log`）留痕。加账号超 ~300 个或想提频到 30min 时需重新核算（UI 提示阈值）。
2. **冷启动无增速**：首日只有底库，Δ 全"—"；明确告知"第二天才有速度"（用户参考材料的原始结论，UI 文案同步）。
3. **口径变更**：2026-08-24 计数口径已切换，旧快照（如有外部导入）不可跨口径比斜率；caliber 字段是唯一防线。
4. **视频删除/转私享**：videos.list 缺行 → `status="unavailable"`，保留快照并在表格置灰，不参与排序头部。
5. **高频上传频道**：playlistItems 只取 1 页，单轮新增 >50 的极端频道会漏；缓解：报告输出 `playlist_overflow` 计数，后续版本按需加第 2 页。
6. **并发写**：serve 进程只读；采集单进程写 + 原子 replace；前端按钮与计划任务双跑由 5min 采集冷却挡住（`--force` 才穿透）。
7. **文件膨胀**：MAX_POINTS/MAX_VIDEOS/120d 清理三重闸；超 50MB（约 5000 视频满配）再评估分片（本期不做）。
8. **hot 端点性能**：全量读 snapshots JSON，~18MB 内可接受；预留 30s 进程内缓存位（对齐 stats.py invalidate 模式），本期不实现。
9. **ToS**：只走 Data API；缩略图用官方 i.ytimg.com 直链；无任何网页抓取/Playwright。
10. **网络/无 key 环境的定时任务**：所有失败收敛为报告行 + error 字段，绝不半写缓存；任务计划静默失败可通过日志与 `meta.last_collect_at` 陈旧度发现（热点页显示"最近采集 xx 前"，超 3h 变黄提示）。

## 7. 实施步骤清单（⑦，每步可独立验证）

| # | 步骤 | 触及文件 | 独立验证 |
|---|---|---|---|
| 1 | settings 增 `youtube` 段 + 打码回显 + 设置页输入框 | `server/config.py`、`web/js/pages/settings.js` | `GET /wb-api/settings` 出 `youtube.has_key/key_tail`；粘贴 key 落盘且回显打码；留空保存不丢 key |
| 2 | `yt_track.py` 骨架：`parse_channel_input` + `_prune` + 读写函数 | `server/yt_track.py`（新建） | `py -3.11 -c "from server.yt_track import parse_channel_input; …"` 对 6 种输入形态断言（离线零外呼） |
| 3 | cli 子命令 + 真跑一轮 | `cli.py` | 配 key 后 `py -3.11 cli.py workbench refresh-yt-track --force --json`：三个 yt_*.json 生成、报告行含 quota 估算、二次跑命中冷却 skip |
| 4 | 读端点：`/yt/hot`、`/yt/channels` | `server/app.py` | curl 校验 shape；`range/sort/kind/channel/q` 逐参数验证；null 沉底 |
| 5 | 写端点：channels POST/DELETE/enabled/import + `/yt/collect`（subprocess） | `server/app.py` | curl 增删改查 + 立即采集返回真实报告；import 能吃进旧清单 YouTube 行 |
| 6 | video.js 7 子页骨架 + prod 迁移 + 占位页 + index.html 版本号 | `web/js/pages/video.js`、`web/index.html` | 页面 7 项左菜单切换正常；原项目列表/mp4 播放行为与改造前一致；离开视频页左菜单清空 |
| 7 | 热点追踪页（表格/筛选/排序/立即采集/空态三分） | `video.js`、`css/app.css`（少量追加） | 无 key 引导卡→配置→采集→表格出数据；24h 窗按播放排序正确；Δ 列冷启动显"—" |
| 8 | 追踪账号页（增删/启停/导入/状态 pill） | `video.js` | 添加 pending→采集后变 ok；关闭开关后下一轮报告 accounts 数不含该频道；导入按钮去重生效；**track.js 主页面回归不受影响** |
| 9 | 计划任务脚本 | `bin/yttrack_task.bat`（新建） | `schtasks /run /tn aag-yttrack-refresh` 触发一轮，日志追加、`last_collect_at` 前进 |
| 10 | 文档 | `docs/第四板块-前端工作台方案.md` 追加"视频页·热点追踪"节 | 口径/配额/命令与实现一致 |

**预计变更文件**：新建 `workbench/server/yt_track.py`、`bin/yttrack_task.bat`；修改 `workbench/server/config.py`、`workbench/server/app.py`、`cli.py`、`workbench/web/js/pages/video.js`、`workbench/web/js/pages/settings.js`、`workbench/web/index.html`、`workbench/web/css/app.css`、`docs/第四板块-前端工作台方案.md`。**明确不动**：`js/pages/track.js`、`tracked_accounts.json` 结构、三板块任何文件（红线：workbench 对外只读，写口仅 `data/workbench/`）。

---

**实现提示**：x_surge.py 的四件套（分层冷却、prune 三重闸、CLI 单行 JSON 报告、熔断退出码）是本方案的直接模板，编码时应最大程度照抄其函数切分与命名风格；news.js 的 `registerSubs` + hash 前缀守卫 + `unmounted` 清理是 video.js 改造的模板。建议实施完成后交 grok 做一轮代码复审（重点：subprocess 超时路径、JSON 半写防护、quota 熔断分支）。
