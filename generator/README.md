# 文章生成模块(generator)

基于多源财经快讯 + LLM 生成两类内容,初稿版本:

- **早报**:抓取 A股/港美股多源快讯 → 生成《今日A股早报》《今日港美股早报》两篇文章,各配口播稿
- **分析文章**:选题 → 锁定最新信息 → 确定大纲 → 生成分析文章 + 口播稿

生成的**文章直接落入 `../autopub/articles/`**(发布系统待发目录),口播稿存 `generator/output/口播/`(不进发布链路),过程产物(选题素材快照、大纲)存 `output/research/`。

## 前置准备

1. 依赖(Python 3.10+):
   ```bash
   pip install requests pyyaml
   ```
2. 模型 API(与 autopub 共用一套配置,填一次即可):
   - 最简单:启动 `python autopub/webapp/app.py`,在 http://127.0.0.1:5001 的「模型 API 设置」里选 provider(智谱/DeepSeek/千问/Kimi/OpenAI/Ollama)并填 key
   - 或设环境变量 `AUTOPUB_API_KEY` 并在 `autopub/config.yaml` 的 `model:` 段填 `provider` + `model`
   - 检查状态:`python generator/main.py llm-status`
3. 信息源无需账号,默认启用新浪财经 7×24 + 东方财富快讯;在 `config.yaml` 里可开关/调条数

## 使用

```bash
# 看看信息源能抓到什么(不需要模型)
python generator/main.py fetch --limit 10

# 早报:A股 + 港美股两篇(各带口播稿)
python generator/main.py morning
python generator/main.py morning --market us     # 只出港美股

# 分析文章:四步流程,交互确认
python generator/main.py analysis                # 自动从热点里提3个候选主题供选择
python generator/main.py analysis --topic "AI芯片国产替代"
python generator/main.py analysis --topic "..." --yes   # 全自动不确认
```

## 流程说明

**早报**(`morning.py`):抓多源快讯取最新 N 条 → 模型按市场筛选分类 → 分别成文 + 改写口播稿。筛选交给模型而非关键词,避免漏掉宏观联动消息。

**分析文章**(`analysis.py`)四步,每步产物落盘可追溯:
1. **选题**:手动 `--topic` 或从最新快讯自动提炼 3 个候选(含理由与切入角度)
2. **锁定信息**:全量快讯中筛出主题相关条目,原文不改写,快照存 `output/research/主题-日期.json`
3. **大纲**:基于锁定素材生成,交互确认或重新生成
4. **成文**:文章(约1500-2500字)+ 口播稿(约2分钟),事实只允许来自锁定素材

## 配置

见 `config.yaml`:信息源开关、早报/分析的字数与口播时长、输出目录。模型 provider/key 不在本模块配置,见上「前置准备」。

## 后续规划

- 信息源扩展:财联社电报、同花顺热榜、港美股行情数据(隔夜指数点位自动附在早报里)
- 定时任务:每个交易日早间自动生成早报
- 生成质量:素材溯源标注、发布平台差异化版本
