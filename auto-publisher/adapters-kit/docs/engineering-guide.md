# 四平台发文工程说明

## 1. 交付范围

本包只解释“把一篇已准备好的文章提交到平台，并读取平台结果”这一段能力。上游正文来源、业务审批、排期、账号管理、持久化任务队列、结果回写和运营控制台均不在交付范围内。

当前平台：

| 平台 ID | 平台 | 主链路 | 发布后状态特点 |
| --- | --- | --- | --- |
| `sohu` | 搜狐号 | HTTP API 直发 | 通常可从内容列表取得公开链接 |
| `toutiao` | 今日头条 | API + 浏览器动态安全参数 | 可能先返回审核中，再补公开链接 |
| `wangyi` | 网易号 | HTTP API 直发；遇风控时浏览器恢复 | 保存草稿后复用文章 ID 正式发布 |
| `zdm` | 什么值得买 | HTTP API 直发 | 先审后发，通常不能即时拿公开链接 |

## 2. 目录结构

```text
src/
├── adapters/
│   ├── base.js                 # 统一错误类型和浏览器型发布流水线
│   ├── registry.js             # 平台注册、别名解析、公开元数据
│   ├── richtext.js             # 富文本注入与图片完整性门禁
│   ├── publicationStatus.js    # 标题容错匹配、状态归一化、列表轮询
│   └── <platform>/
│       ├── index.js            # 平台级编排入口
│       ├── api.js              # 请求组装、上传、提交、状态查询
│       └── selectors.js        # 页面 URL 与 DOM 选择器
├── browser/                    # 临时浏览器上下文与拟人化输入
├── captcha/                    # 网易易盾第三方识别客户端
├── domain/                     # 标题、封面、字数、图片数等规则
├── http/                       # 可重试 HTTP 请求
├── runtime/                    # 脱敏后的内存登录态适配层
├── config.js                   # 仅从环境变量读取可选配置
└── index.js                    # 对外导出

examples/                       # 最小调用样例，不含真实账号
test/                           # 四平台请求与公共逻辑测试
```

## 3. 统一输入模型

平台入口统一接收 `article` 和 `hooks`。推荐的文章对象如下：

```js
const article = {
  title: '文章标题',
  html: '<p>正文，图片可先使用 data URL 占位</p>',
  text: '用于字数统计和纯文本降级的正文',
  images: [
    { path: '/绝对路径/body-1.jpg', contentType: 'image/jpeg' },
  ],
  topicImage: {
    path: '/绝对路径/cover.jpg',       // 网易封面
    longPath: '/绝对路径/cover-long.jpg', // 值得买长图
    squarePath: '/绝对路径/cover-square.jpg', // 值得买方图
  },
  tags: ['标签'],
};

const hooks = {
  accountId: '接收方自己的账号主键',
  mode: 'auto',
  onStage(stage, detail) {},
  onLoginChecked(ok, accountStatus) {},
};
```

调用方应在进入 adapter 前完成内容授权、敏感词检查、平台投放确认和幂等控制。`accountId` 只是调用方内部主键，不是平台账号明文。

## 4. 统一生命周期

通用浏览器型基类定义了以下阶段：

1. `login-check`：确认登录态。
2. `open-editor`：打开编辑器或声明使用 API 直发。
3. `fill-title`、`fill-body`、`fill-meta`：准备标题、正文、封面和标签。
4. 可选 `waiting-confirm`：调用方自行生成预览并等待人工确认。
5. `click-publish` 或 `publish-api`：真正产生外部提交副作用。
6. `detect-published` / `fetch-status`：读取作品列表或接口状态。
7. 返回统一结果：

```js
{ status: 'published | reviewing | scheduled', url: '', detail: '' }
```

失败分为三类：

- `NeedLoginError`：登录态失效，可重新登录后再试。
- `PublishRejectedError`：平台明确拒绝或内容不符合硬约束，不应盲目自动重试。
- `PublishResultUnknownError`：已产生提交动作，但未确认最终结果。调用方必须先查作品列表，再决定是否重试，避免重复发文。

## 5. 四个平台实现要点

### 5.1 搜狐号

入口：`src/adapters/sohu/index.js`。

主流程是检查会话、读取账号和发文额度、逐图上传、把正文中的 data URL 按顺序替换为平台 CDN URL、组装发布载荷并提交，最后按 newsId 与标题从内容列表匹配状态。平台明确显示额度为零或 API 返回对应错误时，转为不可继续提交的拒绝错误。

保留的页面型方法用于登录检查和兼容性排障；正常发文走 API 直发。

### 5.2 今日头条

入口：`src/adapters/toutiao/index.js`。

标题先按 2～30 个 Unicode 码点做硬校验。图片先上传，正文中的 data URL 再替换为平台图片地址。发布接口需要动态安全参数，因此使用带登录态的临时浏览器加载平台脚本，仅抓取请求所需的动态查询参数和请求头；图片上传、发布、作品查询仍由 HTTP 客户端完成。

这是一条混合链路，所以调用 `publish` 时必须传入 Playwright page。

### 5.3 网易号

入口：`src/adapters/wangyi/index.js`。

网易要求 5～64 字标题和封面。正文图与封面先上传并登记到素材库；随后先保存草稿，让服务端生成 articleId，再携带该 articleId 正式发布。

网易的动态 token 与易盾验证较复杂：接口出现验证码信号时，代码会打开临时浏览器，进入真实编辑页触发保存，通过可选识别服务换取 validate，再把刷新后的动态字段合并回原始业务表单。合并时只替换 `ursToken`、`sign`、`timestamp`、`NECaptchaValidate`，原始标题、正文和文章 ID 保持不变。

如果接收方不配置识别服务，`WANGYI_CAPTCHA_PROVIDER=none`，普通请求仍可运行；遇到风控时应中止并转人工，不要无限重试。

### 5.4 什么值得买

入口：`src/adapters/zdm/index.js`。

发布前要求长图和方图两种封面。流程先分配 articleId、建立空草稿，再上传正文图和两种封面，最后以 `submit` 类型提交。正文建议不少于 800 字、图片不少于 5 张；这两项属于审核风险提示，不是接口硬拦截。

值得买先审后发。提交成功后没有公开 URL 是正常情况，调用方应保留 reviewing 状态，并按 articleId 或容错标题定期查询作品列表。

## 6. 富文本与图片策略

浏览器型兼容逻辑依次尝试：编辑器原生 API、合成 paste 事件、`execCommand('insertHTML')`。图片由上游提供本地文件，同时正文中保留可顺序替换的 data URL。API 型适配器先上传图片，再按出现顺序替换正文图片地址。

`requireCompleteInjection` 是发布门禁：若编辑器里的图片数少于文章图片数，流程会停止，不会继续点击发布。选择器完全失效时只告警，由调用方结合页面诊断处理。

## 7. 登录态接入

分享包不读原工程数据库。调用前先把接收方自己的 Playwright storageState 放入内存：

```js
import { setStorageState } from './src/index.js';
setStorageState(accountId, JSON.parse(storageStateJson));
```

生产接入时建议把 `src/runtime/storage.js` 换成接收方的加密凭证库，并满足：

- 按租户和账号隔离；
- 静态加密、传输加密、最小权限；
- 日志禁止输出 Cookie、localStorage、请求签名和完整响应载荷；
- 浏览器任务结束后回写更新后的 storageState；
- 支持吊销、过期与审计。

## 8. 运行示例

先安装依赖并检查：

```bash
npm install
npm run check
```

只有在接收方自有测试环境中，才复制 `.env.example` 为 `.env` 并准备自己的登录态文件和图片。调用：

```bash
node examples/publish.js sohu demo-account ./private/storage-state.json ./private/article.json
```

搜狐和值得买是 API-only；头条需要浏览器动态参数；网易只有遇到动态 token 或验证码恢复时才会启用浏览器。示例没有幂等数据库，重复运行可能重复发文，因此只适合受控测试，不适合直接部署。

## 9. 接入方必须补齐的生产能力

- 幂等键：至少按“内容 ID + 平台 + 账号”唯一。
- 状态机：pending、processing、reviewing、published、failed、unknown。
- 限流与串行：同一账号一次只运行一个发布任务。
- 未知结果核验：先查平台列表，再允许重试。
- 人工确认：外部提交前展示最终标题、正文、图片和目标账号。
- 审计：记录操作者、内容 ID、平台、阶段、结果和时间，但不记录凭证。
- 失败分级：登录失效、内容拒绝、额度耗尽、临时网络错误、结果未知分别处理。
- 选择器巡检：平台改版时优先更新各自 `selectors.js`。

## 10. 测试与维护

`npm test` 覆盖载荷组装、图片 URL 替换、状态映射、标题约束、HTTP 重试、富文本缺图门禁和网易验证码恢复的纯函数部分。它不能替代真实平台沙箱验证。

平台改版排查顺序：先确认登录态；再抓取失败请求的路径、状态码和无敏感字段摘要；然后对比接口字段；最后才调整选择器或恢复流程。任何真实 Cookie、token、代理凭证和第三方识别 key 都只能通过接收方的秘密管理系统注入。
