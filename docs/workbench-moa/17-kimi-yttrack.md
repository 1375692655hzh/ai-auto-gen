# 17-kimi-yttrack.md — 工作台视频页【热点追踪】MoA 独立答卷(kimi)

> MoA 同题并行 2026-09-05,任务同 16 号文件。本篇为 kimi 岗位(K2.7 Coding,经对照源码核验定稿)的独立答卷原文。

---

Kimi（K2.7 Coding）的独立答卷已收回且与我对全部源码的逐行核对基本吻合。我已修正其草稿中的几处不一致（详见文末"来源与修正说明"），下面给出定稿的完整实施方案。

---

# 工作台视频页改造实施方案：【热点追踪】YouTube 账号视频数据追踪 +【追踪账号】账号库（含 7 子页骨架）

> 范围：本期只实做【热点追踪】（追踪 YouTube 财经账号的视频数据，24h/7d 增量快照差分排序）与【追踪账号】（YouTube 账号库增删 + 启停），其余 5 个子页（视频分析/脚本生成/视频制作外壳/模板仓库/素材仓库）只搭骨架占位；现有"视频项目列表"原样归入【视频制作】子页。
> 红线对齐：对三板块全程只读；板块四唯一写口 `data/workbench/` 自有 JSON；采集外呼只发生在 CLI 进程，`app.py` 端点零外呼（照 `x_surge.py` 架构）；前端手动刷新经 subprocess 调 `cli.py`（红线 7 既有模式，同 `/wb-api/sources/{sid}/enabled`）；SPA 免构建、不引 npm；`track.js` 追踪主页面本期不动。

---

## ① 数据模型（全部落 `data/workbench/` 下 JSON，不引数据库）

三个新文件 + 原子写。列表形文件走 `config.load_rows()/save_rows()`（`workbench/server/config.py` 现成通用存取）；对象形文件在 `yt_track.py` 内自带 `tempfile.mkstemp + os.replace` 原子写（与 `x_surge._save_engage` 同款），损坏一律"当空库重来"（照 `load_engage` 的 try/except 兜底）。

### 1.1 追踪账号表 `data/workbench/yt_accounts.json`（行数组，主键 `channel_id`）

```json
{
  "platform": "YouTube",
  "account": "@TreasuryTracker",
  "channel_id": "UCxxxxxxxx",
  "handle": "@TreasuryTracker",
  "title": "频道名",
  "uploads_id": "UUxxxxxxxx",
  "subscribers": 1520000,
  "note": "宏观/美联储",
  "enabled": true,
  "added_at": "2026-09-05 18:06:07",
  "last_ok_at": "2026-09-05 18:00:00",
  "last_error": null
}
```

**输入解析 `parse_channel_input(raw) -> {kind, value}`**（`yt_track.py` 内纯函数）：

| 输入形态 | 识别 | 解析方式（配额） |
|---|---|---|
| `@handle`、`youtube.com/@handle`、裸 handle | `kind="handle"` | `channels.list?forHandle=@handle&part=id,snippet,contentDetails`（1 unit） |
| `youtube.com/channel/UC…`、裸 `UC…`（UC 开头 24 字符） | `kind="channel_id"` | 直接入库；元数据留到下一轮 `channels.list` 批量补 |
| `youtube.com/user/名` | `kind="username"` | 尝试 `channels.list?forUsername=`（1 unit），失败即报错 |
| `youtube.com/c/自定义名` | `kind="forbidden"` | 无法用 Data API 直解（`search.list` 100 unit 全程禁用），前端/CLI 直接拒绝，提示"请改用 @handle 或 /channel/UC… 链接" |

解析失败返回 400 `{"error": "无法识别的 YouTube 账号格式", "hint": "支持 @handle 或 youtube.com/channel/UC… 链接"}`。

### 1.2 视频现状表 `data/workbench/yt_videos.json`（对象，key=video_id）

```json
{
  "version": 1, "updated_at": "2026-09-05 18:00:00",
  "videos": {
    "dQw4w9WgXcQ": {
      "video_id": "dQw4w9WgXcQ",
      "channel_id": "UCxxxxxxxx",
      "title": "...", "thumb": "https://i.ytimg.com/vi/.../mqdefault.jpg",
      "published_at": "2026-09-03T12:00:00Z",
      "duration_s": 602, "is_short": false,
      "views": 120345, "likes": 3200, "comments": 180,
      "first_seen_ts": 1756893600.0,
      "first_seen_views": 154,
      "last_seen_ts": 1756976400.0
    }
  }
}
```

预留字段 `title_history`（本期不实装只存当前标题；后续要盯标题改动/A/B 再开，参照 yt-title-tracker 思路——官方 API 只回当前标题，历史必须自存）。

### 1.3 快照时序表 `data/workbench/yt_snapshots.json`（对象，key=video_id）

```json
{
  "version": 1, "updated_at": "2026-09-05 18:00:00",
  "view_policy_since": "2026-08-24",
  "quota_date": "2026-09-05", "quota_used_today": 27,
  "videos": {
    "dQw4w9WgXcQ": {
      "channel_id": "UCxxxxxxxx",
      "series": [ {"ts": 1756893600.0, "views": 154, "likes": 12, "comments": 1} ]
    }
  }
}
```

**体积控制三重封顶（照抄 `x_surge` 机制）**：`RETAIN_H = 192`（series 只留 8 天，覆盖 Δ7d 口径）、`MAX_POINTS = 400`（30min 节奏 × 8 天 ≈ 384 点，恰好容纳）、`MAX_VIDEOS = 3000` 硬顶（按 `series[-1].ts` 最旧淘汰）。视频行独立保留 `VIDEO_RETAIN_DAYS = 45`（series 过期不删视频行，只剪序列——保住长窗口复盘素材）。预估稳态体积 < 3MB。

### 1.4 与现有 `tracked_accounts.json` 的共存/迁移策略

- **物理隔离，互不读写**：`tracked_accounts.json` 是追踪主页面（track.js）的"发布渠道/竞品总清单"（平台混杂、无 channel_id、按位置下标删除）；`yt_accounts.json` 是采集配置（仅 YouTube、带 channel_id/uploads_id/enabled）。本期**不动 track.js 与 `/wb-api/track/accounts`**。
- 不采用"视频页添加时双写回 tracked_accounts.json"——两页行结构不同构（track 主页 `POST /wb-api/track/accounts` 追加的行没有 id/enabled/channel_id），双写必然漂移。
- 迁移**不自动做**，提供一次性 CLI：`python cli.py workbench import-yt-accounts`——读 `config.load_accounts()` 中 `platform == "YouTube"` 的行，逐行 `parse_channel_input` + API 解析成 channel_id 后写入 `yt_accounts.json`（已存在 channel_id 跳过；无法解析的行打印清单留人工处理），**原 `tracked_accounts.json` 不删不改**，用户在追踪主页自行清理。
- 前端追踪账号子页空态提示该命令，不做隐式联动。

---

## ② 采集器：新建 `workbench/server/yt_track.py`

架构照 `x_surge.py`：**外呼只发生在 CLI 进程（`collect()`）；`build_view()` 纯读缓存零外呼（app.py 端点用）**。全部用标准库 `urllib.request`（项目现况无 google-api-python-client 依赖，Data API v3 是纯 REST GET，不引 SDK）。

### 2.1 配额账（免费额度 10,000 unit/天/项目，太平洋时间 0 点重置）

| 调用 | 单次成本 | 每轮次数 | 说明 |
|---|---|---|---|
| `channels.list`（逗号批量 id，≤50/批） | 1 | 1 | 刷 title/handle/uploads_id/subscribers |
| `playlistItems.list`（uploads 播放列表，1 页/账号，maxResults=15） | 1 | N | N=启用账号数；只取最新 15 条即可覆盖 24h/7d 窗口 |
| `videos.list`（50 id/批，`part=snippet,statistics,contentDetails`） | 1 | ⌈M/50⌉ | M=本轮需刷新的视频数（新发现 + 窗口内全量） |
| `search.list` | 100 | **0（全程禁用）** | 频道发现只经 uploads 播放列表 |

- N=20、窗口内约 200 视频 → 每轮 1+20+4 = **25 unit**；每 30min 一轮 × 48 轮 ≈ **1200/天 ≈ 12%**。
- N=50、约 500 视频 → 61/轮 → 2928/天 ≈ 29%，仍安全。15min 加密节奏（N=20）2400/天 ≈ 24%。
- 追加账号时的 `forHandle` 解析 1 unit/次，忽略不计。
- 报告字段 `quota_used_today` 为**自估记量**（按上表累加），meta 中注明非官方余量。

### 2.2 一轮流程 `collect(force=False, take=15)`

1. `cfg = config.load().get("youtube") or {}`；无 `api_key` → 打印 `{"skipped": "youtube.api_key 未配置"}`，**exit 0**（计划任务日志安静，绝不外呼）。
2. 读 `yt_accounts.json`，取 `enabled` 且 `channel_id` 非空的行。
3. 冷却：`last_ok_at` 距今 <30min 的账号跳过（`--force` 越过），防手刷与计划任务重叠。
4. `channels.list?id=UC,…&part=snippet,contentDetails,statistics` 批量刷新账号行（含 subscribers）；404 → 该行 `last_error="deleted"` 并跳过，单账号失败不炸轮（对齐 `_fetch_one` 语义）。
5. 每账号 `playlistItems.list?playlistId=UU…&part=contentDetails&maxResults=15` 收集 video_id（近期视频 >50 的搬运号只在 `--force` 深度轮翻第 2 页）。
6. 全部 id 去重后按 50/批 `videos.list?part=snippet,statistics,contentDetails`：解析 `viewCount/likeCount/commentCount`（累计值）、`duration`（ISO8601 `PT#H#M#S` 转秒）、`publishedAt`。
7. 合并写盘：新视频初始化 `first_seen_ts/first_seen_views`；老视频**每轮追加快照点** `{ts, views, likes, comments}`（`videos.list` 是批量计费，窗口内全量刷不加重成本）；`_prune()` 后原子写两个文件。
8. `viewCount` 归 0 但历史 >1000 → 视为转私密/下架：保留行、标 `last_error`、不追点。
9. 打印 JSON 报告：`{"accounts": N, "channels_ok": n, "videos_seen": n, "new_videos": n, "points_added": n, "quota_used_today": n, "circuit_break": false}`（stdout 末行 JSON，与 `x_surge.collect` 同风格）。
10. 403 `quotaExceeded` → `circuit_break=True`，保留旧快照直接返回，CLI 返回 exit 3（对齐 x_surge 熔断语义）。

### 2.3 API key 存放（照 settings.json 服务端存放 + 打码回显模式）

`workbench/server/config.py` 改三处：

```python
DEFAULTS = {
    ...,
    "youtube": {                    # YouTube 热点追踪(Data API v3)
        "api_key": "",              # 仅存服务端, 永不明文回显
    },
}
```

- `public_view()`：照 `translate` 节三行模式加 `v["youtube"]["api_key"]="" / has_key / key_tail`（尾 4 位）。
- `apply_patch()`：`for sec in ("source", "translate")` 元组扩为 `("source", "translate", "youtube")`（"留空 = 保持不变"语义自动复用）。
- 文件尾新增 `load_yt_accounts()/save_yt_accounts()`（`load_rows("yt_accounts.json")` 薄封装，与 `load_accounts` 完全同款）。

### 2.4 无 key 降级表现（三层）

| 层 | 表现 |
|---|---|
| CLI 采集 | `{"skipped": "youtube.api_key 未配置"}`，exit 0，零外呼 |
| `POST /wb-api/yt/accounts`（解析需 API） | 503 `{"error": "未配置 YouTube API Key", "hint": "到 设置 → YouTube 热点追踪 填入"}` |
| 热点页 | 缓存有数据照常展示，`meta.has_key=false` → 页顶 notice 引导设置页；全新无缓存则整卡引导 |

### 2.5 增量调度挂载

**cli.py**：`workbench` 子命令组新增两个（argparse 注册照 `refresh-x-surge`，`workbench_cmd()` 加分支）：

```python
if args.sub == "refresh-yt-track":
    sys.path.insert(0, str(WB))
    from server import yt_track
    rep = yt_track.collect(force=args.force, take=args.take)
    return 0 if not rep.get("circuit_break") else 3
if args.sub == "import-yt-accounts":          # 一次性迁移, 见①.4
    ...
```

参数：`--force`（忽略冷却）、`--take`（覆盖每账号条数，默认 15）。

**bin/yt_task.bat**（新建，照抄 `xsurge_task.bat` 模式）：

```bat
@echo off
rem aag YouTube热点追踪采集·任务计划专用(相对路径自适应; 日志落盘 data\yt_task.log)
rem 登记: schtasks /create /tn "aag-yt-track" /tr "<项目路径>\bin\yt_task.bat" /sc minute /mo 30 /f
set PYTHONUTF8=1
cd /d "%~dp0.."
if not exist data mkdir data
where py >nul 2>nul && (py -3.11 cli.py workbench refresh-yt-track >> data\yt_task.log 2>&1) || (python cli.py workbench refresh-yt-track >> data\yt_task.log 2>&1)
```

默认 30min 节奏（与 sources refresh 计划任务同频），配额余量见 ②.1。机器关机即停采，无补采逻辑（YouTube 累计值本身可回溯，只是缺中间点，见⑥.2）。

---

## ③ 后端 API 新端点清单（注册在 `app.py create_app()` 内，风格对齐现有端点）

| 方法 | 路径 | 参数 / 请求体 | 返回 shape | 说明 |
|---|---|---|---|---|
| GET | `/wb-api/yt/hot` | `window`="24h"(默认)/"48h"/"7d"/"30d"；`channel`=channel_id（空=全部）；`kind`="all"/"short"/"long"；`sort`="delta"(默认)/"views"/"vph"/"published"；`limit`=100 | `{"items": [...], "total": n, "meta": {...}}` | **纯读缓存零外呼**，同 `/wb-api/x-surge` 结构；发布窗口=window，排序键=sort |
| GET | `/wb-api/yt/status` | — | `{"has_key": bool, "accounts": {"total": n, "enabled": n}, "videos_tracked": n, "points": n, "quota_used_today": n, "last_round_at": "...", "data_age_min": n\|null, "last_error": ...}` | 页顶状态条 |
| GET | `/wb-api/yt/accounts` | — | `{"accounts": [yt_accounts.json 全量]}` | |
| POST | `/wb-api/yt/accounts` | `{"input": "@handle 或链接", "note": ""}` | `{"accounts": [保存后全量]}`；400 格式错；409 `{"error": "该频道已在追踪"}`；503 无 key | 服务端解析补全 channel_id/handle/title/uploads_id |
| POST | `/wb-api/yt/accounts/{channel_id}/enabled` | `{"on": bool}` | `{"channel_id": "...", "enabled": bool, "accounts": [...]}` | 启停不删快照；动词对齐现有 `POST /wb-api/sources/{sid}/enabled` |
| DELETE | `/wb-api/yt/accounts/{channel_id}` | — | `{"accounts": [...]}` | 越界静默（照 `track_del`）；删账号不删其历史快照（下轮 prune 自然收敛） |
| POST | `/wb-api/yt/refresh` | — | 成功返回 ②.2 第 9 步的采集报告 JSON；超时 504 `{"error": "cli 调用超时"}` | **照 `/wb-api/sources/{sid}/enabled` 的 subprocess 模式**：`subprocess.run(["py","-3.11",str(cli),"workbench","refresh-yt-track","--json"], capture_output=True, text=True, encoding="utf-8", timeout=180)`；N≤50 时典型耗时 10–30s，同步等待可接受 |

**与 `/wb-api/track/accounts` 的关系**：并列独立，两套端点各管各的文件，互不读写。路径键用 `channel_id` 而非位置下标 `idx`（追踪主页用 idx 是因为其行没有稳定 id；yt 行有主键，用资源键可避免两次刷新间列表重排导致的误删/误停——参考页内已有 `/wb-api/sources/{sid}/enabled` 的资源键风格）。

**`/wb-api/yt/hot` 的 item shape**（`build_view(window_h, channel, kind, sort, limit)` 产出）：

```python
{
  "video_id": "...", "channel_id": "...", "channel_title": "...", "handle": "@...",
  "title": "...", "thumb": "...",
  "url": "https://www.youtube.com/watch?v=...",
  "published_at": "2026-09-03T12:00:00Z", "age_h": 30.2,
  "duration_s": 602, "is_short": False,
  "views": 120345, "likes": 3200, "comments": 180,       # 累计值
  "delta_24h": 4521,           # None=算不出
  "delta_24h_basis": "snapshot" | "first_seen" | None,   # 口径来源(前端标 *)
  "delta_7d": None,
  "vph": 188.0,                # 近两快照点折时增速
  "views_first_24h": None,     # 发布后24h表现
  "avg_daily": 387.0,
  "first_seen_views": 154,
  "has_series": True,          # 冷启动无快照 False → 前端"采集中"badge
}
```

`meta = {"updated_at", "data_age_min", "window", "sort", "kind", "channel", "videos_tracked", "accounts_enabled", "has_key", "quota_used_today", "shorts_n": n, "long_n": n, "rule": "Δviews=本地快照差分; None 一律沉底; 新视频带*为首见基线; 口径2026-08-24起播放=开始播放即计"}`——`data_age_min` 计算照抄 `x_surge.build_view` 对 `eng["updated_at"]` 的解析段。

---

## ④ 前端：`workbench/web/js/pages/video.js` 七子页改造

### 4.1 结构（对齐 news.js 的"setSubs 注册 + 页内 tab + v-show + unmounted 清菜单"模式）

```js
WB.pages.video = {
  data() {
    return {
      tab: "hot",   // hot|analysis|script|make|templates|materials|yt-accounts
      /* 热点追踪子页 */
      hotItems: [], hotMeta: null, hotTotal: 0, hotLoading: false, hotErr: null, refreshing: false,
      f: { window: "24h", channel: "", kind: "all", sort: "delta" },
      /* 追踪账号子页 */
      ytAccounts: [], yForm: { input: "", note: "" }, showYForm: false, busyId: "",
      /* 视频制作子页 = 现有项目列表原样迁入 */
      videos: [], sel: null, error: null,
    };
  },
  mounted()  { this.registerSubs(); this.loadYtAccounts(); this.loadHot(); /* 原项目列表加载 */ },
  unmounted() { if (WB.shell) WB.shell.setSubs([]); },
  methods: {
    registerSubs() {
      if (!location.hash.replace(/^#/, "").startsWith("/video")) return;  // 防迟到回调覆盖别页(news.js 同款)
      WB.shell.setSubs([
        { id: "hot",        title: "热点追踪", cnt: this.hotTotal || "" },
        { id: "analysis",   title: "视频分析" },
        { id: "script",     title: "脚本生成" },
        { id: "make",       title: "视频制作", cnt: this.videos.length || "" },
        { id: "templates",  title: "模板仓库" },
        { id: "materials",  title: "素材仓库" },
        { id: "yt-accounts",title: "追踪账号", cnt: this.ytAccounts.length || "" },
      ], this.tab);
    },
    async loadHot()    { /* GET /yt/hot?... 后 registerSubs() 刷 cnt */ },
    async refreshHot() { /* POST /yt/refresh → 成功 toast + loadHot(); refreshing 态防重点 */ },
    async addYt()      { /* POST /yt/accounts {input, note} */ },
    async toggleYt(a)  { /* POST /yt/accounts/{a.channel_id}/enabled {on: !a.enabled} */ },
    async removeYt(a)  { /* DELETE /yt/accounts/{a.channel_id} */ },
    /* 原项目列表 methods(gateClass/gateText)原样保留 */
  },
};
```

模板 = 7 个 `<div v-show="tab==='…'">` 块。**现有项目列表模板（`two-col` + `list-item` + `<video>` 预览 + 桩按钮）原封不动移入 `tab==='make'` 块**，data/computed/methods 原样保留。5 个占位子页统一桩样式（现有 `stub-wrap/stub-tip`）：一张 card + disabled 按钮 + 提示文案（素材仓库注明"视频素材管理，后续开放"，与图文页素材篮无关）。

### 4.2 热点追踪子页主视角

- **工具行**：窗口 `select`（近24h/48h/7d/30d，`f.window` @change loadHot）｜账号 `select`（全部 + 各启用频道，值=channel_id）｜类型 chips（全部/长视频/Shorts，`f.kind`）｜排序 `select`（播放量增速 Δ24h/总播放/时增速/发布时间）｜**刷新按钮** `btn primary`（`refreshHot()`，`:disabled="refreshing"`，转动文案"采集中…约 30 秒"）。
- **状态条**（读 `hotMeta`）：`数据更新于 xx（n 分钟前）· 追踪 n 账号（启用 m）· 库内 v 视频 · 今日配额约 q`；`data_age_min > 90` 追加黄字"采集器未运行？检查计划任务 aag-yt-track"。
- **主表** `<table class="tbl">`：缩略图(60px)｜标题（新开 `url`）｜频道｜类型 badge（Shorts 用 `badge yellow`）｜时长 `mm:ss`｜发布时间｜总播放｜**Δ24h（主排序列，表头标 ↑，basis=first_seen 的值带 `*`）**｜Δ7d｜vph｜发布后24h。数字格式化抽本地 `fmtNum`（news.js 的万单位写法：`>=1e4 → (n/1e4).toFixed(1).replace(/\.0$/,"")+" 万"`）。
- **空态/降级三则**：无 key → 页顶 notice + 设置页引导；无账号 → 整卡引导"到【追踪账号】添加，或运行 `python cli.py workbench import-yt-accounts`"；冷启动 → "已加入追踪，30 分钟一轮，约 2 个快照点后出增速"。错误态复用 `err-box`（同 news.js）。

### 4.3 追踪账号子页

- 卡1「YouTube 追踪账号(N)」：＋添加表单（一个输入框接受 @handle 或 /channel/UC… 链接 + 备注，样式对齐 track.js 表单行）→ `POST /yt/accounts`；成功 toast 显示解析出的频道名。
- 账号卡列表复用 track.js 的 `acct-grid/acct-card` 类：频道名 + handle + channel_id（`mono`）+ 备注 + subscribers（"约"，可空）+ `added_at` + **启停 switch**——直接复用 news.js 来源详情的 switch 标记：

```html
<span class="switch" :class="{on: a.enabled !== false, busy: busyId === a.channel_id}"
      role="switch" tabindex="0" @click="toggleYt(a)" @keydown.enter="toggleYt(a)"></span>
```

  删除沿用 track.js 的删除链接写法（`WB.api.del("/yt/accounts/" + a.channel_id)`）。
- 卡2「来自追踪页的清单」：只读说明卡——追踪主页面的总清单（`tracked_accounts.json`）本期不联动，如其中录有 YouTube 账号可运行 `python cli.py workbench import-yt-accounts` 一次性导入。

### 4.4 其它文件触点

- **`workbench/web/js/pages/settings.js`**：data 默认加 `youtube: { api_key: "" }` 与 `yHasKey/yKeyTail`；`load()` 取 `(d.youtube || {})` 防旧服务端 undefined；`save()` 的 put body 增 `youtube: { api_key: this.s.youtube.api_key }`，成功后输入框置空并回写 hasKey/keyTail；模板照"翻译模型"卡加一张「YouTube 热点追踪」卡（password 输入框，placeholder=`已配置(尾号 xxxx), 留空保持不变`，注"Data API v3 Key，aigoogleapis.console 申请"）。
- **`workbench/web/index.html`**：六个 script 标签版本号统一 bump（现 `?v=0908b` → `?v=0909a`），沿用现有缓存击穿做法；video.js 保持单文件（改造后约 500–600 行，与 news.js 661 行同量级），不新增 script 标签。

---

## ⑤ 派生指标口径（全部在 `yt_track.build_view()` 计算，公式写进 `meta.rule`）

设快照序列 `series`（按 `ts` 升序），`now`，`pub_ts` = published_at 解析的 epoch，`views_now` = 最新点播放：

| 指标 | 公式 | 边界 |
|---|---|---|
| **Δviews_24h** | 锚点 `p0` = series 中 `ts ≤ now-24h` 的最后一点（最近邻回溯）；若 `p0` 存在且距 now ≤ 30h（span ≥ 18h，容忍采集抖动）→ `views_now - p0.views`，basis="snapshot"；否则若 `pub_ts ≥ now-24h`（24h 内新发）→ `views_now - first_seen_views`，basis="first_seen"（**严格偏小**，前端标 `*`）；否则 None | None 沉底 |
| **Δviews_7d** | 同法，锚点 `now-7d`，容忍 ±1d；新发（7d 内）回退 first_seen 基线；否则 None | |
| **vph（时增速）** | 最近两点 span ≥ 30min → `(v2 - v1) / span_h`（x_surge growth 同思想，防抖阈值 30min） | 点数 <2 → None |
| **发布后 24h 表现 `views_first_24h`** | 仅当 `now - pub_ts ≥ 24h` 且 `first_seen_ts ≤ pub_ts + 2h`：取 series 中 `ts ≥ pub_ts+24h` 的最早点 `p24` → `p24.views - first_seen_views` | 发布后超 2h 才入库 → None（"晚入库，不可比"），**不做外推**；未满 24h → None（"观察中"） |
| **日均增速 `avg_daily`** | 优先 `delta_7d / 7`；否则 `views / max(age_d, 0.5)`（新视频首日不除爆） | 两路都不可算 → None |
| **Shorts 判别 `is_short`** | `duration_s ≤ 60` → Shorts；`60 < duration_s ≤ 180` 且（标题含 `#shorts` 不分大小写 或 tags 含 "shorts"）→ Shorts（2024-10 起 Shorts 上限 3 分钟，API 无原生 is_shorts 字段，此为工程判别）；否则长视频 | |
| **排序** | 键 `(sort值 if not None else -1, views)` 降序——**None 一律沉底，平分按 views 降序**（照抄 x_surge `sort_key`） | |
| **负增长** | YouTube 偶尔回收播放量，`delta < 0` 原值展示（前端标 ↓）不截断，避免假象 | |

窗口内 Shorts/长视频计数 `shorts_n/long_n` 进 meta（本期只给汇总数；分账号对比、vph 中位数等留给未来【视频分析】子页）。

---

## ⑥ 风险与边界

1. **配额用尽**：403 `quotaExceeded` → 本轮熔断（`circuit_break=True`，exit 3），旧快照原样保留；`build_view` 照常出图，meta 带 `quota_used_today`；前端刷新失败 toast "YouTube 当日配额已用尽（太平洋时间 0 点重置）"。额度核算见 ②.1（N=20 约 12%/天），`--take` 调大时报告给 `quota_left_est` 预警。`quota_used_today` 是自估记量非官方余量，meta 注明。
2. **快照冷启动无增速**：新账号/新视频首两轮无 series 或仅 1 点 → 所有 Δ 为 None 沉底，按发布时间/总播放排序兜底；前端"采集中"badge + 空态文案。新视频用 first_seen 基线兜底（带 `*` 说明偏小）。**不做跨频道类比预估**。停机数天无补采——累计值仍可回溯，只是缺中间点，Δ7d 类长窗口指标自愈，Δ24h 在停机 >24h 后对老视频短暂不可算（沉底）。
3. **播放口径变更（2026-08-24 起"开始播放即计"）**：本库快照全部始于新口径之后，**内部自洽**；但与变更前的外部数据/竞品工具历史斜率不可比。处理：`yt_snapshots.json` 顶层记 `view_policy_since`，`meta.rule` 固定口径文案，**不尝试归一化**（无官方换算系数）。
4. **订阅数取整/隐藏**：`subscriberCount` 为 3 位有效数字取整且可被频道主隐藏 → 前端统一前缀"约"，排序与派生指标一律不依赖它；订阅数公开接口取整，不能当精确净增（与 grok 参考一致）。
5. **空库表现分层**：无账号 / 有账号无快照 / 无 key 三种空态各有明确引导文案（见 ④.2），任何情况下页面可渲染、接口不 5xx（`build_view` 零外呼纯读缓存）。
6. **JSON 单文件体积**：三重封顶（`RETAIN_H=192` / `MAX_POINTS=400` / `MAX_VIDEOS=3000`）+ 视频行 45d 保留 + 每轮落盘前 `_prune()` + 原子写防半写 + 损坏当空库重来；稳态 < 3MB。
7. **下架/转私密**：条目缺失或 viewCount 异常归零 → 保留历史行不追点（`last_error` 标记），已有快照仍可算历史 Δ；连续 7 天 `last_seen_ts` 未更新的行 prune 淘汰。
8. **ToS**：只走官方 Data API v3，不上 Playwright 爬网页（采纳 grok 参考建议）；`search.list` 全程禁用既是配额考虑也是最小权限。

---

## ⑦ 实施步骤清单（每步可独立验证）

1. **config.py：youtube 节 + yt_accounts 存取**
   改 `DEFAULTS`/`public_view()`/`apply_patch()`，尾加 `load_yt_accounts/save_yt_accounts`。
   验证：`py -3.11 -c "import sys; sys.path.insert(0,'workbench'); from server import config; print(config.public_view(config.load())['youtube'])"` → `{'api_key':'','has_key':False,'key_tail':''}`；起服务后 `curl -s http://127.0.0.1:8788/wb-api/settings` 确认无明文回显；`PUT /wb-api/settings` 写入 key 后 `GET` 仍只回尾号。
2. **新建 `workbench/server/yt_track.py`**：`parse_channel_input` / `resolve_channel` / 三文件 load+原子 save / `_prune` / `collect` / `build_view` / `status_payload`。
   验证（无 key 降级）：`py -3.11 -c "import sys; sys.path.insert(0,'workbench'); from server import yt_track; print(yt_track.collect()); print(yt_track.build_view())"` → skipped 报告 + `{"items":[],"total":0,"meta":{...}}`，全程零网络请求；`parse_channel_input` 各形态单测（裸跑 python -c 逐个喂）。
3. **cli.py：`refresh-yt-track` + `import-yt-accounts` 子命令；新建 `bin/yt_task.bat`**
   验证：`py -3.11 cli.py workbench refresh-yt-track` → skipped 报告 exit 0；在设置页配 key 后再跑 → 报告 `videos_seen>0`、`data/workbench/yt_accounts.json|yt_videos.json|yt_snapshots.json` 生成且第二轮 series 增点；`schtasks /create /tn "aag-yt-track" /tr "E:\ai-gen-article-publish\bin\yt_task.bat" /sc minute /mo 30 /f` 后 `schtasks /query /tn "aag-yt-track"`、`schtasks /run /tn "aag-yt-track"` 确认日志落 `data/yt_task.log`。
4. **app.py：注册 7 个端点**（③ 表）
   验证（服务起后）：`curl -s "http://127.0.0.1:8788/wb-api/yt/status"`；`curl -s "http://127.0.0.1:8788/wb-api/yt/hot?window=7d&sort=views"` → items/meta shape；`curl -s -X POST http://127.0.0.1:8788/wb-api/yt/accounts -H "Content-Type: application/json" -d "{\"input\":\"@BloombergTV\",\"note\":\"测试\"}"` → 行含 channel_id；`curl -s -X POST .../yt/accounts/UC.../enabled -d "{\"on\":false}"` → enabled=false 且下一轮采集跳过；`curl -s -X POST .../yt/refresh` → 采集报告（≤180s）。
5. **前端：video.js 七子页重构**（`make` 子页迁入旧模板，功能无损）
   验证：浏览器开 `http://127.0.0.1:8788/#/video`——左侧 7 个子菜单；逐个点击 v-show 切换无闪烁；`#/video` → `#/news` → 回 `#/video` 左菜单重新注册（unmounted 清空生效）；【视频制作】项目列表/播放与改造前一致（回归点）。
6. **前端：热点页 + 追踪账号页实装；settings.js 加 YouTube Key 卡；index.html 版本号 bump**
   验证：F12 Network 核对 `/yt/hot` querystring 随筛选联动；设置页填 key 保存 → 输入框清空、placeholder 变"已配置(尾号 xxxx)"、`GET /settings` 无明文；追踪账号页添加/启停/删除各一次，`yt_accounts.json` 行级核对。
7. **端到端冒烟**
   `python cli.py workbench import-yt-accounts`（若追踪页有 YouTube 存量）→ 等 2 个快照周期（约 1h）→ 热点页出现 Δ24h 排序（None 沉底、`*` 基线标注、Shorts badge 正确）→ 禁用一个账号后下一轮报告 `channels_ok` 减 1。
8. **回归**
   `python cli.py workbench status --json` 正常；`#/track` 追踪主页增删账号仍落 `tracked_accounts.json` 且功能无损；`python cli.py doctor` 无新增异常；确认 git status 未出现 `data/` 变更（三个 yt_*.json 均在 gitignore 覆盖内）。

---

## 附：来源与修正说明

本方案主体由 Kimi（K2.7 Coding，会话可续：`kimi -r session_3282f103-9ec2-4359-bcd4-6b083cf4d6e1`）独立起草，经我对照以下源码逐项核验后定稿：`workbench/server/app.py`（端点/subprocess 模式）、`config.py`（DEFAULTS/public_view/apply_patch/load_rows）、`views.py`、`x_surge.py`（缓存/冷却/build_view/prune 全套参照）、`proxy.py`、`workbench/web/js/{app,api}.js`、`js/pages/{video,news,track,settings}.js`、`cli.py:378-422,624-645`、`bin/xsurge_task.bat`、`data/workbench/` 现存文件。对 Kimi 草稿的修正点（定稿已含）：

1. 无 key 时 collect 的退出码两处矛盾（exit 4 vs exit 0）→ 统一 **exit 0**（计划任务日志安静；配置缺失语义留给 doctor）。
2. 启停/删除路径键 `{idx}` → 改 **`{channel_id}`**（yt 行有稳定主键，避免位置竞态；`/wb-api/track/accounts` 的 idx 模式保留不动）；enabled 动词 PUT → **POST**（对齐现有 `/wb-api/sources/{sid}/enabled`）。
3. Shorts 判别补 **2024-10 起 3 分钟档**（Kimi 只写了 ≤60s + #Shorts）。
4. 快照保留与视频行保留**解耦**（Kimi 把 series 清空的视频同步剔除，会伤 Δ7d 长窗口复盘）→ series 剪 8 天、视频行留 45 天。
5. `/yt/hot` 窗口参数命名 `window` 并原生支持 h/d 双单位（避开 app.py x-surge 端点 `range.rstrip("h")` 解析的局限）。
6. 账号行补 `subscribers` 字段（Kimi 流程里写回但行结构漏列）。
7. 手动刷新 subprocess 超时 300s → **180s**（N≤50 典型 10–30s，180s 已含重试余量）。

grok 参考意见的采纳情况：三种合法做法中取 Data API v3 + 定时快照差分（本机无自己频道诉求，Analytics API 不做）；开源项目仅作思路参照不引依赖；"能走 Data API 就不上 Playwright"写入红线；播放口径 2026-08-24 变更、订阅数取整、标题 A/B 自存三条注意全部落入 ⑥ 与 ①.2。
