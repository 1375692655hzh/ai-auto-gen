# 19-vstudio-moa.md — 视频工坊三环节(视频分析/脚本生成/脚本仓库) MoA 规划与执行记录

> 2026-09-05, moa(grok+doubao+codex+gemini+kimi) 五岗独立规划, 全员交卷 ✅(无失败岗)。任务原文: 用户消息逐字(三子页布局+参考项目清单 E:\ai-video 与 30 个外部工具)。本文 = 汇总裁决 + 执行/验证记录。五岗答卷原文存会话, 需要可导出。

## 一、五岗共识(直接采纳)

- 新模块 `workbench/server/vstudio.py` 收口(否决 doubao 三模块案), 对标 yt_track 纪律: 端点零外呼, LLM/yt-dlp 外呼只在 CLI 子进程(app.py 仅两处 Popen + JSONResponse); 前端 3s 轮询任务态。
- 四个新 JSON 全落 data/workbench/: video_pool.json(素材池)/video_analyses.json(分析缓存, 字典)/video_scripts.json(脚本仓库)/video_jobs.json(analyze+generate 双锁任务态, 参数进 request 文件不走 argv——长中文粘贴稿规避 Windows argv 限制)。
- 分析降级链: G0 Gemini file_uri 直读 YouTube URL(移植 E:\ai-video gen-video-analysis.mjs 请求形状+三段式 prompt, 180s 一次不重试) → G1 yt-dlp 字幕(py -3.12, 单次, cookies 可选) + muse 文本分析 → G2 yt_videos.json 元数据 + muse(partial)。whisper 本期不做(5:0)。
- 脚本生成: 三件套(brief/文章稿[粘贴或 drafts.json 引用]/风格预设) + 可选 analysis_key(只注入 reusable+hook.categories+structure.arc, 禁注入对方原文——差异化铁律); muse 出 wb-video-script/v1; 代码算时长(4.2字/秒)不信 LLM; 校验产 warnings 不拒收。
- 保存语义: 分析页保存=确定性转换 analysis_seed(零 LLM); 生成页保存=generated; 都是显式按钮(不自动入库)。
- 前端: 8 子页(脚本仓库排脚本生成下方); 热点两张表标题行内"＋加入素材池"; 分析页右池/中分析/下结果/底保存; `.two-col.pool-right` 反转列(grok 揪出 .two-col 是左窄右宽)。
- Gemini key: settings.json 新增 gemini 段(打码回显)+env 兜底; 禁止运行时跨仓库读 E:\ai-video\.env(4:1 否决 kimi 案)。

## 二、关键分歧裁定

| 分歧 | 裁决 | 理由 |
|---|---|---|
| 模块数(1 vs 3) | 1 个 vstudio.py | 与 yt_track/x_surge 一库一域惯例一致 |
| 缓存复用策略 | status ok/partial 即永久复用 + 显式"重新分析"force(grok 案) | 分析成本分钟级, input_hash 自动失效收益低; force 足够 |
| Gemini key 来源 | settings + env(多数案) | 解耦部署; 首次由用户粘贴(执行时已代配) |
| 热点入池按钮位置 | 近期热点+近期视频两表标题行内文字链(grok 案) | 不新开列(表已 10 列), 不跳页 |

## 三、执行与验证记录(codex 执行, 主会话核验修正)

改动: 新建 vstudio.py(838行) + 改 config.py/app.py/cli.py/video.js/settings.js/app.css/index.html/AGENTS.md。codex 离线验证 33 项单测 + TestClient 14 项全过。

主会话实测中揪出并修复 5 个问题:
1. **gemini-2.5-flash 已停用**(API 404 提示改 3.6-flash) → 默认模型改 `gemini-3.6-flash`(config DEFAULTS + settings 热更)。
2. **新版 yt-dlp 需 JS 运行时** → 命令加 `--js-runtimes node`。
3. **_id 同秒撞车**(两条脚本仓库行同 id) → _id 加毫秒尾数。
4. **analysis 记录 title 空**(池行无标题且无自动补齐) → pool_add 与 _target 双点从 yt_videos.json 补展示快照(蓝图有此条, codex 漏做)。
5. gemini_watch_url 返回 (text, evidence) 元组等 codex 合理裁量 6 处照单采纳。

端到端实测(真实外呼): 热点行入池 → G0 看片(tier=gemini, ok, 语义 9 字段+三段式报告齐全, 样例: SPCX 解禁暴涨 38s 竖版片) → analysis_seed 入仓(标题/章节正确) → 生成 shorts-60 脚本(3 钩子互异/6 beats/63s/266 字/零警告, 引用分析 reusable) → 入仓 → 查删改全通。G1→G2 降级链在模型停用事故中实测走通。一次 curl 中文 GBK 编码 500 属测试工具问题(浏览器 fetch UTF-8 不受影响)。

## 四、遗留

- 素材仓库/模板仓库仍占位; 脚本→story.json→video build 衔接、Whisper 本地媒体、素材池非 YT URL 均留 D2。
- Gemini key 已从 E:\ai-video\.env 复制进本机 settings.json(gitignored), 用户可随时在设置页更换。
