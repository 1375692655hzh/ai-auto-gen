/**
 * 今日头条（mp.toutiao.com）选择器 —— 平台改版时只改这个文件
 *
 * 2026-07 依据开源自动化项目源码（mf-yang/toutiao-ops、axdlee/toutiao-publish）
 * 整理，尚未用真实登录态实测校准。后台 profile_v4，编辑器 ProseMirror，
 * UI 组件库为字节自研 byte-*（类名可能随版本变动）。
 */
export default {
  // 登录判断：已登录 URL 落在 /profile_v4/*；未登录跳 /auth/page/login 或 sso.toutiao.com
  homeUrl: 'https://mp.toutiao.com/profile_v4/',
  loginUrl: 'https://mp.toutiao.com/auth/page/login',
  loginUrlPattern: /auth\/page\/login|sso\.toutiao\.com/,
  loggedInProbe: [
    '.auth-avator-name', // 头条源码拼写如此（avator）
    '.auth-avator-img',
    '[class*="user-detail"]',
    '[class*="garr-avatar"]',
  ],
  profileName: [
    '.auth-avator-name',
    '[class*="user-detail"] [class*="name"]',
  ],

  // 图文发布页
  editorUrl: 'https://mp.toutiao.com/profile_v4/graphic/publish',
  titleInput: [
    'textarea[placeholder*="标题"]',
    'input[placeholder*="标题"]',
    '[class*="title"] textarea',
  ],
  // ProseMirror 正文编辑区
  proseMirror: [
    '.ProseMirror',
    '[contenteditable="true"]',
  ],

  // 封面模式（发布设置区）：正文有图时默认「单图」可直接用；
  // 无图文章需点「无封面」，否则发布校验不过
  coverNone: [
    'label:has-text("无封面")',
    'text=无封面',
  ],
  coverSingle: [
    'label:has-text("单图")',
    'text=单图',
  ],

  // 发布是多级：「预览并发布」→ 预览页「确认发布」→（可能的）弹窗「确定」
  publishButton: [
    'button:has-text("预览并发布")',
    'button:has-text("发布")',
  ],
  publishConfirmButton: [
    'button:has-text("确认发布")',
    '.byte-modal-wrapper button:has-text("发布")',
  ],
  publishConfirmDialog: [
    '.byte-modal-wrapper button:has-text("确定")',
    'button:has-text("确定")',
  ],

  // 扫码登录：登录页直接展示二维码（今日头条 App 扫），约 50s 自动刷新
  qrEntry: [], // 无需点入口
  qrImage: [
    '[class*="qrcode"] img',
    '[class*="qrcode"] canvas',
    '[class*="qr-code"]',
    '[class*="qrcode"]',
    '[class*="web-login"] [class*="scan"]',
  ],

  // 发布成功信号：跳回内容管理页
  publishSuccessUrlPattern: /profile_v4\/manage\/content/,
  publishSuccessToast: [
    'text=/发布成功|提交成功|已发布/',
  ],

  // 内容管理（补链用）：已发布文章链接形如 https://www.toutiao.com/item/<id>/
  managementUrl: 'https://mp.toutiao.com/profile_v4/manage/content/all',
  articleRow: [
    '.article-card-bone',
    '.article-card',
    '.genre-item.genre-item-in-all-tab',
    '[class*="content-item"]',
    '[class*="article-item"]',
    'table tbody tr',
  ],
  articleTitle: [
    'a.title',
    '.title-wrap a',
    'a[href*="toutiao.com/item/"]',
  ],
  articleLink: [
    'a[href*="toutiao.com/item/"]',
    'a[href*="toutiao.com/article/"]',
  ],
};
