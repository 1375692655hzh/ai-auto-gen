/**
 * BaseAdapter —— 平台发布流程统一编排
 *
 * pipeline: loginCheck → openEditor → fillTitle → fillBody → fillMeta
 *           → mode=confirm 时生成预览链接并暂停等待确认
 *           → clickPublish（机器点平台「发布」按钮）
 *           → detectPublished（多信号等待）→ 返回发布链接
 *
 * page 由上层的 withAccountContext 提供（storageState 注入的临时 context）。
 * 子类只实现平台差异：loginCheck / openEditor / fillTitle / fillBody /
 * fillMeta / detectPublished / fetchArticleUrl，选择器集中在各自 selectors.js。
 */
import { firstVisible } from './helpers.js';
import { findPublicationInManagement, pollPublicationInManagement } from './publicationStatus.js';
import { sleep } from '../browser/humanize.js';

export class NeedLoginError extends Error {
  constructor(platform) {
    super(`${platform} 登录态失效，需要重新登录`);
    this.code = 'NEED_LOGIN';
  }
}

export class ConfirmCancelledError extends Error {
  constructor(reason = '用户取消发布') {
    super(reason);
    this.code = 'CONFIRM_CANCELLED';
  }
}

/** 已经点击平台发布按钮，但平台没有返回可确认的结果；交给后台核验器继续查。 */
export class PublishResultUnknownError extends Error {
  constructor(message = '已提交发布，但暂未检测到平台结果，系统将继续自动核验') {
    super(message);
    this.code = 'PUBLISH_RESULT_UNKNOWN';
  }
}

/** 平台明确返回审核未通过/发布失败。 */
export class PublishRejectedError extends Error {
  constructor(message = '平台返回发布失败') {
    super(message);
    this.code = 'PUBLISH_REJECTED';
  }
}

export class BaseAdapter {
  /** 子类覆盖 */
  static id = '';
  static name = '';
  static homeUrl = '';
  static loginUrl = '';
  /** 平台是否支持控制台扫码登录（无二维码入口/有滑块拦截的平台设 false，走 companion 本机登录） */
  static supportsQrLogin = true;
  /** 子类的 selectors.js 默认导出（clickPublish/loginFlow 用） */
  static selectors = null;
  /** 点击发布后等待平台即时信号的最长时间。 */
  static detectionTimeoutMs = 10 * 60 * 1000;
  /** 只收到“提交成功”而还没有公开链接时的平台状态。 */
  static submissionStatus = 'reviewing';

  constructor() {
    this.id = this.constructor.id;
    this.name = this.constructor.name_ || this.constructor.name;
    this.selectors = this.constructor.selectors;
    this.detectionTimeoutMs = this.constructor.detectionTimeoutMs;
    this.submissionStatus = this.constructor.submissionStatus;
  }

  /** 打开后台首页判断登录态；返回 true=已登录 */
  async loginCheck(_page) { throw new Error('not implemented'); }
  /** 从已登录会话读取账号资料；默认以页面昵称兜底，平台可覆盖为会话接口。 */
  async getAccountProfile(page) {
    const selectors = this.selectors?.profileName || [];
    for (const selector of selectors) {
      try {
        const text = await page.locator(selector).first().innerText({ timeout: 1500 });
        const name = String(text || '').replace(/\s+/g, ' ').trim();
        if (name) return { profileName: name, username: '' };
      } catch { /* 平台改版或当前页未渲染该区域，继续尝试 */ }
    }
    return { profileName: '', username: '' };
  }
  async getProfileName(page) { return (await this.getAccountProfile(page)).profileName; }
  async openEditor(_page) { throw new Error('not implemented'); }
  async fillTitle(_page, _title) { throw new Error('not implemented'); }
  async fillBody(_page, _article) { throw new Error('not implemented'); }
  /** 分类/标签/封面等平台特有项，默认无操作 */
  async fillMeta(_page, _article) {}

  /** 上传主题匹配的本地图片到平台封面控件。 */
  async uploadCover(page, article, selectors = [], triggers = []) {
    const coverPath = article.topicImage?.path;
    if (!coverPath || !selectors.length) return false;
    for (const selector of triggers) {
      const trigger = page.locator(selector).first();
      try {
        if (!await trigger.count() || !await trigger.isVisible()) continue;
        await trigger.click();
        await sleep(500);
        for (const inputSelector of selectors) {
          const input = page.locator(inputSelector).first();
          if (await input.count() && await input.isEnabled()) {
            await input.setInputFiles(coverPath);
            await sleep(800);
            await this.dismissUploadSuccess(page);
            if (!await this.setUploadedCover(page)) return false;
            await page.keyboard.press('Escape').catch(() => {});
            await sleep(300);
            return true;
          }
        }
      } catch { /* 继续尝试其它封面入口 */ }
    }
    for (const selector of selectors) {
      const input = page.locator(selector).first();
      try {
        if (await input.count() && await input.isEnabled()) {
          await input.setInputFiles(coverPath);
          await sleep(800);
          await this.dismissUploadSuccess(page);
          if (!await this.setUploadedCover(page)) return false;
          await page.keyboard.press('Escape').catch(() => {});
          await sleep(300);
          return true;
        }
      } catch { /* 页面改版或控件不是封面上传，继续尝试候选 */ }
    }
    console.warn(`[${this.id}] 未找到封面上传控件，图片未上传：${coverPath}`);
    return false;
  }

  /** 上传成功后平台仍要求绑定封面，自动点击当前图片卡片的封面按钮。 */
  async setUploadedCover(page) {
    const button = page.getByText('设为封面图', { exact: true }).last();
    try {
      await button.waitFor({ state: 'visible', timeout: 10000 });
      // 该平台的封面卡片是自定义组件，直接调用卡片按钮自身的 click 事件，
      // 比点击覆盖在图片上的文本节点更容易触发 Vue 组件状态更新。
      await button.evaluate(element => element.click());
      await sleep(500);
      console.log(`[${this.id}] 已自动设置上传图片为封面图`);
      return true;
    } catch { /* 页面改版或图片卡片未完成渲染 */ }
    console.warn(`[${this.id}] 图片已上传但未找到「设为封面图」按钮`);
    return false;
  }

  /** 平台上传成功提示会遮住发布按钮，需在继续流程前关闭。 */
  async dismissUploadSuccess(page) {
    const selectors = [
      '.el-overlay-dialog button:has-text("我知道了")',
      '[role="dialog"] button:has-text("我知道了")',
      'button:has-text("我知道了")',
      'text=我知道了',
    ];
    for (const selector of selectors) {
      const button = page.locator(selector).first();
      try {
        if (await button.count() && await button.isVisible()) {
          await button.click();
          await sleep(300);
          return true;
        }
      } catch { /* 弹窗可能刚好切换，继续尝试下一候选 */ }
    }
    return false;
  }
  /** 打开作品管理列表，按容错标题匹配平台真实状态。 */
  async fetchPublicationStatus(page, title) {
    return await findPublicationInManagement(page.context(), this.selectors, title);
  }

  /** 兼容旧调用方：去作品管理列表补公开链接。 */
  async fetchArticleUrl(page, title) {
    return (await this.fetchPublicationStatus(page, title))?.url || '';
  }

  /** 等待跳转/提示/管理列表中的任一可信发布结果。 */
  async detectPublished(page, article) {
    const S = this.selectors || {};
    const timeout = this.detectionTimeoutMs;
    const never = promise => promise.catch(() => new Promise(() => {}));
    const signals = [sleep(timeout).then(() => null)];

    if (S.publishSuccessUrlPattern) {
      signals.push(never(page.waitForURL(S.publishSuccessUrlPattern, { timeout }).then(() => ({
        status: S.publicSuccessUrl ? 'published' : this.submissionStatus,
        url: S.publicSuccessUrl ? page.url() : '',
        detail: '平台页面已跳转',
      }))));
    }
    for (const selector of S.publishSuccessToast || []) {
      signals.push(never(page.locator(selector).first().waitFor({ state: 'visible', timeout }).then(() => ({
        status: this.submissionStatus,
        url: '',
        detail: '平台已提示提交成功',
      }))));
    }
    if (S.managementUrl) {
      signals.push(never(pollPublicationInManagement(this, page, article.title, timeout)));
    }
    return await Promise.race(signals);
  }

  /** 机器点「发布」按钮；子类可覆写。处理可选的二次确认弹窗。 */
  async clickPublish(page) {
    const S = this.selectors || {};
    if (!S.publishButton?.length) throw new Error(`${this.name} 未配置 publishButton 选择器`);
    const btn = await firstVisible(page, S.publishButton, { timeoutMs: 10000 });
    if (!btn) throw new Error(`找不到「发布」按钮（selectors: ${S.publishButton.join(' | ')}）`);
    await sleep(800 + Math.random() * 700);
    await btn.locator.hover().catch(() => {});
    await sleep(200 + Math.random() * 300);
    try {
      await btn.locator.click();
    } catch (error) {
      // 某些平台的图片抽屉没有关闭按钮，会拦截按钮的鼠标命中；
      // 先收起抽屉，再由 Playwright 触发同一个发布按钮事件。
      if (!String(error?.message || '').includes('intercepts pointer events')) throw error;
      await page.keyboard.press('Escape').catch(() => {});
      await sleep(300);
      await btn.locator.click({ force: true });
    }
    // 可选的二次确认弹窗（改版新增时在 selectors.publishConfirmDialog 补）
    if (S.publishConfirmDialog?.length) {
      const confirm = await firstVisible(page, S.publishConfirmDialog, { timeoutMs: 4000 });
      if (confirm) {
        await sleep(500 + Math.random() * 500);
        await confirm.locator.click();
      }
    }
  }

  /**
   * 执行完整发布流程。
   * @param {import('playwright').Page} page - withAccountContext 提供的页面
   * @param {object} article - { title, html, text, images, category, tags }
   * @param {object} hooks
   *   - onStage(stage, detail)   状态回写/日志
   *   - onLoginChecked(ok)       登录检查完成后立即持久化账号健康状态
   *   - mode: 'auto' | 'confirm' 默认 auto
   *   - createPreview()          confirm 模式：生成可分享的预览链接
   *   - waitConfirm()            confirm 模式：等控制台确认；拒绝=取消发布
   * @returns {{ status: string, url: string, detail?: string }} 平台发布结果
   */
  async publish(page, article, hooks = {}) {
    const onStage = hooks.onStage || (() => {});
    const mode = hooks.mode || 'auto';

    await onStage('login-check');
    const loggedIn = await this.loginCheck(page);
    await hooks.onLoginChecked?.(loggedIn);
    if (!loggedIn) throw new NeedLoginError(this.name);

    await onStage('open-editor');
    await this.openEditor(page);

    await onStage('fill-title');
    await this.fillTitle(page, article.title);

    await onStage('fill-body');
    await this.fillBody(page, article);

    await onStage('fill-meta');
    await this.fillMeta(page, article);

    if (mode === 'confirm') {
      if (typeof hooks.createPreview !== 'function') throw new Error('人工确认模式缺少预览链接生成器');
      await hooks.createPreview();
      await onStage('waiting-confirm', '内容已填充，请打开预览链接确认发布');
      await hooks.waitConfirm(); // 取消/超时会抛错，走上层失败流程
    }

    await onStage('click-publish');
    try {
      await this.clickPublish(page);
    } catch (error) {
      await hooks.onDiagnostic?.('click-publish-error', page, error);
      throw error;
    }

    await onStage('detect-published');
    const result = await this.detectPublished(page, article);
    if (!result) {
      await hooks.onDiagnostic?.('publish-result-unknown', page);
      throw new PublishResultUnknownError();
    }

    let finalResult = { status: result.status || this.submissionStatus, url: result.url || '', detail: result.detail || '' };
    if (!finalResult.url) {
      await onStage('fetch-url');
      try {
        const lookup = await this.fetchPublicationStatus(page, article.title);
        if (lookup) finalResult = { ...finalResult, ...lookup };
      } catch { /* 即时补链失败交给后台核验器 */ }
    }
    if (finalResult.status === 'failed') {
      throw new PublishRejectedError(finalResult.detail || '平台返回审核未通过或发布失败');
    }
    if (finalResult.status === 'draft') {
      throw new PublishRejectedError(`${this.name} 作品管理页仍显示为草稿，发布未提交成功；请检查平台额度或页面校验提示`);
    }
    if (finalResult.status === 'unknown') {
      await hooks.onDiagnostic?.('publish-result-unknown', page);
      throw new PublishResultUnknownError();
    }
    await onStage(finalResult.status === 'published' ? 'published' : 'reviewing', finalResult.url);
    return finalResult;
  }
}
