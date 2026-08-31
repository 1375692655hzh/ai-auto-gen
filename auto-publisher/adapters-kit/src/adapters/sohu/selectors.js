/**
 * 搜狐号（mp.sohu.com）选择器 —— 平台改版时只改这个文件
 *
 * 2026-07-11 已对照 v4 后台实测校准：
 * 后台为 /mpfe/v4/*，编辑器是 Quill（.ql-editor），非 UEditor。
 */
export default {
  // 登录判断：打开后台首页，未登录会跳登录页；已登录右上角有账号名（.user-head）
  homeUrl: 'https://mp.sohu.com/mpfe/v4/contentManagement/first/page',
  loginUrl: 'https://mp.sohu.com/mpfe/v4/contentManagement/first/page',
  loginUrlPattern: /login|passport\.sohu\.com/,
  loggedInProbe: [
    '.user-head',
    '.user-info-wrap',
    '.user-wrap',
  ],
  profileName: [
    '.user-head [class*="name"]',
    '.user-info-wrap [class*="name"]',
    '.user-head',
  ],

  // 图文编辑器（点「发布内容」黄色按钮即跳转到此 URL）
  editorUrl: 'https://mp.sohu.com/mpfe/v4/contentManagement/news/addarticle',
  titleInput: [
    'input[placeholder*="请输入标题"]',
    'input[placeholder*="标题"]',
  ],
  // Quill 富文本编辑区
  quillEditor: [
    '.ql-editor',
  ],
  editorContentEditable: [
    '[contenteditable="true"]',
  ],

  // 发布按钮（2026-07-11 实测：li.publish-report-btn，「发布」是 positive-button，
  // 「定时发布」是 negative-button，不能只按文本匹配）
  publishButton: [
    'li.publish-report-btn.positive-button',
    'li.publish-report-btn.active',
  ],
  dailyQuotaExhausted: [
    'text=/今天还能发\\s*0\\s*篇文章/',
  ],
  // 点发布后的二次确认弹窗（2026-07-11 实测：.alert-dialog「确认发布文章么？」，
  // 短文会附带「不足200字」提醒，确定按钮是 button.sure-btn）
  publishConfirmDialog: [
    '.alert-dialog button.sure-btn',
    '.alert-dialog button:has-text("确定")',
    '.el-message-box button:has-text("确定")',
  ],

  // 扫码登录（2026-07-11 实测：搜狐号本身无二维码登录，走第三方微信扫码：
  // 登录页 .wx-icon → 跳 open.weixin.qq.com/connect/qrconnect 出二维码）
  qrEntry: [
    '.login-dialog .other-area .wx-icon',
    '.wx-icon',
  ],
  qrImage: [
    'img[src*="/connect/qrcode/"]',
    '.impowerBox .qrcode',
    'img.web_qrcode_img',
  ],

  // 发布成功信号：发布后跳回内容管理页
  publishSuccessUrlPattern: /contentManagement\/first\/page/,
  publishSuccessToast: [
    'text=/发布成功|提交成功|已提交/',
  ],

  // 内容管理（补链用）：已发布文章链接形如 https://www.sohu.com/a/<id>_<accountId>
  managementUrl: 'https://mp.sohu.com/mpfe/v4/contentManagement/first/page?newsType=1',
  articleRow: [
    '[class*="article-item"]',
    '[class*="news-item"]',
    '[class*="content-item"]',
  ],
  articleTitle: [
    'a[href*="sohu.com/a/"]',
    '[class*="title"]',
  ],
  articleLink: [
    'a[href*="sohu.com/a/"]',
  ],
};
