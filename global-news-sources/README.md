# global-news-sources — 板块一：金融信息源库

107 个金融信息源的注册表 + 抓取实现，覆盖 A股/港/美/日/韩/台/土耳其七地理市场 + 外汇/大宗 + 外围情绪/预测市场。

## 结构

```
sources/            注册表包(对外 API)
  base.py           @source 装饰器 + REGISTRY
  builtin.py        全部来源注册(包装 fetchers 函数)
  cache.py          磁盘缓存(TTL)
  health.py         健康检查(dead 自动跳过)
  __init__.py       gather/gather_refs/fetch_one/list_sources
fetchers/           抓取实现
  basic.py          快讯/公告/行情/宏观 fetcher 主体(约 100 个)
  extra.py          同行早报/外围指数/事件日历/搜索富化
  search.py         豆包搜索 Custom 封装(feedcoopapi)
  yuanbao_fetch.py  腾讯元宝镜像(反爬源的 fallback)
  _runtime.py       独立运行兜底(配置/密钥路径解析)
docs/               源清单.xlsx / 行情数据源清单.md / add-a-source.md 等
```

## 用法（完整仓库内）

```bash
python cli.py sources list             # 全部源 + 启用/健康
python cli.py sources fetch <id>       # 单源抓取(TTL 缓存)
python cli.py sources check            # 全源实抓体检
```

## 独立使用（只下载本文件夹）

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
- 备用源 key：同名大写环境变量，或板块根/`auto-publisher/autopub/` 下的 `secret.local.json`
- 缓存与健康数据默认写到项目根 `data/`（完整仓库）；独立使用时写到上级目录的 `data/`（不存在则随代码层级落盘）

## 加新源

按 [docs/add-a-source.md](docs/add-a-source.md)：在 `fetchers/basic.py` 写 fetcher → 在 `sources/builtin.py` 注册 → `python cli.py sources check --id <新id>` 实抓验证。
