/** 今日头条接口适配器：接口完成业务操作，独立无头浏览器仅获取动态参数。 */
import { BaseAdapter } from '../base.js';
import S from './selectors.js';
import { NeedLoginError, PublishRejectedError } from '../base.js';
import {
  buildToutiaoPublishForm,
  replaceToutiaoImageSources,
  ToutiaoApiClient,
  validateToutiaoTitle,
} from './api.js';

export default class ToutiaoAdapter extends BaseAdapter {
  static id = 'toutiao';
  static name_ = '今日头条';
  static homeUrl = S.homeUrl;
  static loginUrl = S.loginUrl;
  static selectors = S;
  static hybrid = true;

  async apiCheck(page) {
    const client = new ToutiaoApiClient(0, page, page.context());
    return await client.checkLogin();
  }

  /**
   * 今日头条采用混合链路：独立无头浏览器只负责加载 acrawler 并取得动态参数，
   * 登录检查、图片上传、发布和状态查询均走接口。
   */
  async publish(page, article, hooks = {}) {
    if (!page) throw new Error('今日头条混合发布需要浏览器页面');
    // 在登录、图片上传和发布请求前校验，超限标题直接落为失败任务，不产生副作用。
    validateToutiaoTitle(article.title);
    const onStage = hooks.onStage || (() => {});
    const client = new ToutiaoApiClient(hooks.accountId, page, page.context(), {
      useCurrentPageForSecurity: hooks.browserMode === 'headless',
    });

    await onStage('login-check');
    const checked = await client.checkLogin();
    await hooks.onLoginChecked?.(checked.ok);
    if (!checked.ok) throw new NeedLoginError(this.name);

    const uploaded = [];
    for (const image of article.images || []) {
      if (!image?.path) continue;
      const data = await client.uploadImage(image.path, image.contentType || 'application/octet-stream');
      uploaded.push({
        id: '', url: data.image_url || '', uri: data.image_uri || '', ic_uri: '',
        thumb_width: Number(data.image_width || 0), thumb_height: Number(data.image_height || 0),
      });
    }
    const html = replaceToutiaoImageSources(article.html, uploaded.map(image => image.url));
    const form = buildToutiaoPublishForm({
      accountId: hooks.accountId,
      title: article.title,
      html,
      text: article.text,
      covers: uploaded.slice(0, 1),
    });

    await onStage('prepare-security');
    await onStage('publish-api');
    const payload = await client.publishArticle(form);
    const pgcId = String(payload?.data?.pgc_id || '');
    const message = String(payload?.message || payload?.reason || '');
    if (!pgcId && !/成功/.test(message)) {
      throw new PublishRejectedError(message || '今日头条发布接口未返回成功标识');
    }

    await onStage('fetch-status');
    const result = await client.waitForPublication(article.title, { pgcId, timeoutMs: 30_000 });
    if (result?.status === 'failed' || result?.status === 'draft') {
      throw new PublishRejectedError(result.detail || '今日头条作品状态异常');
    }
    return result || {
      status: 'reviewing', url: '', detail: `今日头条已提交（pgc_id=${pgcId || 'unknown'}，接口消息：${message || 'success'}）`,
    };
  }

  /** 后台核验同样使用作品流接口，不再打开内容管理页读取 DOM。 */
  async fetchPublicationStatus(page, title) {
    const client = new ToutiaoApiClient(0, page, page.context());
    const checked = await client.checkLogin();
    if (!checked.ok) {
      const error = new Error(`${this.name} 登录态失效，无法核验发布结果`);
      error.code = 'NEED_LOGIN';
      throw error;
    }
    return await client.findPublication(title);
  }

  async loginCheck(page) {
    return (await this.apiCheck(page)).ok;
  }

  async getAccountProfile(page) {
    try {
      const profile = (await this.apiCheck(page)).profile;
      if (profile?.profileName || profile?.username) return profile;
    } catch { /* 接口临时失败时返回空资料 */ }
    return { profileName: '', username: '' };
  }

}
