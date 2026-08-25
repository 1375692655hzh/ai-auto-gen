/**
 * 网易号（mp.163.com）选择器 —— 平台改版时只改这个文件
 *
 * 2026-07 依据线上 JS bundle 静态分析整理（subscribe_v4 SPA，Draft.js 编辑器），
 * 尚未用真实登录态实测校准。登录走网易通行证 URS iframe；全站挂网易易盾
 * 设备/行为风控（YiDunProtector），必须 headful + 真实登录态。
 *
 * 2026-07-13 已用线上登录态复核新版编辑器。
 */
export default {
  // 登录判断：未登录访问后台会跳 login.html
  homeUrl: 'https://mp.163.com/subscribe_v4/index.html#/',
  loginUrl: 'https://mp.163.com/login.html',
  loginUrlPattern: /mp\.163\.com\/login|dy\.163\.com\/wemedia\/login/,
  loggedInProbe: [
    '[class*="user-info"]',
    '[class*="avatar"]',
    '[class*="header-user"]',
  ],
  profileName: [
    '.topBar__user span',
    '.homeV4__userInfo__tname .ellipse-1',
    '[class*="header-user"] [class*="name"]',
    '[class*="user-info"] [class*="name"]',
  ],

  // 图文发布页（SPA hash 路由）
  editorUrl: 'https://mp.163.com/subscribe_v4/index.html#/article-publish',
  titleInput: [
    'input[placeholder*="请输入标题"]',
    'textarea[placeholder*="请输入标题"]',
    'input[name="title"]',
  ],
  accountReviewNotice: [
    'text=您的账号信息正在审核中，请耐心等待哦',
    'text=/账号信息.*审核中/',
  ],
  // Draft.js 编辑区：舞台 .rich-editor-stage 内的 contenteditable
  editorBody: [
    '.rich-editor-stage [contenteditable="true"]',
    '.rich-editor-stage .public-DraftEditor-content',
    '.public-DraftEditor-content',
    '[contenteditable="true"]',
  ],
  captchaRoot: '#captcha',
  captchaRefresh: ['#yidun_refresh', '.yidun_refresh'],
  captchaBackground: '.yidun_bgimg',

  // 封面模式：候选「自动」减少人工干预；新版页面已没有分类必填项。
  coverAuto: [
    'label:has-text("自动")',
    'text=自动获取',
  ],
  coverUpload: [
    'input[type="file"][name*="cover"]',
    '[class*="cover"] input[type="file"]',
    'input[type="file"][accept*="image"]',
  ],
  publishButton: [
    'button.primary_button',
    '[class*="publish-btn"]',
  ],
  // 二次弹窗注意：主按钮 okText 是「继续编辑」，「确认发布」才是要点的那个
  publishConfirmDialog: [
    'button:has-text("确认发布")',
    '[class*="modal"] button:has-text("确认发布")',
  ],

  // 扫码登录：二维码（若有）由 URS iframe 内部渲染，qrFrame 让 loginFlow
  // 进 iframe 找；入口通常是 iframe 右上角二维码角标（未确认，兜底整页截图）
  qrFrame: [
    '#login-URS-iframe iframe',
    'iframe[src*="urs"]',
    'iframe[src*="reg.163.com"]',
  ],
  qrEntry: [
    '[class*="qrcode"]',
    '[class*="corner"]',
    '[class*="scan"]',
  ],
  qrImage: [
    '[class*="qrcode"] img',
    '[class*="qrcode"] canvas',
    'img[src*="qrcode"]',
  ],

  // 发布成功信号：「发布成功,即将跳转到内容管理页」→ #/content-manage
  publishSuccessUrlPattern: /#\/content-manage/,
  publishSuccessToast: [
    'text=/发布成功/',
  ],

  // 内容管理（补链用）：已发布文章链接形如 https://www.163.com/dy/article/<docId>.html
  managementUrl: 'https://mp.163.com/subscribe_v4/index.html#/content-manage',
  articleRow: [
    '[class*="article-item"]',
    '[class*="content-item"]',
    '[class*="list-item"]',
  ],
  articleTitle: [
    'a[href*="163.com/dy/article/"]',
    '[class*="title"]',
  ],
  articleLink: [
    'a[href*="163.com/dy/article/"]',
  ],
};
