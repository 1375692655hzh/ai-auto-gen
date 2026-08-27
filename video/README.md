# AI 视频 engine

文章 → 演讲稿 →（人工审核）→ 配音 → 数据驱动动效视频，一条流水线。

## 工作流

```
文章 ──> ① agent 撰写演讲稿 + 分镜（story.json）
      ──> ② 人工审核 narration（直接改 story.json）
      ──> ③ project.json 的 status 改为 "reviewed"
      ──> ④ node scripts/build.mjs <projectId>
      ──> ⑤ videos/<projectId>/out/final.mp4
```

- ①③ 中 agent 只参与写稿和新模板开发；④ 是纯脚本（TTS → 测时长 → 渲染），无需 agent。
- status 不是 "reviewed" 时 build 会拒绝执行（强制构建加 `--force`）。

## 常用命令

```bash
npm run video:new -- <id> "文章.md路径"   # 新建视频项目（脚手架）
npm run video:build -- <id>              # 一键制作（审核通过后）
node scripts/build.mjs <id> --estimate   # 无语音快速预览版（按字数估时长）
node scripts/build.mjs <id> --no-render  # 只生成时间轴，配合 studio 预览：
npx remotion studio --public-dir videos/<id>
```

## 项目文件夹结构（videos/<id>/，自包含可归档）

```
videos/<id>/
├── project.json    # 元信息 + 审核状态（draft/reviewed/built）
├── story.json      # 演讲稿 + 分镜数据（人工审核对象）
├── input/          # 原始文章
├── script/         # 稿件草稿（可选）
├── audio/          # TTS 语音（build 自动生成/补齐）
└── out/            # 成片 final.mp4
```

## story.json 格式速览

```jsonc
{
  "meta": { "title": "...", "voice": "zh-CN-YunxiNeural", "fps": 30, "width": 1920, "height": 1080 },
  "scenes": [
    {
      "id": "deal",                      // 场景 id（也是音频文件名）
      "template": "event",               // 版式：title/event/bars/compare/cards/rows/stacked/versus/checklist/conclusion
      "narration": "旁白文本（TTS 念法，数字写汉字）",
      "caption": "字幕（缺省用 narration）",
      "data": { "...": "版式数据，见 src/story-types.ts" }
    }
  ]
}
```

- 富文本统一用片段数组：`[{ "t": "文字", "c": "red", "b": true }, { "br": true }]`
  （c 颜色：text/sub/nvidia/red/green/amber/blue/purple；b 加粗；br 换行）
- 场景时长 = 该段语音时长 + padSeconds，自动计算，无需手填。

### TTS 引擎（二选一）

**1. Edge TTS（默认，免费）** —— 直接改 `meta.voice`：
`zh-CN-YunxiNeural` 云希男声 / `zh-CN-YunjianNeural` 沉稳男声 / `zh-CN-XiaoxiaoNeural` 女声

**2. 阿里云 Qwen TTS（qwen-audio-3.0-tts-plus，付费，质量更好）** —— `meta` 里加：

```jsonc
"tts": { "provider": "dashscope", "voice": "longanlufeng" }
// 音色：longanlufeng 龙安鲁风（男，明亮开朗）/ longanlingxin 龙安灵心（女，知心温暖）
```

密钥放在引擎根目录 `.env`（不入库）：
```
DASHSCOPE_API_KEY=sk-...
DASHSCOPE_BASE_URL=https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
```

## 引擎结构（本仓库根目录）

```
src/
├── story-types.ts      # story.json 的 TypeScript 类型（含各模板 data 结构）
├── templates-core.tsx  # 模板：title / event / bars / compare / cards
├── templates-extra.tsx # 模板：rows / stacked / versus / checklist / conclusion
├── ui.tsx              # 主题（色板/字体/富文本渲染/面板/字幕条）
├── Video.tsx           # 装配：按 active-story 排布场景 + 挂音轨
├── active-story.ts     # 【自动生成】当前要渲染的项目数据
└── Composition.tsx     # Remotion 入口（id: Nvidia500B）
scripts/
├── new-article.mjs     # 新建项目
└── build.mjs           # 一键流水线（审核门禁）
```

## 注意事项

- TTS 走 Edge TTS 免费接口，网络偶发断流已内置 8 次重试；失败重跑即可（已有音频自动跳过）。
- 改了 narration 后需重出对应语音：删除 `audio/<id>.mp3` 再 build。
- 渲染 3 分钟 1080p 视频约 1-2 分钟（`--concurrency C4`）。
