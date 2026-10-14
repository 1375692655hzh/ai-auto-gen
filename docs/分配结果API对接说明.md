# 账号选题全量清单 API 对接说明（/v1/alloc）

> 版本：2026-10-14 ｜ 服务：数据站 `sources serve`（云端 8787 端口）
> **2026-10-14 改向（破坏性变更）**：经用户裁决，本 API **不再返回限量分配结果**（原
> 主推 main/备选 bench/quota/short/metrics 等字段全部下线），改为**直接返回该账号
> 窗口内的全量命中清单**——与飞书推送表格子页同口径，不做任何分配处理。
> 旧文档描述的"限量分配制"接口已废弃；已按旧口径开发的对接方需改读 `items` 数组。

---

## 一、能获取什么

每个 X 账号每个推送档位一份**全量命中清单**：窗口内命中最该账号成分（mix）的全部 X 帖，
逐条带主题、类型（观点/资讯）、金融价值分档（FV·P0~P3）、作者、中文译文、原文、链接、
发布时间、板块/ticker/事件类型。与飞书表格同一份内容，两侧对得上。

- **一帖一行**：表格中多主题帖会在多个主题段重复出现（行数略多），API 归入 mix 最高的
  命中主题、只出一行，`themes` 字段列出全部命中主题；
- **分发前质量闸（2026-10-14 起）**：纯链接帖/剥 URL 后正文不足 8 字的空帖、推广口令帖
  （订阅导流"需要的请扣"、免费工具、webinar、bStocks 合约推广）在进入清单**之前**已被
  公共闸过滤——doc 表格与 API 走同一道闸，两侧口径一致，对接方无需自行再滤此类垃圾；
- **排序**：主题段按账号成分占比降序 → 段内观点型在前 → 时间降序；
- **浏览量/增速不在返回里**：这两个是推送时刻现拉的实时数据，不入库，API 无法回放。

## 二、端点

### 1. 账号索引

```
GET /v1/alloc
```

返回所有账号与其最新档位（档=推送锚点，schedule 当前为 8/11/17 三档）：

```json
{"accounts": {"WCixot": {"latest_slot": "2026-10-14-17", "owner": "谢成"}, ...},
 "schedule": [8, 11, 17],
 "note": "详情: GET /v1/alloc/{账号名}?slot={档位,缺省最新; ...}"}
```

### 2. 账号全量清单

```
GET /v1/alloc/{账号名}                     → 该账号最新一档
GET /v1/alloc/{账号名}?slot=2026-10-14-8   → 指定档位
GET /v1/alloc/{账号名}?since=2026-10-14 18:00:00   → 增量模式(定时轮询拉新帖)
```

档位模式与增量模式**二选一**（同时传 `slot` 与 `since` 返回 400）。返回结构（节选，实机实测）：

```json
{
  "account": "WCixot",
  "owner": "谢成",
  "mix": {"美股": 60.0, "投教科普": 40.0},
  "slot": "2026-10-14-8",
  "window": {"since": "2026-10-13 17:00", "until": "2026-10-14 08:00"},
  "total": 223,
  "themes": [{"theme": "美股", "count": 223}],
  "items": [
    {
      "theme": "美股",            // 归属主题(mix 最高的命中主题)
      "themes": ["A股", "美股"],  // 全部命中主题
      "type": "观点",             // 观点/资讯(与表格判定同口径)
      "fv": "70·P1",             // 金融价值分·档位(P0≥75/P1≥60/P2≥40/P3)
      "url": "https://x.com/StockMKTNewz/status/...",
      "time": "2026-10-14 02:20",
      "fetched_at": "2026-10-14 07:59:00",  // 入库时间(数据站抓到它的时刻)
      "author": "StockMKTNewz",
      "text": "BREAKING: Williams says ...",
      "text_zh": "美联储威廉姆斯刚刚表示…",   // 译文缺失时为空串, 自行回退 text
      "sectors": "[\"金融与加密>宏观\"]",
      "markets": "[\"美国\"]",
      "tickers": "[]",
      "event_type": "macro",
      "item_type": "快讯",
      "positioning": "新闻源",
      "dup_count": 3              // 库内同源去重后的合并条数
    }
  ],
  "note": "全量命中清单, 与飞书表格同口径(...)"
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| items | 全量命中帖数组，顺序即推荐阅读序（主题段→观点→时间） |
| window | 取数窗口；档位模式=`[上一锚点, 本锚点)`（8 点档覆盖 overnight），增量模式=`[since, now)` |
| fetched_at | **入库时间**（数据站抓到该帖的时刻）；`time`=发帖时间。**增量/批次归属按 fetched_at 判，判重用 url**（相邻批次按发帖时间看会有少量交叠） |
| fv | 金融价值分·档位，排序/筛选建议直接用 P 档 |
| text_zh | 中文译文；空串=未翻译，展示时回退 text（与飞书表规则一致） |
| dup_count | 同源多帖已在库侧合并，>1 表示同源还有 N-1 条 |

### 3. 增量模式（定时轮询拉新帖）

```
GET /v1/alloc/{账号名}?since=<上次响应的 cursor>
```

- 窗口 = `[since, now)` 按 **fetched_at（入库时刻）** 切——"上次拉取之后新入库的帖"；
- 响应带 `mode: "incremental"` 和 `cursor`（= 本次窗口上界，服务器时钟）；
  **下次调用 `?since=<cursor>` 接续**；空结果 cursor 照样前进，不会卡住；
- `since` 接受 `YYYY-MM-DD HH:MM:SS` / `YYYY-MM-DD HH:MM` / `YYYY-MM-DD`（T 分隔亦可）；
  传未来时间返回 400（提示以响应 cursor 为准，别用客户端本地钟推算）；
- 轮询节奏随意（典型 15~30 分钟一次，对齐数据站 15min 抓取节奏最省）；
- 单窗口护栏 `LIMIT 400`（按发帖时间取最新 400 条），拉取间隔别超过一天；首启冷启动
  建议先用档位模式拿一档做基线，再切增量模式从该档锚点时刻起拉。

## 三、怎么配（鉴权与配额）

### 1. 请求鉴权

数据站全接口 Bearer Key 鉴权，两种写法等价：

```
Authorization: Bearer <你的key>
X-API-Key: <你的key>
```

### 2. 发 key（管理员操作，一次性）

key 配置在**云端** `global-news-sources/config/api_keys.local.json`（gitignored，绝不进仓库）：

```json
{
  "keys": [
    {"name": "对接方名称", "key": "ak_live_随机长串",
     "enabled": true, "rpm": 60, "daily_items": 200000, "daily_snapshot": 10}
  ]
}
```

- `name`：调用方标识（进访问日志，按方命名）；
- `rpm`：每分钟请求上限；
- `daily_items`：**每天可返回的条数**（alloc 按 items 条数计费。注意改向后单次返回从
  十几条变为**全量一两百条**，按 24 账号×3 档估算日耗约 1.5 万条，配额请据此评估）；
- `daily_snapshot`：快照类接口日限（alloc 不消耗此项）；
- 改完保存即生效（每请求重读，无需重启）。

### 3. 调用示例

```bash
# 索引
curl -H "Authorization: Bearer <key>" https://<数据站地址>/v1/alloc

# 英文账号名直接拼路径
curl -H "Authorization: Bearer <key>" https://<数据站地址>/v1/alloc/WCixot

# 指定档位(小时可不补零; 补零 "08" 也能识别, 返回会归一为 "-8")
curl -H "Authorization: Bearer <key>" \
  "https://<数据站地址>/v1/alloc/WCixot?slot=2026-10-14-8"

# 增量模式(定时轮询; since 用上次响应的 cursor, 空格需 URL 编码为 %20)
curl -H "Authorization: Bearer <key>" \
  "https://<数据站地址>/v1/alloc/WCixot?since=2026-10-14%2018:53:20"

# 中文账号名需 URL 编码(如 "花街 S 姐" → %E8%8A%B1%E8%A1%97%20S%20%E5%A7%90)
curl -H "Authorization: Bearer <key>" \
  "https://<数据站地址>/v1/alloc/%E8%8A%B1%E8%A1%97%20S%20%E5%A7%90"
```

错误码：`401`（key 无效/未带）；`400`（档位格式错/mix 无效/schedule 未配置）；
`404`（账号名不存在、档位不在 schedule、档位尚未到来——**不再静默回落到最新档**）；
`429`（触发 rpm 或日配额，带 Retry-After 头）。

## 四、对接注意事项

1. **档位（slot）命名**：`YYYY-MM-DD-H`，H 为推送锚点小时，**小时不补零**（与推送侧
   落档一致，如 `2026-10-14-8`）；查询传补零值会被归一。午夜锚点记 24。当天最早档的
   窗口从昨日最末锚点起算。
2. **拉取时机**：数据从库内现算（非快照），锚点整点后即可拉；窗口上界=锚点整点，之后
   新入库的帖不会混入本档。飞书表格的窗口起点是"上次推送完成时刻"（锚点后几分钟），
   与 API 的锚点整点在**边界分钟级**可能有少量出入。
3. **历史深度**：不设快照保留档数，可查库内留存范围内任意历史档（X 帖按留存策略约 7 天，
   更早档位会查到 0 条而非报错）。
4. **同帖判重**：直接用 `url`；同源多帖库侧已合并（`dup_count`）。
5. **与飞书表格对数**：API `total` ≤ 表格行数（表格多主题帖重复计数），内容集合一致。
6. **CORS**：已放行 GET（浏览器页面可直连，但仍需带 key——建议用后端代理转发，key 不落前端）。
7. **访问日志**：每次调用按 key 名记入 `data/serve/access.log`（路径/条数/耗时/状态码），排障找管理员。

## 五、相关

- 端点实现：`global-news-sources/sources/serve.py`（`/v1/alloc` 两端点 + 档位/窗口/增量游标辅助函数）
- 档位/窗口单测：`global-news-sources/tests/test_alloc_slots.py`
- 已废弃并**整体移除**（2026-10-14）的限量分配引擎：`sources/feishu_alloc.py` 及推送侧
  shadow/draft 接线已删（用户裁决"旧的没人在用"）；如需回溯方案定案过程见 git 历史
  （`data/tmp/moa_dedup_answers.md` / `moa_alloc_reviews.md` 为当时评审底稿）
- 数据站其他接口：`python cli.py sources serve --help`、`docs/云端部署方案.md`
