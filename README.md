# ai-auto-gen

AI 财经内容 **来源采集 → 生成 → 发布** 一体化工具。仓库按三大板块组织，**每个板块可独立下载使用**（只想要其中一块功能时，只取对应文件夹即可）。

## 三板块布局

| 板块 | 目录 | 干什么 | 独立运行 |
|---|---|---|---|
| **来源** | [`global-news-sources/`](global-news-sources/) | 107 个金融信息源的注册表 + 抓取实现（快讯/公告/行情/同行文章/日历），带 TTL 缓存与健康检查 | ✅ 完全独立（`sources` 包 + `fetchers/`），配置走板块根 `config.yaml` 兜底 |
| **工作流** | [`ai-workflow/`](ai-workflow/) | 生成引擎：`flows/` YAML 编排工作流（断点续跑/审核挂起）+ `generator/` 生成实现 + `video/` Remotion 出片 | ⚠️ 依赖板块一的 fetchers 与板块三的模型配置 |
| **发布** | [`auto-publisher/`](auto-publisher/) | 双引擎发布：`autopub/` 浏览器自动化（10 平台，CDP 接管日常 Chrome）+ `adapters-kit/` Node API 适配器（搜狐/头条/网易/值得买）+ `publish/` 平台矩阵门面 | ✅ 基本独立（LLM 配置自给自足） |

统一入口是根目录的 [`cli.py`](cli.py)（或 `bin/aag.cmd`），它会自动把三个板块挂上导入路径。

## 快速开始

```bash
pip install -r ai-workflow/generator/requirements.txt -r auto-publisher/autopub/requirements.txt
playwright install chromium

python cli.py doctor                 # 环境体检（密钥/浏览器/队列/账本）
python cli.py sources list           # 板块一: 全部 107 源 + 启用/健康状态
python cli.py flows list             # 板块二: 全部工作流包
python cli.py flows run morning-paper --auto   # 跑每日早报(断点续跑, 审核挂起 exit 2)
python cli.py publish status         # 板块三: 待发队列 + 发布账本
python cli.py publish run --draft    # 草稿验证(真发需去掉 --draft 并人工确认)
```

## 只取一个板块

- **只要源**：下载 `global-news-sources/`，`pip install requests pyyaml`，然后 `sys.path` 挂上该目录及其 `fetchers/` 即可 `from sources import gather, fetch_one`。enabled 开关读板块根 `config.yaml`（完整仓库内自动改用 `ai-workflow/generator/config.yaml`），备用源 key 读环境变量或板块根 `secret.local.json`。详见 [global-news-sources/README.md](global-news-sources/README.md)。
- **只要发布**：下载 `auto-publisher/`，按 [auto-publisher/README.md](auto-publisher/README.md) 操作（模型密钥三种方式任选，网页控制台最省事）。
- **只要工作流**：下载 `ai-workflow/`，另需把 `global-news-sources/fetchers/` 的可抓取实现配上（工作流的 fetch 步骤依赖它）；模型配置沿用 auto-publisher 的 `autopub/secret.local.json` 链路或环境变量。

## 安全模型

- 仓库内**不含任何凭证**：平台登录态保存在本机（Chrome 配置目录 / storageState），LLM key 走 `secret.local.json` 或环境变量，均被 .gitignore 排除
- 发布账本 `auto-publisher/autopub/state.json` 是防重复发布的唯一账本（原子写+损坏熔断），不手编
- 发布命令一律先 `--draft` 验证，人工确认后才真发
- `adapters-kit` 源自脱敏学习包，附带 [NOTICE.md](auto-publisher/adapters-kit/NOTICE.md)，仅限授权学习使用

## 功能规划

- [x] 来源库 107 源（快讯/公告/行情/同行/日历，缓存+健康检查）
- [x] YAML 工作流引擎（断点续跑 / 审核挂起 / 包导出导入）
- [x] AI 财经早报 + 日报 + 分析文章（多模型可切换）
- [x] 日报一键成片（Remotion：TTS 配音 + 模板渲染，1080p）
- [x] 多平台自动发布（14 平台矩阵，浏览器 + API 双引擎）
- [ ] 定时自动早报（交易日早间）
- [ ] 发布结果统一对账与数据看板

详细架构见 [docs/三大板块实施方案.md](docs/三大板块实施方案.md)。
