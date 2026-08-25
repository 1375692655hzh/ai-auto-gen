/**
 * 什么值得买（post.smzdm.com）选择器 —— 平台改版时只改这个文件
 *
 * 2026-07-13 已用线上登录态校准：/tougao/ 是创作中心，点击「发布新文章」
 * 进入动态 /edit/<id> 地址，编辑器为 ProseMirror。全站有 JS 指纹盾（probe.js/buid），
 * 必须 headful + 真实登录态。
 */
export default {
  // 登录判断：未登录访问投稿页会 302 到 zhiyou.smzdm.com/user/login
  homeUrl: 'https://post.smzdm.com/tougao/',
  loginUrl: 'https://zhiyou.smzdm.com/user/login/?redirect_to=https%3A%2F%2Fpost.smzdm.com%2Ftougao%2F',
  loginUrlPattern: /zhiyou\.smzdm\.com\/user\/login/,
  loggedInProbe: [
    '[class*="avatar"]',
    '[class*="user-info"]',
    '[class*="username"]',
  ],
  profileName: [
    '[class*="user-info"] [class*="nickname"]',
    '[class*="user-info"] [class*="name"]',
    '[class*="username"]',
  ],

  // /tougao/ 是创作中心，发文入口 href 指向动态编辑地址。
  editorUrl: 'https://post.smzdm.com/tougao/',
  newArticleLink: [
    'a.release-new',
    'a:has-text("发布新文章")',
  ],
  editorIntroDismiss: [
    '.upgrade-tip-btn',
    '.upgrade-tip :text("立即体验")',
  ],
  titleInput: [
    'textarea.article-title',
    'input[placeholder*="标题"]',
    'textarea[placeholder*="标题"]',
    '[class*="title"] input',
  ],
  // 正文编辑区候选：主文档 contenteditable / Quill / ProseMirror
  editorBody: [
    '.ProseMirror',
    '.ql-editor',
    '[contenteditable="true"]',
  ],
  // UEditor 场景：正文在 iframe 里（iframe 定位 + 帧内 body）
  ueditorFrame: [
    'iframe[id*="ueditor"]',
    '.edui-editor iframe',
    'iframe.edui-editor-iframebody',
  ],
  ueditorBody: 'body[contenteditable="true"], body.view',
  coverUpload: [
    'input[type="file"][name*="cover"]',
    '[class*="cover"] input[type="file"]',
    'input[type="file"][accept*="image"]',
    'input[type="file"]',
  ],
  coverTriggers: [
    'button:has-text("添加长图")',
    'text=添加长图',
  ],
  coverSquareTriggers: [
    'button:has-text("添加方图")',
    'text=添加方图',
  ],

  publishButton: [
    'button.publish-btn',
    'button:has-text("提交")',
    'a:has-text("发布")',
    '[class*="publish"] button',
  ],
  publishConfirmDialog: [
    '.el-message-box button:has-text("确定")',
    'button:has-text("确认发布")',
    'button:has-text("确定")',
  ],

  // 扫码登录：登录页点微信第三方登录 → open.weixin.qq.com 出二维码（同搜狐模式）。
  // 值得买 App 扫码登录未确认，暂走微信。
  qrEntry: [
    'a[href*="type=weixin"]',
    '[class*="weixin"]',
    '[class*="wechat"]',
    'a:has-text("微信")',
  ],
  qrImage: [
    'img[src*="/connect/qrcode/"]',
    '.impowerBox .qrcode',
    'img.web_qrcode_img',
    '[class*="qrcode"] img',
  ],

  // 发布成功信号：值得买先审后发，成功后一般提示进入审核，拿不到即时链接。
  publishSuccessUrlPattern: /post\.smzdm\.com\/p\//,
  publicSuccessUrl: true,
  publishSuccessToast: [
    'text=/发布成功|提交成功|审核|已提交/',
  ],

  // 我的文章列表（2026-07-13 实测）：
  // 已发布文章链接形如 https://post.smzdm.com/p/<短id>/
  managementUrl: 'https://zhiyou.smzdm.com/user/article/',
  articleRow: [
    '.pandect-content-stuff.common.article',
    '[class*="article-item"]',
    '[class*="list-item"]',
    'li[class*="item"]',
  ],
  articleTitle: [
    '.p-pandect-content-title > a',
    'a.isPreview_',
    'a[href*="post.smzdm.com/p/"]',
    '[class*="title"]',
  ],
  articleLink: [
    '.p-pandect-content-title > a[href*="post.smzdm.com/p/"]',
    'a.isPreview_',
    'a[href*="post.smzdm.com/p/"]',
  ],
};
