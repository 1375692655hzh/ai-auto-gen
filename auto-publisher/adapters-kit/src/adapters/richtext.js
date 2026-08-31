/**
 * 富文本注入工具 —— 三级降级策略
 *
 * 1. synthetic paste：构造 DataTransfer 派发 ClipboardEvent('paste')，
 *    走编辑器自身的粘贴清洗/图片转存逻辑，不占系统剪贴板（主方案）。
 * 2. 编辑器 JS API 直注：UEditor setContent / execCommand insertHTML。
 * 3. 系统剪贴板 + 真实 Cmd+V：对付拦截 synthetic 事件的编辑器（兜底）。
 *
 * frame 参数支持 Page 或 FrameLocator 场景下传入对应 Frame（UEditor 正文在 iframe 里）。
 */

/** 方案 1：对目标元素派发 synthetic paste */
export async function injectBySyntheticPaste(frame, selector, html, plainText) {
  return await frame.evaluate(({ selector, html, plainText }) => {
    const target = document.querySelector(selector);
    if (!target) return { ok: false, reason: `selector 未命中: ${selector}` };
    target.focus();
    const dt = new DataTransfer();
    dt.setData('text/html', html);
    dt.setData('text/plain', plainText);
    const event = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
    const dispatched = target.dispatchEvent(event);
    return { ok: true, defaultPrevented: !dispatched || event.defaultPrevented };
  }, { selector, html, plainText });
}

/** 方案 2c：Quill 实例直注（走 clipboard 模块，格式清洗与真实粘贴一致） */
export async function injectByQuill(frame, selector, html) {
  return await frame.evaluate(({ selector, html }) => {
    const editorEl = document.querySelector(selector);
    if (!editorEl) return { ok: false, reason: `selector 未命中: ${selector}` };
    const container = editorEl.closest('.ql-container') || editorEl.parentElement;
    const quill = container?.__quill
      || (window.Quill?.find ? window.Quill.find(container) : null);
    if (!quill?.clipboard?.dangerouslyPasteHTML) {
      return { ok: false, reason: '未拿到 Quill 实例' };
    }
    quill.clipboard.dangerouslyPasteHTML(html, 'user');
    return { ok: true };
  }, { selector, html });
}

/** 方案 2a：UEditor 实例直注 */
export async function injectByUEditor(frame, html) {
  return await frame.evaluate((html) => {
    const UE = window.UE;
    if (!UE || !UE.instants) return { ok: false, reason: '页面无 UEditor 实例' };
    const editor = Object.values(UE.instants)[0];
    if (!editor?.setContent) return { ok: false, reason: 'UEditor 实例无 setContent' };
    editor.setContent(html);
    return { ok: true };
  }, html);
}

/** 方案 2b：contenteditable 聚焦后 execCommand insertHTML */
export async function injectByExecCommand(frame, selector, html) {
  return await frame.evaluate(({ selector, html }) => {
    const target = document.querySelector(selector);
    if (!target) return { ok: false, reason: `selector 未命中: ${selector}` };
    target.focus();
    document.execCommand('selectAll', false);
    const ok = document.execCommand('insertHTML', false, html);
    return { ok };
  }, { selector, html });
}

/** 方案 3：系统剪贴板 + 真实 Cmd+V（需 context.grantPermissions(['clipboard-read','clipboard-write'])） */
export async function injectByRealPaste(page, locator, html, plainText) {
  await page.evaluate(async ({ html, plainText }) => {
    const item = new ClipboardItem({
      'text/html': new Blob([html], { type: 'text/html' }),
      'text/plain': new Blob([plainText], { type: 'text/plain' }),
    });
    await navigator.clipboard.write([item]);
  }, { html, plainText });
  await locator.click();
  await page.keyboard.press(process.platform === 'darwin' ? 'Meta+KeyV' : 'Control+KeyV');
  return { ok: true };
}

/** 统计目标区域内 img 数量，用于注入后校验图片是否齐 */
export async function countImages(frame, selector) {
  return await frame.evaluate((selector) => {
    const target = document.querySelector(selector);
    return target ? target.querySelectorAll('img').length : -1;
  }, selector);
}

/** 统计目标区域内的正文字数（去掉所有空白），用于判断正文是否真的注入进去了。 */
export async function countBodyChars(frame, selector) {
  return await frame.evaluate((selector) => {
    const target = document.querySelector(selector);
    if (!target) return -1;
    return (target.innerText || target.textContent || '').replace(/\s/g, '').length;
  }, selector);
}

export class InjectionVerificationError extends Error {
  constructor(message, { platform, expectedImages, actualImages, tempDir } = {}) {
    super(message);
    this.name = 'InjectionVerificationError';
    this.code = 'INJECTION_INCOMPLETE';
    this.platform = platform;
    this.expectedImages = expectedImages;
    this.actualImages = actualImages;
    this.tempDir = tempDir;
  }
}

/**
 * 注入后校验图片是否齐 —— 不齐就不允许继续点发布。
 *
 * 之前这里只打一句 console.warn 然后照常发布，结果是平台上出现缺图的残篇，
 * 而运营完全看不到警告（日志只在服务器 stdout）。改成硬门禁后，缺图的任务
 * 落为失败并带上「3/7 张」这样的结论，运营在发布管理页就能看到。
 *
 * 图片是 dataURL 交给编辑器异步转存的，数量会延迟到齐，所以这里轮询等待，
 * 只有等满 timeoutMs 仍然不齐才判失败。
 */
export async function verifyInjectedImages(frame, selector, {
  platform = '', expectedImages = 0, tempDir = '', timeoutMs = 15000, intervalMs = 750,
} = {}) {
  if (!expectedImages) return { ok: true, count: 0, expected: 0 };
  const deadline = Date.now() + Math.max(0, timeoutMs);
  let count = await countImages(frame, selector);
  // count < 0 表示选择器没命中，说明正文区已经不是注入时那个元素，交给调用方判断
  while (count >= 0 && count < expectedImages && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, intervalMs));
    count = await countImages(frame, selector);
  }
  if (count < 0) {
    return { ok: false, count, expected: expectedImages, reason: 'selector-missed' };
  }
  if (count < expectedImages) {
    return { ok: false, count, expected: expectedImages, reason: 'missing-images' };
  }
  return { ok: true, count, expected: expectedImages };
}

/**
 * 校验不通过就抛错，阻断后续的发布点击。
 * selector 没命中时只警告不阻断：正文注入本身已经成功过一次，
 * 大概率是编辑器把内容搬进了别的容器，这时候贸然判失败会误伤正常发布。
 */
export async function requireCompleteInjection(frame, selector, options = {}) {
  const result = await verifyInjectedImages(frame, selector, options);
  if (result.ok) return result;
  const { platform = '', tempDir = '' } = options;
  if (result.reason === 'selector-missed') {
    console.warn(`[${platform}] 注入后未能定位正文区（${selector}），跳过图片校验`);
    return result;
  }
  throw new InjectionVerificationError(
    `正文图片未全部注入：编辑器内 ${result.count} 张，文档共 ${result.expected} 张。`
    + `为避免发出缺图的文章，本次没有提交${tempDir ? `；图片本地副本在 ${tempDir}` : ''}`,
    { platform, expectedImages: result.expected, actualImages: result.count, tempDir },
  );
}
