# global-news-sources — 板块一：金融信息源库 / 数据站

108 个金融信息源的注册表 + 抓取实现，覆盖 A股/港/美/日/韩/台/土耳其七地理市场 + 外汇/大宗 + 外围情绪/预测市场。

## 结构

```
sources/            注册表包(对外 API)
  base.py           @source 装饰器 + REGISTRY
  builtin.py        全部来源注册(包装 fetchers 函数)
  cache.py          磁盘缓存(TTL)
  health.py         健康检查(dead 自动跳过, 半开探针自动复活)
  refresh.py        数据站写侧: 到期源调度刷新(单实例锁+12min 墙钟预算)
  serve.py          数据站读侧: 只读 HTTP 供数(8787, Bearer Key)
  console.py        运维控制台(8786, 回环免密)
fetchers/           抓取实现
  basic.py          快讯/公告/行情/宏观 fetcher 主体(约 100 个)
  extra.py          同行早报/外围指数/事件日历/搜索富化
  search.py         豆包搜索 Custom 封装(feedcoopapi)
  yuanbao_fetch.py  腾讯元宝镜像(反爬源的 fallback, 浏览器登录态, 不进自动刷新环)
  _runtime.py       独立运行兜底(配置/密钥路径解析)
docs/               源清单.xlsx / 行情数据源清单.md / 供数服务.md / add-a-source.md 等
```

## 用法（完整仓库内）

```bash
python cli.py sources list             # 全部源 + 启用/健康
python cli.py sources fetch <id>       # 单源抓取(TTL 缓存)
python cli.py sources check            # 全源实抓体检
python cli.py sources refresh          # 数据站写侧: 跑一轮到期刷新
python cli.py sources serve            # 数据站读侧: 127.0.0.1:8787 Bearer 供数
python cli.py sources console          # 运维控制台: 127.0.0.1:8786
```

## 作为数据站独立部署（只下这一块，24/7 供数）

适用画像：只要"108 源采集 → SQLite → HTTP 供数 + 运维控制台"，不要生成/发布/工作台。

**下载**（sparse checkout，根目录的 `cli.py` 会自动带上）：

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/1375692655hzh/ai-auto-gen.git
cd ai-auto-gen
git sparse-checkout set global-news-sources bin
```

**安装与试跑**：

```bash
pip install -r global-news-sources/requirements.txt   # 含 serve/console 需要的 fastapi/uvicorn
python cli.py sources refresh --dry-run               # 看本轮计划(不抓)
python cli.py sources refresh                         # 实跑一轮(真抓外网)
python cli.py sources serve                           # 起供数(8787)
python cli.py sources console                         # 起控制台(8786, 浏览器打开看刷新轮/健康)
```

**无人值守（Windows 任务计划，全部经 silent_run.vbs 静默包装）**：

```bat
schtasks /create /tn "aag-sources-refresh" /tr "wscript.exe <项目路径>\bin\silent_run.vbs <项目路径>\bin\refresh_task.bat" /sc minute /mo 15 /f
schtasks /create /tn "aag-serve" /tr "wscript.exe <项目路径>\bin\silent_run.vbs <项目路径>\bin\serve_task.bat" /sc onlogon /f
schtasks /create /tn "aag-console" /tr "wscript.exe <项目路径>\bin\silent_run.vbs <项目路径>\bin\console_task.bat" /sc onlogon /f
schtasks /create /tn "aag-resident-watchdog" /tr "wscript.exe <项目路径>\bin\silent_run.vbs <项目路径>\bin\resident_watchdog.bat" /sc minute /mo 15 /f
```

笔记本必做（否则拔电全站静默停摆）：

```powershell
foreach ($n in "aag-sources-refresh","aag-serve","aag-console","aag-resident-watchdog") {
  $t = Get-ScheduledTask -TaskName $n
  $t.Settings.DisallowStartIfOnBatteries = $false   # 拔电也允许启动
  $t.Settings.StopIfGoingOnBatteries = $false       # 拔电不停正在跑的
  $t.Settings.StartWhenAvailable = $true            # 错过触发开机补跑
  Set-ScheduledTask -InputObject $t | Out-Null
}
```

**运维常识**：日志在 `data/refresh_task.log`（每轮有 `===== 轮开始/轮结束 rc=N =====` 分隔行，逐源心跳实时可见）；账本 `data/serve/refresh.json`（禁手编）；单实例锁 `data/serve/refresh.lock`（进程死亡自动释放，蓝屏后可手删）；无 LLM key 时 llm_tag/translate 自动跳过，采集供数不受影响。

**对外供数**：默认回环 127.0.0.1。局域网/云端对外时 `python cli.py sources serve --bind 0.0.0.0` + Bearer Key（Key 生成见 config/api_keys.example.json），禁裸公网。API 契约见 [docs/供数服务.md](docs/供数服务.md)。

## 当作库嵌入（不要数据站，只要抓取函数）

```python
import sys
sys.path.insert(0, "global-news-sources")
sys.path.insert(0, "global-news-sources/fetchers")
from sources import gather, fetch_one
items, failed = gather()                 # 所有启用快讯源, 去重按时间倒序
items, err = fetch_one("sina_7x24")      # 单源
```

- 依赖：`pip install requests pyyaml`
- enabled 开关：板块根放一份 `config.yaml`（只要 `sources:` 段，格式同 ai-workflow/generator/config.yaml）；完整仓库内自动读 `ai-workflow/generator/config.yaml`
- 备用源 key：同名大写环境变量，或板块根/发布仓 `autopub/`（兄弟仓 ai-auto-publisher，经 AAG_AUTOPUB_ROOT 解析）下的 `secret.local.json`
- 缓存与健康数据默认写到项目根 `data/`（完整仓库）；独立使用时写到上级目录的 `data/`（不存在则随代码层级落盘）

## 加新源

按 [docs/add-a-source.md](docs/add-a-source.md)：在 `fetchers/basic.py` 写 fetcher → 在 `sources/builtin.py` 注册 → `python cli.py sources check --id <新id>` 实抓验证。
