---
name: aag-source-fix
description: ai-auto-gen 工具的信息源抓取失败排查与修复（来源库健康机制）。当用户说"某来源挂了/抓不到数据/来源失效"时使用。
---

# 来源修复流程

1. **定位**：`python cli.py sources check` 看全部来源健康（ok/degraded/dead）。
2. **单源复现**：`python cli.py sources fetch <id> --fresh --limit 5`
   - dead = 连续 3 次失败，gather 时自动跳过。
3. **修复**（按 docs/add-a-source.md）：
   - 接口/选择器变了 → 改 `global-news-sources/sources/builtin.py` 里对应包装指向的 fetchers 抓取函数（`global-news-sources/fetchers/basic.py` / `extra.py`）。
   - 富途 WAF 类 → 算法在 `global-news-sources/fetchers/extra.py` 的 `_waf_hash/_waf_suffix`，需按新站况更新。
   - 反爬严的源（gangtise 搜狗链）优先考虑换 fallback（元宝镜像 `global-news-sources/fetchers/yuanbao_fetch.py`）。
4. **复位**：修好后 `python cli.py sources check --id <id>` 成功一次即从 dead 恢复 ok。
5. 新增来源：在 `sources/builtin.py` 加 `@source(...)` 包装（见 docs/add-a-source.md）。

注意：来源缓存 10-120 分钟（`data/cache/sources/`），改完代码调试记得 `--fresh`。
