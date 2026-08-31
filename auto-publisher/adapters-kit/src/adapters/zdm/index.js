/**
 * 什么值得买 adapter —— post.smzdm.com 原创文章投稿
 *
 * 编辑器为 ProseMirror：fillBody 先在主文档按
 * Quill/ProseMirror/contenteditable 候选注入，找不到再走 UEditor iframe
 * （实例直注 → 帧内 synthetic paste）。值得买先审后发，detectPublished
 * 多数情况拿不到即时链接，返回空 URL 由上层记「审核中」，事后补链。
 *
 * 平台内容门槛：原创 ≥800 字、配图 ≥5 张、建议 ≥1 个商品卡片，
 * 不达标可能被驳回 —— adapter 不做拦截，只在日志提醒。
 */
import { BaseAdapter } from '../base.js';
import { mustFind, firstVisible } from '../helpers.js';
import { typeHuman, sleep } from '../../browser/humanize.js';
import { injectBySyntheticPaste, injectByQuill, injectByUEditor, injectByExecCommand, requireCompleteInjection } from '../richtext.js';
import {
  ZdmApiClient, ZdmApiError, isZdmAccountBanned,
} from './api.js';
import { NeedLoginError, PublishRejectedError, PublishResultUnknownError } from '../base.js';
import { checkPlatformContent, checkPlatformCover } from '../../domain/platformConstraints.js';
import S from './selectors.js';

function replaceDataImages(html, uploadedUrls = []) {
  let index = 0;
  return String(html || '').replace(
    /(\bsrc\s*=\s*["'])data:image\/[^"']+(["'])/gi,
    (match, prefix, suffix) => {
      const url = String(uploadedUrls[index++] || '').trim();
      return url ? `${prefix}${url}${suffix}` : match;
    },
  );
}

function requireZdmCovers(article) {
  const hasRequiredCovers = Boolean(article.topicImage?.longPath && article.topicImage?.squarePath);
  const coverIssue = checkPlatformCover(hasRequiredCovers, 'zdm', '什么值得买');
  if (!coverIssue) return;
  const error = new Error(`${coverIssue.message}（长图和方图），系统已停止发布`);
  error.code = coverIssue.code;
  error.status = 400;
  throw error;
}

export default class ZdmAdapter extends BaseAdapter {
  static id = 'zdm';
  static name_ = '什么值得买';
  static homeUrl = S.homeUrl;
  static loginUrl = S.loginUrl;
  static supportsQrLogin = false; // 登录页先弹滑块验证，服务端扫码流走不通（2026-07-11 实测）
  static selectors = S;
  static apiOnly = true;
  static nonLoginBrowserMode = 'none';
  static detectionTimeoutMs = 5 * 60 * 1000;

  async apiCheck(accountId, options = {}) {
    try {
      const client = new ZdmApiClient(accountId);
      return await client.checkLogin(options);
    } catch (error) {
      if (error instanceof ZdmApiError) return { ok: false, profile: null, error };
      throw error;
    }
  }

  async createApiClient(accountId) {
    const client = new ZdmApiClient(accountId);
    await client.getAccountProfile();
    return client;
  }

  /** 什么值得买接口直发：登录检查、图片上传、文章提交和审核状态读取全走 HTTP API。 */
  async publish(_page, article, hooks = {}) {
    requireZdmCovers(article);
    const onStage = hooks.onStage || (() => {});
    const client = new ZdmApiClient(hooks.accountId);

    await onStage('login-check');
    const checked = await client.checkLogin();
    await hooks.onLoginChecked?.(checked.ok, checked.accountStatus);
    if (!checked.ok) {
      if (checked.accountStatus === 'banned') {
        throw new PublishRejectedError('什么值得买账号已限制发布原创文章，内容未提交');
      }
      throw new NeedLoginError(this.name);
    }

    const rejectApiPublish = async error => {
      if (!(error instanceof ZdmApiError)) throw error;
      if (isZdmAccountBanned(error)) {
        await hooks.onLoginChecked?.(false, 'banned');
        throw new PublishRejectedError('什么值得买账号已限制发布原创文章，内容未提交');
      }
      throw new PublishRejectedError(error.message);
    };

    await onStage('open-editor', '什么值得买 API 直发');
    const articleId = await client.allocateArticleId();
    await onStage('fill-title');
    await onStage('fill-body');
    await client.prepareDraft(articleId);
    // 平台先通过一次自动保存建立服务端草稿，之后图片上传接口才接受该 article_id。
    await onStage('save-draft');
    try {
      await client.publishArticle({
        articleId,
        title: article.title,
        editorValue: '<p></p>',
        submitType: 'auto_save',
      });
    } catch (error) {
      await rejectApiPublish(error);
    }
    const imageList = [];
    const uploadedUrls = [];
    for (const image of article.images || []) {
      if (!image?.path) continue;
      const uploaded = await client.uploadImage(image.path, {
        articleId,
        contentType: image.contentType || 'application/octet-stream',
      });
      uploadedUrls.push(uploaded.url);
      imageList.push({
        id: uploaded.id,
        pic_url: uploaded.url,
        original_drawing: 0,
      });
    }
    const html = replaceDataImages(article.html, uploadedUrls);

    await onStage('fill-meta');
    let focusImage = '';
    let squarePicUrl = '';
    if (article.topicImage?.longPath) {
      const cover = await client.uploadCover(article.topicImage.longPath, {
        articleId,
        isHead: true,
        contentType: 'image/jpeg',
      });
      focusImage = cover.pic_url;
    }
    if (article.topicImage?.squarePath) {
      const cover = await client.uploadCover(article.topicImage.squarePath, {
        articleId,
        isHead: false,
        contentType: 'image/jpeg',
      });
      squarePicUrl = cover.square_pic_url || cover.pic_url;
    }
    if (hooks.mode === 'confirm') {
      if (typeof hooks.createPreview !== 'function') throw new Error('人工确认模式缺少预览链接生成器');
      await hooks.createPreview();
      await onStage('waiting-confirm', '内容已准备，请打开预览链接确认发布');
      await hooks.waitConfirm();
    }

    await onStage('click-publish');
    let response;
    try {
      response = await client.publishArticle({
        articleId,
        title: article.title,
        editorValue: html,
        focusImage,
        squarePicUrl,
        imageList,
        submitType: 'submit',
      });
    } catch (error) {
      await rejectApiPublish(error);
    }

    await onStage('detect-published');
    const result = await client.waitForPublication(article.title, {
      articleId,
      timeoutMs: this.detectionTimeoutMs,
    });
    if (!result) {
      throw new PublishResultUnknownError('什么值得买已接受提交，作品列表暂未出现目标文章，系统将继续自动核验');
    }
    if (result.status === 'failed' || result.status === 'draft') {
      throw new PublishRejectedError(result.detail || '什么值得买作品状态异常');
    }
    if (result.status === 'unknown') throw new PublishResultUnknownError(result.detail);
    await onStage(result.status === 'published' ? 'published' : 'reviewing', result.url || '');
    return {
      status: result.status,
      url: result.url || response.url || '',
      detail: result.detail || '',
      articleId,
    };
  }

  async loginCheck(page) {
    await page.goto(S.homeUrl, { waitUntil: 'domcontentloaded' });
    await sleep(3000);
    if (S.loginUrlPattern.test(page.url())) return false;
    const probe = await firstVisible(page, S.loggedInProbe, { timeoutMs: 8000 });
    return !!probe;
  }

  async openEditor(page) {
    await page.goto(S.editorUrl, { waitUntil: 'domcontentloaded' });
    const { locator } = await mustFind(page, S.newArticleLink, '发布新文章入口', { timeoutMs: 20000 });
    const href = await locator.getAttribute('href');
    if (!href) throw new Error('什么值得买「发布新文章」入口缺少链接，请校准 selectors.newArticleLink');
    await page.goto(new URL(href, page.url()).toString(), { waitUntil: 'domcontentloaded' });
    const intro = await firstVisible(page, S.editorIntroDismiss, { timeoutMs: 4000 });
    if (intro) {
      await intro.locator.click();
      await page.locator('.upgrade-tip').first().waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {});
    }
    await mustFind(page, S.titleInput, '标题输入框', { timeoutMs: 20000 });
  }

  async fillTitle(page, title) {
    const { locator } = await mustFind(page, S.titleInput, '标题输入框');
    await typeHuman(locator, title);
  }

  async fillBody(page, article) {
    const { html, text } = article;
    // 门槛数值统一取自 domain/platformConstraints.js，与前端预检同源。
    // 这两项是 warning（平台会收下但大概率驳回），所以只提示不阻断。
    const contentIssues = checkPlatformContent(
      { bodyChars: text.replace(/\s/g, '').length, imageCount: article.images.length },
      'zdm',
      '什么值得买',
    );
    for (const issue of contentIssues) {
      console.warn(`[zdm] ${issue.message}，可能被审核驳回`);
    }

    // 1) 主文档编辑器（Quill/ProseMirror/contenteditable）
    const hit = await firstVisible(page, S.editorBody, { timeoutMs: 8000 });
    if (hit) {
      let result = await injectByQuill(page, hit.selector, html);
      if (!result.ok) {
        result = await injectBySyntheticPaste(page, hit.selector, html, text);
        if (!(result.ok && result.defaultPrevented)) {
          result = await injectByExecCommand(page, hit.selector, html);
        }
      }
      if (!result?.ok) throw new Error(`正文注入失败: ${result?.reason || '所有注入方案均未成功'}`);
      await sleep(2000);
      await this.#checkImages(page, hit.selector, article);
      return;
    }

    // 2) UEditor iframe
    const frame = await this.#findUeditorFrame(page);
    if (!frame) {
      throw new Error(`未找到正文编辑区（主文档候选: ${S.editorBody.join(' | ')}；iframe 候选: ${S.ueditorFrame.join(' | ')}），请校准 selectors.js`);
    }
    let result = await injectByUEditor(page);
    if (!result.ok) {
      result = await injectBySyntheticPaste(frame, S.ueditorBody, html, text);
      if (!(result.ok && result.defaultPrevented)) {
        result = await injectByExecCommand(frame, S.ueditorBody, html);
      }
    }
    if (!result?.ok) throw new Error(`正文注入失败（UEditor）: ${result?.reason || '所有注入方案均未成功'}`);
    await sleep(2000);
    await this.#checkImages(frame, S.ueditorBody, article);
  }

  async #findUeditorFrame(page) {
    for (const sel of S.ueditorFrame) {
      const el = await page.locator(sel).first().elementHandle().catch(() => null);
      const frame = el ? await el.contentFrame() : null;
      if (frame) return frame;
    }
    return null;
  }

  async fillMeta(page, article) {
    requireZdmCovers(article);
    if (article.topicImage.longPath) {
      const ok = await this.uploadCover(page, { ...article, topicImage: { path: article.topicImage.longPath } }, S.coverUpload, S.coverTriggers);
      if (!ok) throw new Error('什么值得买长图封面上传失败：未找到可用的长图上传控件');
    }
    if (article.topicImage.squarePath) {
      const ok = await this.uploadCover(page, { ...article, topicImage: { path: article.topicImage.squarePath } }, S.coverUpload, S.coverSquareTriggers);
      if (!ok) throw new Error('什么值得买方图封面上传失败：未找到可用的方图上传控件');
    }
  }

  async #checkImages(scope, selector, article) {
    // 图片门禁：缺图就不提交。值得买有 ≥5 图的原创门槛，缺图几乎必然审核驳回，
    // 与其发出去等驳回，不如当场判失败让运营知道注入哪里出了问题。
    await requireCompleteInjection(scope, selector, {
      platform: 'zdm',
      expectedImages: article.images.length,
      tempDir: article.tempDir,
    });
  }

}
