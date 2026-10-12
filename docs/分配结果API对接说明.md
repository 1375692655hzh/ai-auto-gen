# 账号选题分配结果 API 对接说明（/v1/alloc）

> 版本：2026-10-13 ｜ 服务：数据站 `sources serve`（云端 8787 端口）
> 用途：外部平台按账号获取"限量分配引擎"当轮分给该账号的选题内容（主推+备选），
> 字段与飞书推送表同源同口径——外部系统可以直接据此展示、审稿或自动发布。

---

## 一、能获取什么

每个 X 账号每个推送档位（每天 9/13/17/21/24 五档）有一份"分配结果"：

- **主推（main）**：本档分给该账号的选题，每条带分配说明（为什么给你）、主题、金融价值分档（FV·P0~P3）、作者、**中文译文**、原文、链接、发布时间、板块/ticker/事件类型；
- **备选（bench）**：命中该账号但主推名额已满的备胎（最多 10 条），可自选使用；
- **元信息**：配额（quota）、是否供给不足（short）、负责人（owner）、本档指标摘要（summary/metrics，含同类账号重合度）。

分配说明（note）的取值与含义：

| note | 含义 |
|---|---|
| 限量分配 | 竞争层按名额制分给你（K 限量内的正席） |
| 低竞争直通 / 命中直通 | 命中账号少（≤2）或你独占命中，无竞争直接给 |
| 持续跟进(已报道) | 该事件今天早档已分给你，新帖自动接续 |
| 公共大事件·建议角度:XX | 全网级大事全员覆盖，系统给各号分配了不同写作角度 |
| 尾部加印·同类号也可能看到 | 供给不足时用 P2/P3 长尾补量，不占竞争名额 |
| 备选转主推 | 你本轮主推为空，备选升级 |
| 极端兜底·同类号也会看到 | 竞争全落选时的保底行（≤3 条），同类号可能重复 |

## 二、端点

### 1. 账号索引

```
GET /v1/alloc
```

返回所有账号与其最新档位（用于发现账号列表）：

```json
{"accounts": {"sojanna": {"latest_slot": "2026-10-13-24"}, ...},
 "slots_kept": 50,
 "note": "详情: GET /v1/alloc/{账号名}?slot={档位,缺省最新}"}
```

### 2. 账号分配详情

```
GET /v1/alloc/{账号名}            → 该账号最新一档
GET /v1/alloc/{账号名}?slot=2026-10-13-24   → 指定历史档
```

返回结构（节选，实机实测）：

```json
{
  "account": "sojanna",
  "slot": "2026-10-13-24",
  "day": "2026-10-13",
  "quota": 18,              // 本档主推目标行数 = min(18, 命中供给)
  "short": true,            // true=供给不足没凑满配额(缺口已亮出)
  "owner": "兰蓝",          // 负责人
  "main": [
    {
      "key": "macro|GS",    // 事件键(event_type|主ticker)——同事件的判重依据
      "note": "限量分配",    // 分配说明(见上表)
      "rep_url": "https://x.com/zerohedge/status/2109654098794500218",
      "topics": ["美股"],   // 命中主题(9大类)
      "fv": "79·P0",        // 金融价值分·档位(P0≥75/P1≥60/P2≥40/P3)
      "time": "2026-10-12 22:35",
      "author": "zerohedge",
      "text": "Behind The Chip Curve: Goldman Admits ...",
      "text_zh": "落后于芯片曲线：高盛承认AI打乱了其通胀预测…",
      "sectors": "[\"金融与加密>券商\"]",
      "markets": "[\"美国\", \"全球\"]",
      "tickers": "[\"GS\"]",
      "event_type": "macro",
      "item_type": "快讯",
      "positioning": "新闻源"
    }
  ],
  "bench": [ ... ],          // 备选(结构同 main)
  "summary": {"accounts": 19, "events": 110, "mean_jaccard": 0.014, ...},
  "metrics": {"books": {"comp": {...}, "big": {...}, "tail": {...}}, ...}
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| main / bench | 主推/备选数组，顺序即推荐优先级 |
| key | 事件归并键：`event_type\|主ticker`（同事件多条帖共用一键；`u\|hash` = 无事件键的独立帖） |
| rep_url | 该账号分到的**具体帖子**链接（同一事件不同账号可能分到不同帖——同源不同报） |
| text_zh | 中文译文（缺失时回退原文，回退规则与飞书表一致） |
| fv | 金融价值分·档位，排序/筛选建议直接用 P 档 |
| summary.mean_jaccard | 本档同类账号主推重合度（质量指标，越低越不撞车） |

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
- `daily_items`：**每天可返回的条数**（alloc 接口按 主推+备选 条数计费）；
- `daily_snapshot`：快照类接口日限（alloc 不消耗此项）；
- 改完保存即生效（每请求重读，无需重启）。

### 3. 调用示例

```bash
# 索引
curl -H "Authorization: Bearer <key>" https://<数据站地址>/v1/alloc

# 英文账号名直接拼路径
curl -H "Authorization: Bearer <key>" https://<数据站地址>/v1/alloc/sojanna

# 中文账号名需 URL 编码(如 "花街 S 姐" → %E8%8A%B1%E8%A1%97%20S%20%E5%A7%90)
curl -H "Authorization: Bearer <key>" \
  "https://<数据站地址>/v1/alloc/%E8%8A%B1%E8%A1%97%20S%20%E5%A7%90?slot=2026-10-13-24"
```

错误码：`401 unauthorized`（key 无效/未带）；`429`（触发 rpm 或日配额，带 Retry-After 头）；`404`（账号名不存在或该档无分配）。

## 四、对接注意事项

1. **档位（slot）命名**：`YYYY-MM-DD-H`，H 为推送锚点小时（9/13/17/21/24）。每档在锚点后几分钟内生成；拉取时机建议在锚点后 10 分钟（等飞书推送与状态落盘完成）。
2. **历史深度**：快照保留最近 50 档（约 3~4 天），更早的档位会 404。
3. **当前为 shadow 模式（重要）**：分配引擎正在影子运行——**飞书推给运营者的仍是全量清单，本 API 返回的是"限量分配制会分的内容"**。切换 draft 模式后两者一致。对接方现在接入拿到的就是未来正式分配口径，切换无感知。
4. **同事件多帖**：`key` 相同代表同一事件；不同账号 `rep_url` 可能不同（分到的具体帖不同）。判重用 key，取内容用 rep_url。
5. **CORS**：已放行 GET（浏览器页面可直连，但仍需带 key——建议用后端代理转发，key 不落前端）。
6. **访问日志**：每次调用按 key 名记入 `data/serve/access.log`（路径/条数/耗时/状态码），排障找管理员。

## 五、相关

- 引擎与机制说明：`global-news-sources/sources/feishu_alloc.py` 模块 docstring
- 分配方案定案过程：`data/tmp/moa_dedup_answers.md`（五方方案）/ `moa_alloc_reviews.md`（代码复核）
- 数据站其他接口：`python cli.py sources serve --help`、`docs/云端部署方案.md`
