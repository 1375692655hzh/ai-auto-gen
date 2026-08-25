/**
 * 搜狐号 adapter —— v4 后台，Quill 编辑器（2026-07 实测）
 *
 * 注入策略：Quill clipboard API 直注优先（格式清洗与真实粘贴一致），
 * 失败降级 synthetic paste，再降级 contenteditable execCommand。
 */
import { BaseAdapter } from '../base.js';
import { mustFind, firstVisible } from '../helpers.js';
import { typeHuman, sleep } from '../../browser/humanize.js';
import { injectByQuill, injectBySyntheticPaste, injectByExecCommand, requireCompleteInjection } from '../richtext.js';
import {
  SohuApiClient, SohuApiError, buildSohuPublishPayload, replaceSohuImageSources,
} from './api.js';
import { NeedLoginError, PublishRejectedError, PublishResultUnknownError } from '../base.js';
import S from './selectors.js';

export default class SohuAdapter extends BaseAdapter {
  static id = 'sohu';
  static name_ = '搜狐号';
  static homeUrl = S.homeUrl;
  static loginUrl = S.loginUrl;
  static selectors = S;
  static apiOnly = true;
  // 即时信号不明确时尽快释放串行队列，后续交给持久化核验器。
  static detectionTimeoutMs = 60 * 1000;

  async loginCheck(page) {
    await page.goto(S.homeUrl, { waitUntil: 'domcontentloaded' });
    await sleep(3000);
    if (S.loginUrlPattern.test(page.url())) return false;
    // URL 未跳登录页不代表已登录，可能页面内弹扫码框；再探测已登录标志
    const probe = await firstVisible(page, S.loggedInProbe, { timeoutMs: 8000 });
    return !!probe;
  }

  /** 搜狐号会话接口：公开昵称优先来自 account/pending，register-info 作为兜底。 */
  async getAccountProfile(page) {
    try {
      const profile = await page.evaluate(async () => {
        const fetchWithRetry = async (url) => {
          let lastError;
          for (let attempt = 1; attempt <= 3; attempt += 1) {
            try {
              const response = await fetch(url, { credentials: 'include' });
              if (![403, 408, 425, 429].includes(response.status) && response.status < 500) return response;
              lastError = new Error(`HTTP ${response.status}`);
              lastError.status = response.status;
            } catch (error) {
              lastError = error;
            }
            if (attempt < 3) await new Promise(resolve => setTimeout(resolve, 250 * (2 ** (attempt - 1))));
          }
          throw lastError;
        };
        const [accountResponse, registerResponse] = await Promise.all([
          fetchWithRetry('/mpbp/bp/account/info'),
          fetchWithRetry('/mpbp/bp/account/register-info'),
        ]);
        const accountPayload = accountResponse.ok ? await accountResponse.json() : {};
        const registerPayload = registerResponse.ok ? await registerResponse.json() : {};
        const account = accountPayload?.data || registerPayload?.data?.account || {};
        const user = registerPayload?.data?.user || {};
        const phone = String(user.mobile || '').trim();
        return {
          profileName: String(account.nickName || '').trim(),
          username: String(user.mobile || user.email || user.userCode || '').trim(),
          ...(phone ? { phone } : {}),
        };
      });
      if (profile?.profileName || profile?.username) return profile;
    } catch { /* 会话接口临时失败时降级页面昵称 */ }
    return await super.getAccountProfile(page);
  }

  async openEditor(page) {
    await page.goto(S.editorUrl, { waitUntil: 'domcontentloaded' });
    await mustFind(page, S.titleInput, '标题输入框', { timeoutMs: 20000 });
  }

  async fillTitle(page, title) {
    const { locator } = await mustFind(page, S.titleInput, '标题输入框');
    await typeHuman(locator, title);
  }

  async fillBody(page, article) {
    const { html, text } = article;
    const quillSel = S.quillEditor[0];
    await mustFind(page, S.quillEditor, 'Quill 编辑区', { timeoutMs: 15000 });

    // 1) Quill clipboard API 直注
    let result = await injectByQuill(page, quillSel, html);
    if (!result.ok) {
      // 2) synthetic paste → 3) execCommand
      result = await injectBySyntheticPaste(page, quillSel, html, text);
      if (!(result.ok && result.defaultPrevented)) {
        result = await injectByExecCommand(page, quillSel, html);
      }
    }
    if (!result?.ok) throw new Error(`正文注入失败: ${result?.reason || '所有注入方案均未成功'}`);
    await sleep(2000);

    // 图片门禁：dataURL 转存是异步的，先轮询等到齐；等满仍缺图就不发，
    // 避免平台上出现缺图的残篇（任务会以「3/7 张」这样的结论落为失败）。
    await requireCompleteInjection(page, quillSel, {
      platform: 'sohu',
      expectedImages: article.images.length,
      tempDir: article.tempDir,
    });
  }

  async clickPublish(page) {
    const quota = await firstVisible(page, S.dailyQuotaExhausted, { timeoutMs: 1500 });
    if (quota) {
      const error = new Error('搜狐号今日发布额度已用完（平台显示“今天还能发 0 篇文章”），内容已保留为草稿，请明天再发布');
      error.status = 429;
      error.code = 'DAILY_LIMIT_EXCEEDED';
      throw error;
    }
    await super.clickPublish(page);
  }

  async apiCheck(accountId) {
    try {
      const client = new SohuApiClient(accountId);
      return await client.checkLogin();
    } catch (error) {
      if (error instanceof SohuApiError) return { ok: false, profile: null, error };
      throw error;
    }
  }

  async createApiClient(accountId) {
    return new SohuApiClient(accountId);
  }

  /** API 发布路径；不创建浏览器 context，不打开编辑器，也不依赖页面状态。 */
  async publish(_page, article, hooks = {}) {
    const onStage = hooks.onStage || (() => {});
    let client;
    let profile;

    await onStage('login-check');
    try {
      client = new SohuApiClient(hooks.accountId);
      const checked = await client.checkLogin();
      profile = checked.profile;
      await hooks.onLoginChecked?.(checked.ok, checked.accountStatus);
      if (!checked.ok) {
        if (checked.accountStatus === 'banned') {
          throw new PublishRejectedError(`搜狐号${profile?.statusName || '已查封'}，内容未提交`);
        }
        throw new NeedLoginError(this.name);
      }
    } catch (error) {
      if (!(error instanceof NeedLoginError) && !(error instanceof PublishRejectedError)) {
        await hooks.onLoginChecked?.(false);
      }
      if (error instanceof NeedLoginError) throw error;
      if (error instanceof SohuApiError) throw new NeedLoginError(this.name);
      throw error;
    }

    await onStage('open-editor', '搜狐 API 直发');
    await onStage('fill-title');
    await onStage('fill-body');
    let html = article.html;
    const imageUrls = [];
    for (const image of article.images || []) {
      const uploaded = await client.uploadImage(image.path, image.contentType || 'application/octet-stream');
      imageUrls.push(uploaded.url);
    }
    if (imageUrls.length) html = replaceSohuImageSources(html, imageUrls);

    await onStage('fill-meta');
    const payload = buildSohuPublishPayload({
      accountId: client.accountId,
      title: article.title,
      html,
      channelId: profile?.channelId || 28,
      tags: article.tags,
    });

    if (hooks.mode === 'confirm') {
      if (typeof hooks.createPreview !== 'function') throw new Error('人工确认模式缺少预览链接生成器');
      await hooks.createPreview();
      await onStage('waiting-confirm', '内容已准备，请打开预览链接确认发布');
      await hooks.waitConfirm();
    }

    await onStage('check-limit');
    const remaining = await client.getPublishLimit();
    if (remaining <= 0) {
      throw new PublishRejectedError('搜狐号今日发布额度已用完，内容未提交');
    }

    await onStage('click-publish');
    let response;
    try {
      response = await client.publishArticle(payload);
    } catch (error) {
      if (error instanceof SohuApiError && error.code === 3003) {
        throw new PublishRejectedError('搜狐号今日发布额度已用完，内容未提交');
      }
      if (error instanceof SohuApiError) throw new PublishRejectedError(error.message);
      throw error;
    }

    const newsId = Number(response?.data?.id || response?.data || 0) || 0;
    await onStage('detect-published');
    const result = await client.waitForPublication(article.title, {
      newsId,
      timeoutMs: this.detectionTimeoutMs,
    });
    if (!result) {
      throw new PublishResultUnknownError('搜狐已接受发布请求，列表暂未出现目标文章，系统将继续自动核验');
    }
    if (result.status === 'failed') throw new PublishRejectedError(result.detail);
    if (result.status === 'draft') throw new PublishRejectedError('搜狐内容仍为草稿，平台未接受发布');
    if (result.status === 'unknown') throw new PublishResultUnknownError(result.detail);
    await onStage(result.status === 'published' ? 'published' : 'reviewing', result.url);
    return { status: result.status, url: result.url || '', detail: result.detail || '' };
  }

}
