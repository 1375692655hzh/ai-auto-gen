# 四平台发文逻辑脱敏学习包

这是从现有主工程中独立整理出的学习包，只保留当前四个平台的发文适配逻辑：搜狐号、今日头条、网易号、什么值得买。包内不包含业务后台、上游内容源同步、数据库表结构、用户体系、任务队列、生产账号、登录 Cookie、代理地址或固定密钥。

## 快速阅读

- 先读 `docs/engineering-guide.md`，了解统一流程、文章模型和各平台差异。
- 四个平台入口分别在 `src/adapters/<platform>/index.js`。
- HTTP 接口、请求组装和状态映射在同目录 `api.js`。
- 易变的页面定位集中在同目录 `selectors.js`。
- 共享编排在 `src/adapters/base.js`，富文本注入与缺图门禁在 `src/adapters/richtext.js`。
- 脱敏边界与交付前复核项见 `docs/sanitization-checklist.md`。

## 本地检查

要求 Node.js 20 以上。

```bash
npm install
npm run check
```

真实发布具有外部副作用，示例不会自动携带任何账号。确需在接收方测试环境验证时，先阅读工程说明，并只使用接收方自有测试账号和内容。平台页面、接口和风控会随时变化，选择器与接口参数需要以接收方测试时的页面为准。
