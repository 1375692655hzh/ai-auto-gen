# ai-auto-gen

AI 财经内容 **来源采集 → 生成 → 发布** 一体化工具，外加一个前端工作台。仓库按四大板块组织，**每一板块可独立下载使用**——不必为用不到的功能买单。

## 你要哪一个？

| 我想… | 需要下载 | 环境 | 上手 |
|---|---|---|---|
| 只跑**数据站**（108 源采集→SQLite→HTTP 供数+运维控制台，24/7 无人值守） | `cli.py` + `global-news-sources/` + `bin/` | Python ≥3.10，无 Node | [global-news-sources/README.md](global-news-sources/README.md) |
| 只跑**工作台**（接别人/自己局域网的数据站，可视化资讯/图文/视频/追踪） | `cli.py` + `workbench/` | Python ≥3.10，无 Node | [workbench/README.md](workbench/README.md) |
| 全部四板块（采集+生成+发布+工作台） | `git clone` 全仓 | 见下方快速开始 | `python cli.py doctor` |

只取一部分（sparse checkout，git 自带能力，根目录文件 cli.py 自动包含）：

```bash
# 数据站用户
git clone --depth 1 --filter=blob:none --sparse https://github.com/1375692655hzh/ai-auto-gen.git
cd ai-auto-gen
git sparse-checkout set global-news-sources bin

# 工作台用户
git clone --depth 1 --filter=blob:none --sparse https://github.com/1375692655hzh/ai-auto-gen.git
cd ai-auto-gen
git sparse-checkout set workbench
```

> 不要用"网页单目录下载"类第三方工具：板块目录不是自包含启动单元（根 `cli.py` 是统一入口），那样下会丢掉入口文件。

## 四板块布局

| 板块 | 目录 | 干什么 | 独立运行 |
|---|---|---|---|
| **来源·数据站** | [`global-news-sources/`](global-news-sources/) | 108 个金融信息源的注册表 + 抓取实现（快讯/公告/行情/同行文章/日历/X大V池），带 TTL 缓存、健康检查与四标签分类；含单机数据站（15min 调度刷新 → SQLite → 只读 HTTP 供数 8787 + 运维控制台 8786，见 global-news-sources/docs/供数服务.md） | ✅ 完全独立，配置走板块根 `config.yaml` 兜底 |
| **工作流** | [`ai-workflow/`](ai-workflow/) | 生成引擎：`flows/` YAML 编排工作流（断点续跑/审核挂起）+ `generator/` 生成实现 + `video/` Remotion 出片 | ⚠️ 依赖板块一的 fetchers 与板块三的模型配置 |
| **发布** | [`auto-publisher/`](auto-publisher/) | 双引擎发布：`autopub/` 浏览器自动化（10 平台，CDP 接管日常 Chrome）+ `adapters-kit/` Node API 适配器（搜狐/头条/网易/值得买）+ `publish/` 平台矩阵门面 | ✅ 基本独立（LLM 配置自给自足） |
| **工作台** | [`workbench/`](workbench/) | 前端工作台：FastAPI + 免构建 Vue3 SPA（资讯/图文/视频/追踪/设置 5 页），对三板块全程只读，数据只认数据站 HTTP 供数（设置页填地址+Key） | ✅ 完全独立（缺板块二三时动作类按钮不可用，浏览类页面不受影响） |

统一入口是根目录的 [`cli.py`](cli.py)（或 `bin/aag.cmd`），它按子命令惰性挂载各板块的导入路径——只保留部分板块时，其余板块的命令不可用但互不干扰。

## 快速开始（全量用户）

```bash
pip install -r ai-workflow/generator/requirements.txt -r auto-publisher/autopub/requirements.txt -r global-news-sources/requirements.txt -r workbench/requirements.txt
playwright install chromium

python cli.py doctor                 # 环境体检（密钥/浏览器/队列/账本/依赖）
python cli.py sources list           # 板块一: 全部源 + 四标签 + 启用/健康状态
python cli.py sources refresh        # 板块一·数据站写侧: 到期源刷新入 SQLite+快照(任务计划每15min)
python cli.py sources serve          # 板块一·数据站读侧: 只读 HTTP 供数(默认 127.0.0.1:8787)
python cli.py workbench serve --open # 板块四: 前端工作台(默认 127.0.0.1:8788)
python cli.py flows list             # 板块二: 全部工作流包
python cli.py flows run morning-paper --auto   # 跑每日早报(断点续跑, 审核挂起 exit 2)
python cli.py publish status         # 板块三: 待发队列 + 发布账本
python cli.py publish run --draft    # 草稿验证(真发需去掉 --draft 并人工确认)
```

## 安全模型

- 仓库内**不含任何凭证**：平台登录态保存在本机（Chrome 配置目录 / storageState），LLM key 走 `secret.local.json` 或环境变量，均被 .gitignore 排除
- 发布账本 `auto-publisher/autopub/state.json` 是防重复发布的唯一账本（原子写+损坏熔断），不手编
- 发布命令一律先 `--draft` 验证，人工确认后才真发
- `adapters-kit` 源自脱敏学习包，附带 [NOTICE.md](auto-publisher/adapters-kit/NOTICE.md)，仅限授权学习使用

## 功能规划

- [x] 来源库 108 源（快讯/公告/行情/同行/日历，缓存+健康检查；以 `sources list` 实测为准）
- [x] YAML 工作流引擎（断点续跑 / 审核挂起 / 包导出导入）
- [x] AI 财经早报 + 日报 + 分析文章（多模型可切换）
- [x] 日报一键成片（Remotion：TTS 配音 + 模板渲染，1080p）
- [x] 多平台自动发布（14 平台矩阵，浏览器 + API 双引擎）
- [x] 前端工作台（资讯聚合/图文成稿/视频工坊/账号追踪）
- [ ] 定时自动早报（交易日早间）
- [ ] 发布结果统一对账与数据看板

详细架构见 [docs/三大板块实施方案.md](docs/三大板块实施方案.md)。
