import fs from 'node:fs/promises';
import path from 'node:path';
import { publicationTitleSimilarity } from '../publicationStatus.js';
import { withHeadlessAccountContext } from '../../browser/manager.js';
import { withRetry } from '../../http/retry.js';
import { getPlatformConstraints } from '../../domain/platformConstraints.js';

const BASE_URL = 'https://mp.toutiao.com';
const EDITOR_URL = `${BASE_URL}/profile_v4/graphic/publish`;
// 编辑器页当前会在 Garr 初始化竞态下阻断 acrawler；主站页仍稳定暴露同一签名器。
// 签名只依赖目标 URL 和请求正文，实际发布请求仍固定发往 mp.toutiao.com。
const SECURITY_BOOTSTRAP_URL = 'https://www.toutiao.com/';
const APP_ID = '1231';
const USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36';
const SECURITY_BROWSER_HEADLESS = process.env.TOUTIAO_SECURITY_HEADLESS !== 'false';
const SECURITY_READY_TIMEOUT_MS = 30_000;
const SECURITY_RELOAD_ATTEMPTS = 2;

// 标题范围由 domain/platformConstraints.js 统一声明，前端预检读的是同一份数据。
export const TOUTIAO_TITLE_MIN_LENGTH = getPlatformConstraints('toutiao').titleMin;
export const TOUTIAO_TITLE_MAX_LENGTH = getPlatformConstraints('toutiao').titleMax;

export class ToutiaoApiError extends Error {
  constructor(message, { status = 0, code = 0, payload = null } = {}) {
    super(message);
    this.name = 'ToutiaoApiError';
    this.status = status;
    this.code = code;
    this.payload = payload;
  }
}

function parseJson(value, fallback = {}) {
  try { return JSON.parse(value); } catch { return fallback; }
}

function asString(value) {
  return value == null ? '' : String(value);
}

function wordCount(text, html) {
  const plain = asString(text) || asString(html).replace(/<[^>]*>/g, '');
  return [...plain].length;
}

export function normalizeToutiaoTitle(value) {
  return [...asString(value).trim()].slice(0, TOUTIAO_TITLE_MAX_LENGTH).join('');
}

/**
 * 发布链路只允许 2~30 字标题。匹配平台返回的历史记录时仍使用
 * normalizeToutiaoTitle，但真正发文前必须显式报错，避免静默截断。
 */
export function validateToutiaoTitle(value) {
  const title = asString(value).trim();
  const length = [...title].length;
  if (length > TOUTIAO_TITLE_MAX_LENGTH) {
    throw new ToutiaoApiError(
      `今日头条标题超过平台限制：当前 ${length} 字，最多 ${TOUTIAO_TITLE_MAX_LENGTH} 字；系统不会自动截断，请缩短标题后再发布。`,
      { code: 'TITLE_TOO_LONG' },
    );
  }
  if (length > 0 && length < TOUTIAO_TITLE_MIN_LENGTH) {
    throw new ToutiaoApiError(
      `今日头条标题不符合平台限制：当前 ${length} 字，标题需为 ${TOUTIAO_TITLE_MIN_LENGTH}~${TOUTIAO_TITLE_MAX_LENGTH} 字。`,
      { code: 'TITLE_TOO_SHORT' },
    );
  }
  return title;
}

/**
 * 依据真实发布请求构造表单字段。字段顺序也保持与页面请求一致，便于
 * acrawler 在浏览器上下文中生成与正文完全对应的动态参数。
 */
export function buildToutiaoPublishForm({ accountId = 0, title, html, text = '', covers = [] } = {}) {
  const safeTitle = validateToutiaoTitle(title);
  const form = new URLSearchParams();
  form.set('pgc_id', '');
  form.set('source', '29');
  form.set('extra', JSON.stringify({
    content_source: 100000000402,
    content_word_cnt: wordCount(text, html),
    is_multi_title: 0,
    sub_titles: [],
    gd_ext: {
      entrance: '', from_page: 'publisher_mp', enter_from: 'PC',
      device_platform: 'mp', is_message: 0,
    },
    tuwen_wtt_trans_flag: '1',
    info_source: { source_type: -1 },
  }));
  form.set('content', asString(html));
  form.set('title', safeTitle);
  form.set('search_creation_info', JSON.stringify({ searchTopOne: 0, abstract: '', clue_id: '' }));
  form.set('title_id', `${Date.now()}_${Number(accountId) || 0}`);
  for (const field of ['ic_uri_list', 'appid_list', 'stock_ids', 'concern_list']) form.set(field, '');
  form.set('mp_editor_stat', JSON.stringify({
    header: 1, 'header-forward-slash': 1, bold: 1, b_quote: 1, 'b_quote-line': 1,
    b_list: 1, o_list: 1, hr: 1, strike: 1, code_block: 1, image: 1, link: 1, emoji: 1,
  }));
  form.set('is_refute_rumor', '0');
  form.set('save', '1');
  form.set('entrance', 'main');
  form.set('timer_status', '0');
  form.set('timer_time', '');
  form.set('educluecard', '');
  form.set('draft_form_data', JSON.stringify({ coverType: 2 }));
  form.set('pgc_feed_covers', JSON.stringify(covers));
  form.set('article_ad_type', '2');
  form.set('is_fans_article', '0');
  form.set('govern_forward', '0');
  form.set('praise', '0');
  form.set('disable_praise', '0');
  form.set('tree_plan_article', '0');
  form.set('star_order_id', '');
  form.set('star_order_name', '');
  form.set('activity_tag', '0');
  form.set('trends_writing_tag', '0');
  form.set('claim_exclusive', '0');
  return form;
}

/** 将上游内容源转换器生成的 data URL 按上传顺序替换为今日头条图片地址。 */
export function replaceToutiaoImageSources(html, uploadedUrls = []) {
  const urls = uploadedUrls.map(value => String(value || '').trim());
  let index = 0;
  return String(html || '').replace(
    /(\bsrc\s*=\s*["'])data:image\/[^"]+(["'])/gi,
    (match, prefix, suffix) => `${prefix}${urls[index++] || match.slice(prefix.length, -suffix.length)}${suffix}`,
  ).replace(
    /(\bsrc\s*=\s*['])data:image\/[^']+(['])/gi,
    (match, prefix, suffix) => `${prefix}${urls[index++] || match.slice(prefix.length, -suffix.length)}${suffix}`,
  );
}

function cookieHeader(cookies = []) {
  return cookies.filter(cookie => String(cookie.domain || '').includes('toutiao.com'))
    .map(cookie => `${cookie.name}=${cookie.value}`).join('; ');
}

function safeHeaderSubset(headers = {}) {
  const allow = ['referer', 'origin', 'x-secsdk-csrf-token', 'tt-anti-token', 'user-agent'];
  return Object.fromEntries(Object.entries(headers).filter(([key, value]) => (
    allow.includes(key.toLowerCase()) && value
  )));
}

function isGarrInitializationError(message) {
  return /reading ['"]network['"]/.test(String(message || ''))
    && /vendors~dde893e5|window\.Garr|Garr\.network/.test(String(message || ''));
}

/**
 * Toutiao 页面会在 Garfish/Garr 和 acrawler 之间异步初始化。
 * 先捕获页面运行时错误，再等待两个依赖按正确顺序就绪；若 Garr 在初始化期间
 * 抛错则重载页面，避免把页面前端异常伪装成 publish API 超时。
 */
async function waitForToutiaoSecurityReady(page, {
  timeoutMs = SECURITY_READY_TIMEOUT_MS,
  reloadAttempts = SECURITY_RELOAD_ATTEMPTS,
} = {}) {
  let lastError;

  for (let attempt = 0; attempt <= reloadAttempts; attempt += 1) {
    const runtimeErrors = [];
    const onConsole = (message) => {
      if (message.type() === 'error') runtimeErrors.push(message.text().slice(0, 1600));
    };
    const onPageError = (error) => {
      runtimeErrors.push(String(error?.stack || error).slice(0, 1600));
    };

    page.on('console', onConsole);
    page.on('pageerror', onPageError);

    try {
      if (attempt > 0) {
        await page.reload({ waitUntil: 'domcontentloaded', timeout: 60_000 });
      } else if (page.url() !== SECURITY_BOOTSTRAP_URL) {
        await page.goto(SECURITY_BOOTSTRAP_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 });
      }

      // 安全上下文固定使用 www.toutiao.com；只有调用方显式传入编辑器页时，
      // 才检查编辑器自身的 Garr 初始化竞态。
      if (page.url().startsWith(BASE_URL)) {
        await page.waitForFunction(
          () => typeof window.Garr?.network === 'function',
          null,
          { timeout: 10_000 },
        );

        const garrError = runtimeErrors.find(isGarrInitializationError);
        if (garrError) {
          throw new ToutiaoApiError(
            `今日头条 Garr 初始化异常（第 ${attempt + 1} 次）：${garrError}`,
            { code: 'TOUTIAO_GARR_INIT_FAILED' },
          );
        }
      }

      await page.waitForFunction(
        () => typeof window.byted_acrawler?.sign === 'function',
        null,
        { timeout: timeoutMs },
      );
      return;
    } catch (error) {
      lastError = error;
      const runtimeSummary = runtimeErrors.find(isGarrInitializationError);
      if (runtimeSummary && !isGarrInitializationError(error.message)) {
        lastError = new ToutiaoApiError(
          `今日头条 Garr 初始化异常：${runtimeSummary}`,
          { code: 'TOUTIAO_GARR_INIT_FAILED' },
        );
      }
      if (attempt >= reloadAttempts) break;
    } finally {
      page.off('console', onConsole);
      page.off('pageerror', onPageError);
    }
  }

  throw new ToutiaoApiError(
    `今日头条安全参数初始化失败：${lastError?.message || 'byted_acrawler.sign 未生成'}`,
    { code: lastError?.code || 'TOUTIAO_SECURITY_INIT_FAILED' },
  );
}

/**
 * 让页面中的 acrawler 对一次被拦截的同构请求做改写，再在同一页面上下文
 * 调用 sign。请求不会到达平台，因此这里仅获取动态参数，不会保存草稿或发文。
 * 调用方负责传入浏览器页面；安全脚本从主站页加载，发布请求仍在路由层拦截。
 */
export async function captureToutiaoSecurityParams(page, {
  body,
  pathname = '/mp/agw/article/publish',
  baseQuery = { source: 'mp', type: 'article', aid: APP_ID, mp_publish_ab_val: '0' },
} = {}) {
  if (!page) throw new ToutiaoApiError('获取今日头条动态参数需要浏览器页面');
  await waitForToutiaoSecurityReady(page);

  const target = new URL(pathname, BASE_URL);
  for (const [key, value] of Object.entries(baseQuery)) target.searchParams.set(key, String(value));
  const capture = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new ToutiaoApiError('浏览器动态参数探针超时')), 30_000);
    page.route('**/mp/agw/article/publish**', async route => {
      try {
        const request = route.request();
        const result = {
          url: request.url(),
          postData: request.postData() || '',
          headers: safeHeaderSubset(await request.allHeaders()),
        };
        clearTimeout(timer);
        resolve(result);
        await route.abort('blockedbyclient');
      } catch (error) {
        clearTimeout(timer);
        reject(error);
        await route.abort('failed').catch(() => {});
      }
    });
  });

  try {
    await page.evaluate(async ({ url, body: requestBody }) => {
      try {
        await fetch(url, {
          method: 'POST', credentials: 'include',
          headers: { 'content-type': 'application/x-www-form-urlencoded; charset=UTF-8' },
          body: requestBody,
        });
      } catch { /* route 会主动中断，探针不触达服务端 */ }
    }, { url: target.toString(), body: String(body || '') });
    const rewritten = await capture;
    if (!rewritten.url || !rewritten.postData) throw new ToutiaoApiError('动态参数探针未捕获到完整请求');
    const signature = await page.evaluate(({ url, requestBody }) => (
      window.byted_acrawler.sign({ url, body: requestBody })
    ), { url: rewritten.url, requestBody: rewritten.postData });
    if (!signature || typeof signature !== 'string') throw new ToutiaoApiError('浏览器未返回 _signature');
    const signed = new URL(rewritten.url);
    signed.searchParams.set('_signature', signature);
    const requestHeaders = {
      ...rewritten.headers,
      // 签名器运行在 www 页面，但真正的发布请求必须保持 mp 来源头。
      origin: BASE_URL,
      referer: EDITOR_URL,
      'user-agent': USER_AGENT,
    };
    return {
      url: signed.toString(),
      body: rewritten.postData,
      headers: requestHeaders,
      queryKeys: [...signed.searchParams.keys()],
    };
  } finally {
    await page.unroute('**/mp/agw/article/publish**').catch(() => {});
  }
}

function findArticleMatch(items, title, pgcId = '') {
  if (pgcId) {
    const exactId = items.find(item => {
      const attr = item.article_attr || item;
      return String(attr.item_id || attr.gid || attr.pgc_id) === String(pgcId);
    });
    return exactId || null;
  }
  const normalizedTitle = normalizeToutiaoTitle(title);
  let best = null;
  for (const item of items) {
    const attr = item.article_attr || item;
    const itemTitle = normalizeToutiaoTitle(attr.title || attr.rich_title || '');
    const score = publicationTitleSimilarity(normalizedTitle, itemTitle);
    const status = mapToutiaoArticleStatus(item).status;
    const statusPriority = status === 'published' ? 3 : status === 'reviewing' ? 2 : status === 'failed' || status === 'draft' ? 1 : 0;
    if (!best || score > best.score || (score === best.score && statusPriority > best.statusPriority)) {
      best = { item, score, statusPriority };
    }
  }
  return best && best.score >= 0.82 ? best.item : null;
}

function normalizeFeedItem(item = {}) {
  const cell = item?.assembleCell?.itemCell || {};
  const base = cell.articleBase || {};
  const custom = parseJson(cell.extra?.creator_center_custom, {});
  const pgcCell = custom.PgcCell || custom.pgc_cell || '';
  return {
    article_attr: {
      title: base.title || custom.title || '',
      rich_title: base.title || custom.title || '',
      item_id: String(base.gidStr || custom.item_id || custom.gid || ''),
      gid: String(base.gidStr || custom.item_id || custom.gid || ''),
      status: custom.status,
      status_desc: custom.status_desc || (Number(custom.status) === 1 ? '审核中' : ''),
      pgc_cell: pgcCell,
    },
    previewUrl: base.displayURL || base.articleURL || custom.article_url || '',
  };
}

export function mapToutiaoArticleStatus(item = {}) {
  const attr = item.article_attr || item;
  const cell = parseJson(attr.pgc_cell, {});
  const description = String(attr.status_desc || cell.status_desc || '').trim();
  const itemId = String(attr.item_id || attr.gid || cell.item_id || cell.group_id || '').trim();
  const url = itemId ? `https://www.toutiao.com/item/${itemId}/` : '';
  if (/草稿/.test(description) || cell.is_draft === true) return { status: 'draft', url: '', detail: description || '今日头条作品仍为草稿' };
  if (/失败|驳回|未通过/.test(description) || cell.is_unpass) return { status: 'failed', url: '', detail: description || '今日头条审核未通过' };
  if (/已发布|发布成功/.test(description) || cell.is_passed === true || Number(cell.status) === 3) {
    return { status: 'published', url, detail: description };
  }
  if (/审核|待发布|发布中/.test(description) || Number(attr.status) === 1) {
    return { status: 'reviewing', url: item.previewUrl || cell.article_url || url, detail: description || '今日头条内容审核中' };
  }
  return { status: 'unknown', url: '', detail: description || '今日头条返回了未识别的作品状态' };
}

export class ToutiaoApiClient {
  constructor(accountId, page, context, { useCurrentPageForSecurity = false } = {}) {
    this.accountId = Number(accountId) || 0;
    this.page = page;
    this.context = context || page?.context?.();
    this.useCurrentPageForSecurity = useCurrentPageForSecurity;
    this.cookies = [];
    this.securityHeaders = {};
    this.userId = '';
  }

  async refreshCookies() {
    if (!this.context) throw new ToutiaoApiError('今日头条接口客户端缺少浏览器上下文');
    this.cookies = await this.context.cookies(BASE_URL);
    if (!this.cookies.length) throw new ToutiaoApiError('今日头条登录态没有可用 Cookie');
  }

  headers(extra = {}) {
    return {
      Accept: 'application/json, text/plain, */*',
      Cookie: cookieHeader(this.cookies),
      ...this.securityHeaders,
      // 签名上下文使用 www.toutiao.com，实际 API 请求必须恢复为 mp 来源。
      Origin: BASE_URL,
      Referer: EDITOR_URL,
      'User-Agent': USER_AGENT,
      ...extra,
    };
  }

  async request(pathname, { method = 'GET', body, headers = {} } = {}) {
    return withRetry(async () => {
      await this.refreshCookies();
      const url = new URL(pathname, BASE_URL);
      const requestHeaders = this.headers(headers);
      if (body !== undefined && !Object.keys(requestHeaders).some(key => key.toLowerCase() === 'content-type')) {
        requestHeaders['Content-Type'] = 'application/json';
      }
      const response = await fetch(url, {
        method,
        headers: requestHeaders,
        body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body),
      });
      const text = await response.text();
      const payload = parseJson(text, { message: text.slice(0, 300) });
      const code = Number(payload?.code ?? payload?.err_no ?? 0);
      if (!response.ok || code === 100004 || (payload && payload.code != null && code !== 0)) {
        throw new ToutiaoApiError(payload?.message || payload?.reason || `今日头条接口请求失败（HTTP ${response.status}）`, {
          status: response.status, code, payload,
        });
      }
      return payload;
    }, { operationName: `toutiao ${method} ${pathname}` });
  }

  async getAccountProfile() {
    const payload = await this.request('/mp/agw/media/get_media_info');
    const profile = payload?.data?.user || {};
    const media = payload?.data?.media || {};
    let user = {};
    try {
      const userPayload = await this.request('/mp/agw/general/user/get_user_info');
      user = userPayload?.data?.data || {};
    } catch { /* 个人信息接口偶发失败时使用媒体接口返回 */ }
    this.userId = String(user.user_id || profile.user_id || profile.id || '').trim();
    return {
      profileName: String(user.screen_name || user.name || profile.screen_name || profile.name || media.display_name || '').trim(),
      username: String(user.user_id || profile.user_id || media.id || '').trim(),
      accountId: this.accountId,
    };
  }

  async checkLogin() {
    try {
      const profile = await this.getAccountProfile();
      return {
        ok: true,
        profile,
      };
    } catch (error) {
      if (error instanceof ToutiaoApiError) return { ok: false, profile: null, error };
      throw error;
    }
  }

  async prepare(body) {
    await this.refreshCookies();
    if (!this.accountId) throw new ToutiaoApiError('获取今日头条动态参数需要有效账号 ID');
    const security = this.useCurrentPageForSecurity
      ? await captureToutiaoSecurityParams(this.page, { body })
      : await withHeadlessAccountContext(this.accountId, page => (
        captureToutiaoSecurityParams(page, { body })
      ), { headless: SECURITY_BROWSER_HEADLESS });
    this.securityHeaders = security.headers;
    return security;
  }

  async uploadImage(filePath, contentType = 'application/octet-stream') {
    await this.refreshCookies();
    const bytes = await fs.readFile(filePath);
    const url = `${BASE_URL}/spice/image?upload_source=20020002&aid=${APP_ID}&device_platform=web`;
    return withRetry(async () => {
      const form = new FormData();
      // ex_jrtt.txt 的真实请求字段名为 image，使用 file 会返回成功但正文无法绑定素材。
      form.append('image', new Blob([bytes], { type: contentType }), path.basename(filePath));
      const response = await fetch(url, { method: 'POST', headers: this.headers(), body: form });
      const text = await response.text();
      const payload = parseJson(text, { message: text.slice(0, 300) });
      if (!response.ok || Number(payload?.code || 0) !== 0 || !payload?.data?.image_uri) {
        throw new ToutiaoApiError(payload?.message || `今日头条图片上传失败（HTTP ${response.status}）`, {
          status: response.status, code: Number(payload?.code || 0), payload,
        });
      }
      return payload.data;
    }, { operationName: 'toutiao POST /spice/image' });
  }

  async publishArticle(form) {
    return withRetry(async () => {
      const security = await this.prepare(form.toString());
      const response = await fetch(security.url, {
        method: 'POST',
        headers: this.headers({ 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' }),
        body: security.body,
      });
      const text = await response.text();
      const payload = parseJson(text, { message: text.slice(0, 300) });
      if (!response.ok || Number(payload?.code ?? payload?.err_no ?? 0) !== 0) {
        throw new ToutiaoApiError(payload?.message || payload?.reason || `今日头条发布接口失败（HTTP ${response.status}）`, {
          status: response.status, code: Number(payload?.code ?? payload?.err_no ?? 0), payload,
        });
      }
      return payload;
    }, { operationName: 'toutiao POST /mp/agw/article/publish' });
  }

  async listArticles({ pageSize = 20 } = {}) {
    const params = new URLSearchParams({
      status: '2', type: '0', page_size: String(pageSize), need_stat: 'true',
      wenda_type: '1', app_id: APP_ID,
    });
    const payload = await this.request(`/mp/agw/creator_center/list/v2?${params}`);
    return payload?.contents || [];
  }

  async listFeedArticles({ count = 20, offset = 0 } = {}) {
    if (!this.userId) {
      const checked = await this.checkLogin();
      if (!checked.ok) return [];
    }
    const params = new URLSearchParams({
      provider_type: 'mp_provider', aid: '13', app_name: 'news_article', category: 'mp_all',
      channel: '', stream_api_version: '88',
      genre_type_switch: JSON.stringify({ repost: 1, small_video: 1, toutiao_graphic: 1, weitoutiao: 1, xigua_video: 1 }),
      device_platform: 'pc', platform_id: '0', visited_uid: this.userId,
      offset: String(offset), count: String(count), keyword: '',
      client_extra_params: JSON.stringify({
        category: 'mp_all', real_app_id: APP_ID, need_forward: 'true', offset_mode: '1',
        page_index: '1', status: '8', source: '0',
      }),
      app_id: APP_ID,
    });
    const payload = await this.request(`/api/feed/mp_provider/v1/?${params}`);
    return (payload?.data || []).map(normalizeFeedItem);
  }

  async findPublication(title, { pgcId = '' } = {}) {
    const items = await this.listArticles({ pageSize: 100 });
    let item = findArticleMatch(items, title, pgcId);
    let listStatus = item ? mapToutiaoArticleStatus(item).status : '';
    // 发布接口返回的 pgc_id 可能先对应「由文章生成」记录，正式文章随后以另一 item_id 出现在列表。
    // 这时优先使用同标题且已有明确状态的列表项，避免无效 pgc_id 把查询引向易被拦截的 Feed 接口。
    if (pgcId && listStatus === 'unknown') {
      const titleItem = findArticleMatch(items, title);
      const titleStatus = titleItem ? mapToutiaoArticleStatus(titleItem).status : '';
      if (titleItem && titleStatus !== 'unknown') {
        item = titleItem;
        listStatus = titleStatus;
      }
    }
    if (!item || listStatus === 'unknown' || listStatus === 'reviewing') {
      try {
        const feedItems = await this.listFeedArticles({ count: 20 });
        const feedItem = findArticleMatch(feedItems, title, pgcId);
        if (feedItem) item = feedItem;
      } catch (error) {
        // Feed 403 只影响补充核验；保留列表已有结果，发布任务后续由 reconciler 继续核验。
        if (Number(error?.status) !== 403) throw error;
        if (item && listStatus !== 'unknown') return { ...mapToutiaoArticleStatus(item), article: item };
        return null;
      }
    }
    return item ? { ...mapToutiaoArticleStatus(item), article: item } : null;
  }

  async waitForPublication(title, { pgcId = '', timeoutMs = 60_000, intervalMs = 3_000 } = {}) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() <= deadline) {
      const result = await this.findPublication(title, { pgcId });
      if (result && result.status !== 'unknown') return result;
      const waitMs = Math.min(intervalMs, Math.max(0, deadline - Date.now()));
      if (!waitMs) break;
      await new Promise(resolve => setTimeout(resolve, waitMs));
    }
    return null;
  }
}
