# 20-vmake-moa.md — 视频制作页打通(文稿→创作设置→Remotion 成片) MoA 规划与执行记录

> 2026-09-05, moa(codex[astra]+grok+kimi) 三岗独立规划, 全员交卷 ✅。任务原文: "视频制作页面也帮我打通，同样是参考E盘Ai-video这个项目…用户上传文稿，可以选择风格等等视频创作设置，然后制作视频"。

## 一、三岗共识(采纳)

- 本仓库 ai-workflow/video 与 E:\ai-video\ai-video 是**同源 Remotion 产线**(后者为超集: 竖版三模板/clip/数字人/reveal 对齐/story-validate/QA)。同为用户自有 UNLICENSED 项目, 移植代码无许可障碍、零新依赖。
- 架构: workbench 进程只写 data/workbench/; 新 CLI 子进程是板块二 videos/ 目录唯一写者; video_jobs.json 扩第三 build 锁(独立 60min 僵死阈值; active-story.ts 全局单槽 → build 全局单飞 409); 参数进 request 不走 argv; 前端 pollJob('build') 3s 轮询, mounted 恢复。
- 三文稿来源归一: 粘贴/上传(.txt/.md 前端 FileReader, 零后端上传端点)先走既有脚本生成链; 脚本仓库成稿直接用; 统一 wb-video-script/v1 → story.json 转换。
- 转换: narration **逐字冻结** + 模板白名单双闸门; LLM 只编排视觉 data 层, 失败降确定性映射(role→模板轮换)。
- TTS: edge 免费默认(Xiaoxiao/Yunxi/Yunyang), dashscope 可选(key 探测 ai-workflow/video/.env, 不进 workbench settings); 语速本期不做; 封面自动; 字幕 caption=narration。

## 二、分歧裁定

| 分歧 | 裁决 |
|---|---|
| 竖版是否本期移植(2:1) | **移植**。kimi 案: Data 接口声明在 templates-vertical.tsx 内, story-types.ts 一字不动——恰好满足红线字面与精神; grok 独立同设计。codex 的保守案(纯横版)被否, 因 shorts 脚本本就是竖版语义 |
| story-validate 移植(2:1) | 移植, 扩展容忍本仓库字段(captions/compact/summary/stat/tags/entrances 只警告不拒) |
| QA 状态机 | kimi 中间案: verify.json + 日志留痕, 门禁维持 draft/reviewed/built 三态, QA 失败不置 built |
| 模块落点 | 转换器独立 `vmake.py`(grok 命名); 渲染由编排 CLI 直调 node scripts/build.mjs(逐行读 stdout 做进度, 不经 cli.py video build 透传) |
| 门禁语义 | 向导"开始制作"=用户确认 → project.status 直接写 reviewed, 不用 --force |

## 三、执行与验证(codex[astra] 执行, 主会话核验)

改动: 新建 ai-workflow/video/src/templates-vertical.tsx、scripts/story-validate.mjs、scripts/template-ids.mjs、workbench/server/vmake.py; 改 Video.tsx/Composition.tsx/build.mjs/vstudio.py/app.py/cli.py/video.js/index.html/AGENTS.md。红线核验: story-types.ts 相对 HEAD **0 diff**; active-story.ts 仅由 build.mjs 生成。

codex 验证: tsc --noEmit exit 0(含新竖版模板); 离线单测 35/35; 竖版真渲染冒烟(1080×1920 preview-silent.mp4)。

主会话全链路实测(真实外呼+渲染): 粘贴文稿 → gen-script(muse) → 入仓 vs0905205628970 → POST /video-build → job 进度 convert→create→tts→render→done exit 0 → `videos/wb0905205634/out/final.mp4`(5.2MB, TTS 配音) + cover.png + verify.json, status=built, story 1080×1920 6 scenes(vtitle/vstat/vpoints 轮换), /wb-api/videos 列表可见可播。

修复/裁量: dashscope 音色名绝不落 edge 引擎(防降级后整批失败); build 超时 3600s 杀进程树; 日志 data/workbench/video_builds/<project_id>.log; mp4 播放优先 final.mp4; video new 落空修复、video remove 新增。

遗留 D2: clip 素材/数字人/reveal 逐字对齐/语速/投稿按钮激活(板块三 --draft 流程)/模板仓库与素材仓库实装。
