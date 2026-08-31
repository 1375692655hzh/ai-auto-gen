# ai-workflow — 板块二：生成工作流

AI 财经内容的生成引擎：YAML 编排工作流 + 生成实现 + Remotion 视频出片。

## 结构

```
flows/              工作流引擎(YAML 编排, 断点续跑, 审核挂起 exit 2)
  engine.py         执行器(discover/lint/run_flow/export/import/new)
  steps/            步骤库(fetch/rank/expand/assemble/formats/enrich/script/video/morning/image/review)
  builtin/          内置工作流包(morning-paper 早报 / morning-digest / market-review 大盘复盘)
generator/          生成实现(LLM 桥接/早报/日报/分析/长图/口播)
video/              Remotion 视频引擎(story.json 契约, 1080p)
```

## 用法（完整仓库内，经根 cli.py）

```bash
python cli.py flows list                        # 工作流包
python cli.py flows run morning-paper --auto    # 每日早报(审核挂起 exit 2, 改完产物重跑自动续)
python cli.py flows status morning-paper        # 运行状态(run.json)
python cli.py gen <args>                        # 生成模块透传(gen morning/daily/run/fetch/llm-status)
python cli.py video build <id>                  # Remotion 出片
```

## 依赖关系（独立下载时注意）

- **fetch 步骤**依赖板块一 `global-news-sources/fetchers/`（`basic.py`/`extra.py` 的抓取实现）——单独使用本板块需把该目录挂上 `sys.path`
- **LLM 配置**沿用板块三 `auto-publisher/autopub/` 的配置链（config.yaml model 段 ← secret.local.json ← AUTOPUB_API_KEY 环境变量），三选一即可
- `video/` 出片需 Node ≥ 20，首次 `cd video && npm install`

## 审核点语义

工作流跑到标记 `review: true` 的步骤会写 `data/runs/<流>/<日期>/run.json`(status=waiting_review) 后 exit 2——这是**非交互挂起**：人工到产物目录审改后重跑同一命令即自动续跑（存档复用）。

## 红线

- 不改 `video/src/active-story.ts`（渲染时自动生成）与 `video/src/story-types.ts` 契约
- LLM 生成的数字必须逐字来自素材（引擎内有防幻觉校验）
