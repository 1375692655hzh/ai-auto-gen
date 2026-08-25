# ai-gen-article-publish

AI 文章生成与多平台自动发布工具：基于大语言模型生成文章，并自动发布到国内 8 大内容平台。

## 架构总览

本仓库由两个互补的发布子系统组成，覆盖不同平台的最佳接入方式：

| 模块 | 技术栈 | 接入方式 | 支持平台 |
|---|---|---|---|
| [`generator/`](generator/) | Python + LLM | 多源财经快讯 + OpenAI 兼容模型 | 早报（A股/港美股）与分析文章生成，直接产出待发文章 + 口播稿 |
| [`autopub/`](autopub/) | Python + Playwright | 浏览器持久化配置（人工首登保会话） | 雪球、知乎专栏、东方财富财富号、老虎社区（同花顺/微博为占位） |
| [`adapters-kit/`](adapters-kit/) | Node.js + Playwright | API 优先 + storageState 认证 | 搜狐号、今日头条（头条号）、网易号、什么值得买 |

生成 → 发布链路：`generator` 产出的文章直接落入 `autopub/articles/` 待发目录，`autopub` 负责多平台发布。

### autopub/ — 浏览器自动化发布（Python）

- 从 `articles/` 目录读取 Markdown / Word 文章，解析为富文本块（粗体、标题、股票标签、图片）
- 每个平台使用独立的持久化 Chrome 配置目录（位于用户主目录），首次运行人工登录一次即可长期保持会话
- 内置：发布幂等账本（state.json）、节流与熔断（每篇间隔 ≥60s、连续 3 次失败熔断）、验证码/登录等待人工介入、图表转文字兜底（可选接 LLM）、Flask 本地控制台
- 详见 [autopub/README.md](autopub/README.md) 与 [autopub/使用指南.md](autopub/使用指南.md)

```bash
cd autopub
pip install -r requirements.txt
playwright install chromium
python webapp/app.py        # 打开 http://127.0.0.1:5001 本地控制台
# 或命令行方式
python publish_all.py       # 依次发布到所有启用平台
python publish.py --platform xueqiu --draft
```

### adapters-kit/ — API 适配器套件（Node.js）

- 统一的适配器接口与错误分类（需登录 / 拒绝发布 / 结果未知等），92 个单元测试
- 搜狐号 / 网易号 / 什么值得买走纯 HTTP API（含签名、CSRF、封面裁剪等完整握手），头条为 API + 无头浏览器混合（动态安全签名）
- 认证通过 Playwright storageState（cookies + localStorage）注入，登录态捕获需自行完成
- 内置平台约束校验（标题字数、封面必填、正文字数/图片数）、每日配额（北京时间计算）
- 详见 [adapters-kit/README.md](adapters-kit/README.md) 与 [adapters-kit/docs/engineering-guide.md](adapters-kit/docs/engineering-guide.md)

```bash
cd adapters-kit
npm install
npm test
node examples/publish.js <sohu|toutiao|wangyi|zdm> <accountId> <storageState.json> <article.json>
```

## 安全模型

- 仓库内**不含任何凭证**：平台登录态保存在本机（Chrome 配置目录 / storageState 文件），均被 .gitignore 排除
- LLM API Key 等个人密钥通过 `secret.local.json`（已忽略）或环境变量注入，切勿提交
- `adapters-kit` 源自脱敏学习包，附带 [NOTICE.md](adapters-kit/NOTICE.md) 说明，仅限授权学习使用

## 功能规划

- [x] 多平台自动发布（8 平台，两个子系统）
- [x] AI 文章生成模块（早报 + 分析文章，多模型可切换，复用 autopub 模型配置）
- [x] 生成 → 发布链路（generator 产出直接进入 autopub 待发目录）
- [ ] 定时自动早报（交易日早间）
- [ ] 发布结果统一对账与数据看板
