# workbench — 板块四·前端工作台

接入数据站的可视化工作台：资讯聚合（标签筛选）→ 图文/视频制作（产物回显）→ 账号追踪 → 设置。
方案定稿见 [docs/第四板块-前端工作台方案.md](../docs/第四板块-前端工作台方案.md)（MoA 四岗方案存档在 `docs/workbench-moa/`）。

## 装工作台：两档口径（2026-09-15 起，发给同事默认发完整档）

### 完整档（推荐 · 全功能，含视频配音/出片、图文成稿）

适用画像：本机要完整用工作台，包括视频制作（配音/出片/封面）。**发给同事就发这段。**

```bash
git clone https://github.com/1375692655hzh/ai-auto-gen.git
cd ai-auto-gen
bin\setup-workbench.cmd        # 一键配置: pip 依赖 + npm 依赖 + 环境体检(幂等, 可重跑)
python cli.py workbench serve --open   # 启动, 浏览器自动打开 http://127.0.0.1:8788
```

- 需要两样环境：**Python ≥3.10**（推荐 3.11）+ **Node.js ≥ 20**（视频功能用，[nodejs.org](https://nodejs.org) 装 LTS；只看资讯可以不装，setup 脚本会说明）。
- setup 脚本做完了所有环境活（pip 三件套、可选增强包、`ai-workflow/video` 里 `npm install`、doctor 体检）；失败重跑即可，每步都有指引。
- 起来之后所有 key 配置都在网页**设置页**完成（每个卡位带注册来源引导：信息源连接/翻译/成稿/TTS/YouTube/Gemini）。

### 轻量档（纯浏览，无 Node）

适用画像：只接别人/局域网数据站**看资讯**，不做视频配音/出片、不做图文成稿。

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/1375692655hzh/ai-auto-gen.git
cd ai-auto-gen
git sparse-checkout set workbench
pip install -r workbench/requirements.txt    # fastapi/uvicorn/pyyaml/requests, 无 Node 无构建
python cli.py workbench serve --open         # 127.0.0.1:8788, 自动开浏览器
```

然后进 **设置页** → 信息源连接选「局域网数据站」→ 填数据站地址（如 `http://192.168.x.x:8787`）+ Bearer Key → 「测试连接」通过即接入完成。

**能力边界**（轻量档）：资讯浏览/翻译/蹭蹭流量/追踪/视频分析(Gemini)可用；**视频配音/出片/封面、图文成稿需要板块二（`ai-workflow/`）+ Node ≥ 20 + 该目录 `npm install`**——点击这些功能时页面会直接给出补救指引（升完整档 = 全量克隆/补拉 `ai-workflow` + 装 Node + 跑 `bin/setup-workbench.cmd`）。X 账号档案/标签增强依赖板块一本地文件，轻量档自动降级为空映射，不影响浏览。

## 完整仓库内快速开始

```bash
# 终端 A: 起数据站(板块一, 资讯页的数据来源)
python cli.py sources serve          # 127.0.0.1:8787

# 终端 B: 起工作台
python cli.py workbench serve --open # 127.0.0.1:8788, 自动开浏览器
```

## 五个页面

| 页面 | 路由 | 状态 |
|---|---|---|
| 资讯 | `#/news` | ✅ 全功能：标签筛选(市场/类型/信息类别/情绪/渠道/形态/来源) + 搜索 + 时效 + 游标翻页 + 同事件折叠 + 中英切换 + 素材篮 |
| 图文 | `#/article` | 素材篮 + 工作流状态机回显 + 产物/队列只读浏览；成稿编排需板块二在位 |
| 视频 | `#/video` | 项目列表(draft→reviewed→built 门禁徽章) + mp4 播放 + 视频工坊(分析/脚本/渲染编排，需板块二在位) |
| 追踪 | `#/track` | 追踪账号真实增删(落盘) + X 起爆帖互动采集 + YouTube 热点追踪(需 Data API Key) |
| 设置 | `#/settings` | ✅ 信息源连接(模式/地址/Key/测试连接)；界面偏好；环境自检；云端同步 501 预留 |

## 依赖矩阵

- **数据**依赖板块一数据站：`sources serve` 供数（经 `/wb-api/v1/*` 代理，前端不直连 8787，Key 不出服务端）；数据站可以在别的机器上。
- **动作**依赖板块二/三：只经 `subprocess 调 python cli.py ...`，不 import 内部模块；板块缺失时优雅降级。

## 运行时数据（gitignored）

| 文件 | 语义 |
|---|---|
| `data/workbench/settings.json` | 工作台设置（数据源/界面/云端预留），设置页唯一写口 |
| `data/workbench/tracked_accounts.json` | 追踪账号清单 |

## 红线

- 三板块文件（state.json/run.json/产物目录）**全程只读**；唯一写口是 `data/workbench/` 自有 JSON。
- 默认绑 127.0.0.1；`--bind 0.0.0.0` 对外时与 sources serve 同一告诫：内网/隧道，禁裸公网。
- 发布永远 `--draft` 先行（真发必须前端二次确认）。
