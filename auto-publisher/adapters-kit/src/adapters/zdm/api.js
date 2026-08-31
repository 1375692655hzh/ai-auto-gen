import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { getStorageState } from '../../runtime/storage.js';
import { publicationTitleSimilarity } from '../publicationStatus.js';
import { withRetry } from '../../http/retry.js';

const POST_BASE_URL = 'https://post.smzdm.com';
const USER_BASE_URL = 'https://zhiyou.smzdm.com';
const TOKEN_PATH = '/api/editor/get_token';
const SUBMIT_PATH = '/api/editor/article/submit';
const USER_INFO_PATH = '/user/info/jsonp_get_current?with_avatar_ornament=1';
const USER_ARTICLE_PATH = '/user/article/';
const USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36';
export const ZDM_ACCOUNT_BANNED_ERROR_CODE = 20_000_115;
const ZDM_BANNED_STATUS_PATTERN = /黑屋|封禁|封号|冻结|封停|禁用|禁止(?:提交|发布)(?:原创文章|文章|内容)?|发布权限(?:受限|限制)|违反.*社区指导原则|banned|blocked|frozen|suspend/i;

export class ZdmApiError extends Error {
  constructor(message, { status = 0, code = 0, payload = null, url = '' } = {}) {
    super(message);
    this.name = 'ZdmApiError';
    this.status = status;
    this.code = code;
    this.payload = payload;
    this.url = url;
  }
}

function asString(value) {
  return value == null ? '' : String(value);
}

function isPositiveStatusFlag(value) {
  if (value === true) return true;
  const normalized = asString(value).trim().toLowerCase();
  return normalized === 'true'
    || normalized === 'yes'
    || normalized === '1'
    || Number(value) > 0;
}

function nestedBanSignalObjects(value) {
  const objects = [];
  const queue = [value];
  const seen = new Set();
  while (queue.length) {
    const current = queue.shift();
    if (!current || typeof current !== 'object' || seen.has(current)) continue;
    seen.add(current);
    objects.push(current);
    for (const key of ['payload', 'raw', 'data', 'user', 'account']) {
      if (current[key] && typeof current[key] === 'object') queue.push(current[key]);
    }
  }
  return objects;
}

/** 根据什么值得买发布接口的错误码和黑屋标记识别账号发布权限受限。 */
export function isZdmAccountBanned(value = {}) {
  return nestedBanSignalObjects(value).some(payload => {
    const errorCode = Number(payload.error_code ?? payload.code ?? 0);
    const blackRoom = payload.is_in_black_room
      ?? payload.isInBlackRoom
      ?? payload.black_room
      ?? payload.blackRoom;
    const statusText = [
      payload.error_msg,
      payload.msg,
      payload.message,
      payload.blackroom_desc,
      payload.blackroom_level,
      payload.statusName,
      payload.statusText,
    ].map(item => asString(item).trim()).filter(Boolean).join(' ');
    return errorCode === ZDM_ACCOUNT_BANNED_ERROR_CODE
      || isPositiveStatusFlag(blackRoom)
      || ZDM_BANNED_STATUS_PATTERN.test(statusText);
  });
}

function parseJson(value, fallback = null) {
  try { return JSON.parse(value); } catch { return fallback; }
}

function parseJsonp(value) {
  const text = asString(value).trim().replace(/^\uFEFF/, '');
  const direct = parseJson(text, null);
  if (direct !== null) return direct;
  const match = text.match(/^[\w$.]+\s*\(([\s\S]*)\)\s*;?$/);
  return match ? parseJson(match[1], null) : null;
}

function sessionCookieHeader(cookies = []) {
  return cookies
    .filter(cookie => /(?:^|\.)smzdm\.com$/i.test(asString(cookie.domain).replace(/^\./, '')))
    .map(cookie => `${cookie.name}=${cookie.value}`)
    .join('; ');
}

function localStorageEntries(storageState = {}) {
  return (storageState.origins || []).flatMap(origin => (
    (origin.localStorage || []).map(item => ({
      name: asString(item.name),
      value: asString(item.value),
      origin: asString(origin.origin),
    }))
  ));
}

function scalarId(value) {
  const text = asString(value).trim();
  return /^\d+$/.test(text) ? text : '';
}

function positiveScalarId(value) {
  const id = scalarId(value);
  return id && Number(id) > 0 ? id : '';
}

function findNestedId(value, preferredKeys = /^(?:smzdm_id|smzdmId|user_id|userId|userid)$/i) {
  if (!value || typeof value !== 'object') return '';
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findNestedId(item, preferredKeys);
      if (found) return found;
    }
    return '';
  }
  for (const [key, item] of Object.entries(value)) {
    if (preferredKeys.test(key)) {
      const found = scalarId(item);
      if (found) return found;
    }
  }
  for (const item of Object.values(value)) {
    const found = findNestedId(item, preferredKeys);
    if (found) return found;
  }
  return '';
}

function findStoredSmzdmId(storageState = {}) {
  const entries = localStorageEntries(storageState);
  const direct = entries.find(item => /^(?:smzdm_id|smzdmId|user_id|userId)$/i.test(item.name));
  const directId = positiveScalarId(direct?.value);
  if (directId) return directId;
  for (const entry of entries) {
    const found = positiveScalarId(findNestedId(parseJson(entry.value, null)));
    if (found) return found;
  }
  const cookie = (storageState.cookies || []).find(item => /^(?:smzdm_id|smzdmId|user_id|userId)$/i.test(asString(item.name)));
  return positiveScalarId(cookie?.value);
}

function findProfileName(value) {
  if (!value || typeof value !== 'object') return '';
  const preferred = /^(?:nickname|nick_name|user_name|username|name|display_name)$/i;
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findProfileName(item);
      if (found) return found;
    }
    return '';
  }
  for (const [key, item] of Object.entries(value)) {
    if (preferred.test(key) && asString(item).trim()) return asString(item).trim();
  }
  for (const item of Object.values(value)) {
    const found = findProfileName(item);
    if (found) return found;
  }
  return '';
}

function decodeHtml(value) {
  return asString(value)
    .replace(/&nbsp;|&#160;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&#(\d+);/g, (_, code) => String.fromCodePoint(Number(code)))
    .replace(/&#x([\da-f]+);/gi, (_, code) => String.fromCodePoint(parseInt(code, 16)));
}

export function htmlToText(html) {
  return decodeHtml(asString(html)
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, '')
    .replace(/<br\s*\/?\s*>/gi, '\n')
    .replace(/<\/(?:p|div|h[1-6]|li|blockquote|pre|tr|section|article)\s*>/gi, '\n')
    .replace(/<[^>]*>/g, ''));
}

export function textCountFromHtml(html) {
  return htmlToText(html).replace(/\s/g, '').replace(/　/g, '').length;
}

export function buildAwne(smzdmId, textCount) {
  const id = asString(smzdmId).trim();
  const count = Number(textCount);
  if (!id) throw new ZdmApiError('什么值得买接口缺少 smzdmId，无法生成 awne');
  if (!Number.isInteger(count) || count < 0) throw new ZdmApiError('什么值得买接口的 textCount 必须是非负整数');
  const secret = `${id}-${count}-smzdm.com`.trim();
  const key = crypto.createHash('md5').update(secret, 'utf8').digest('hex');
  const plaintext = Buffer.from(String(count), 'utf8').toString('base64');
  const cipher = crypto.createCipheriv('aes-256-ecb', Buffer.from(key, 'utf8'), null);
  return Buffer.concat([cipher.update(Buffer.from(plaintext, 'utf8')), cipher.final()]).toString('base64');
}

export function createArticleId() {
  return crypto.randomUUID().replace(/-/g, '').slice(0, 8).toLowerCase();
}

function imageFields(image = {}) {
  return {
    height: image.height ?? '',
    image_tag: image.image_tag ?? image.imageTag ?? '',
    original_drawing: image.original_drawing ?? image.originalDrawing ?? 0,
    pic_url: image.pic_url ?? image.picUrl ?? image.url ?? '',
    picture_id: image.picture_id ?? image.pictureId ?? image.id ?? '',
    width: image.width ?? '',
    cms_link: image.cms_link ?? image.cmsLink ?? '',
    other_data: image.other_data ?? image.otherData ?? '',
    image_product_tag: image.image_product_tag ?? image.imageProductTag ?? '',
  };
}

export function buildPublishForm({
  articleId,
  title,
  editorValue,
  html,
  seriesTitle = '',
  focusImage = '',
  seriesId = 0,
  anonymous = 0,
  firstPublish = 0,
  remark = '',
  createStateType = 3,
  aiStateType = 3,
  squarePicUrl = '',
  coverImageRectangle = '',
  customTopics = '',
  groupId = '',
  awne,
  wne,
  imageList = [],
  submitType = 'submit',
} = {}) {
  const body = asString(editorValue ?? html);
  const form = new URLSearchParams();
  const fields = {
    article_id: articleId,
    submit_type: submitType,
    title,
    series_title: seriesTitle,
    focus_image: focusImage,
    series_id: seriesId,
    anonymous,
    first_publish: firstPublish,
    remark,
    editorValue: body,
    create_state_type: createStateType,
    ai_state_type: aiStateType,
    square_pic_url: squarePicUrl,
    cover_image_rectangle: coverImageRectangle,
    custom_topics: customTopics,
    group_id: groupId,
    awne,
    wne,
  };
  for (const [key, value] of Object.entries(fields)) form.set(key, asString(value));
  imageList.map(imageFields).forEach((image, index) => {
    for (const [key, value] of Object.entries(image)) form.set(`image_list[${index}][${key}]`, asString(value));
  });
  return form;
}

export function statusFromText(value) {
  const text = asString(value);
  if (/驳回|拒绝|未通过|失败|退回/.test(text)) return { status: 'failed', detail: '什么值得买内容审核未通过或处理失败' };
  if (/已发布|已上线|发布成功/.test(text)) return { status: 'published', detail: '' };
  if (/审核中|待审核|审核/.test(text)) return { status: 'reviewing', detail: '什么值得买内容审核中' };
  if (/草稿|待提交/.test(text)) return { status: 'draft', detail: '什么值得买内容仍为草稿' };
  return { status: 'unknown', detail: '什么值得买返回了未识别的内容状态' };
}

/**
 * 什么值得买后台没有“展示受限”文案：发布账号可访问、匿名访问返回 404。
 * 只把明确的 404 视为受限；风控、超时等其它响应保留为待检测，避免误判。
 */
export async function probeZdmPublicVisibility(url, {
  fetchImpl = globalThis.fetch,
  timeoutMs = 10_000,
  attempts = 2,
  retryDelayMs = 5_000,
} = {}) {
  if (!url || typeof fetchImpl !== 'function') return { healthStatus: 'unknown', detail: '' };
  const safeAttempts = Math.max(1, Math.min(Number(attempts) || 1, 3));
  for (let attempt = 1; attempt <= safeAttempts; attempt += 1) {
    try {
      const response = await fetchImpl(url, {
        method: 'GET',
        redirect: 'follow',
        headers: {
          Accept: 'text/html,application/xhtml+xml',
          'User-Agent': USER_AGENT,
        },
        signal: AbortSignal.timeout(timeoutMs),
      });
      if (response.status === 404 && attempt < safeAttempts) {
        await new Promise(resolve => setTimeout(resolve, retryDelayMs));
        continue;
      }
      if (response.status === 404) {
        return {
          healthStatus: 'restricted',
          detail: '公开访问连续返回 404，仅发布账号可见',
        };
      }
      return { healthStatus: response.ok ? 'normal' : 'unknown', detail: '' };
    } catch {
      return { healthStatus: 'unknown', detail: '' };
    }
  }
  return { healthStatus: 'unknown', detail: '' };
}

export function publicationCandidates(html) {
  const candidates = [];
  const pattern = /<a\b[^>]*href=["'](https?:\/\/post\.smzdm\.com\/p\/[^"'?#/]+\/?)[^"']*["'][^>]*>[\s\S]*?<\/a>/gi;
  for (const match of html.matchAll(pattern)) {
    const index = match.index || 0;
    const rowMarker = html.lastIndexOf('pandect-content-common', index);
    const rowStart = rowMarker >= 0 ? html.lastIndexOf('<div', rowMarker) : Math.max(0, index - 1800);
    const lineMarker = html.indexOf('pandect-line', index + match[0].length);
    const lineStart = lineMarker >= 0 ? html.lastIndexOf('<div', lineMarker) : Math.min(html.length, index + match[0].length + 2200);
    const rowHtml = html.slice(Math.max(0, rowStart), Math.max(index + match[0].length, lineStart));
    const context = htmlToText(rowHtml).replace(/\s+/g, ' ').trim();
    const title = htmlToText(match[0]).replace(/\s+/g, ' ').trim();
    const statusMatch = rowHtml.match(/<em\b[^>]*class=["'][^"']*\bgreed\b[^"']*["'][^>]*>([\s\S]*?)<\/em>/i);
    const statusText = htmlToText(statusMatch?.[1] || '').replace(/\s+/g, ' ').trim();
    const articleId = match[1].match(/\/p\/([^/?#]+)\/?$/)?.[1] || '';
    candidates.push({ url: match[1], articleId, title, statusText, context });
  }
  return candidates;
}

export class ZdmApiClient {
  static createArticleId = createArticleId;

  constructor(accountId, storageState = getStorageState(accountId)) {
    this.accountId = Number(accountId) || 0;
    this.storageState = storageState || {};
    this.metadata = {
      cookies: sessionCookieHeader(this.storageState.cookies || []),
      storedSmzdmId: findStoredSmzdmId(this.storageState),
    };
    this.smzdmId = this.metadata.storedSmzdmId;
  }

  headers(extra = {}, baseUrl = POST_BASE_URL) {
    return {
      Accept: 'application/json, text/javascript, */*; q=0.01',
      Cookie: this.metadata.cookies,
      Origin: baseUrl,
      Referer: `${baseUrl}/`,
      'User-Agent': USER_AGENT,
      'X-Requested-With': 'XMLHttpRequest',
      ...extra,
    };
  }

  async request(pathname, {
    method = 'GET',
    body,
    headers = {},
    baseUrl = POST_BASE_URL,
    parse = 'json',
    csrf = false,
  } = {}) {
    return withRetry(async () => {
      const url = new URL(pathname, baseUrl);
      const requestHeaders = this.headers(headers, url.origin);
      if (csrf) requestHeaders._csrf_token = await this.getToken();
      let requestBody = body;
      if (body instanceof URLSearchParams) {
        requestHeaders['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8';
        requestBody = body.toString();
      }
      const response = await fetch(url, { method, headers: requestHeaders, body: requestBody });
      const text = await response.text();
      const payload = parse === 'text' ? text : parse === 'jsonp' ? parseJsonp(text) : parseJson(text, null);
      const code = payload && typeof payload === 'object'
        ? Number(payload.error_code ?? payload.code ?? 0)
        : 0;
      const failed = !response.ok
        || payload === null && parse !== 'text'
        || payload?.success === false
        || payload?.error_code != null && code !== 0;
      if (failed) {
        throw new ZdmApiError(
          payload?.error_msg || payload?.msg || payload?.message || `什么值得买接口请求失败（HTTP ${response.status}）`,
          { status: response.status, code, payload: payload || text.slice(0, 300), url: url.toString() },
        );
      }
      return payload;
    }, { operationName: `zdm ${method} ${pathname}` });
  }

  async getToken() {
    const payload = await this.request(TOKEN_PATH);
    const token = asString(payload?.data?.token).trim();
    if (!token) throw new ZdmApiError('什么值得买接口返回中缺少 CSRF Token', { payload });
    return token;
  }

  async getAccountProfile() {
    const payload = await this.request(USER_INFO_PATH, { baseUrl: USER_BASE_URL, parse: 'jsonp' });
    const data = payload?.data || payload?.user || payload || {};
    const apiSmzdmId = positiveScalarId(findNestedId(payload));
    const profileName = findProfileName(data);
    const username = asString(data.username || data.user_name || data.login_name || '').trim();
    const authenticated = Boolean(apiSmzdmId || profileName || username);
    const smzdmId = apiSmzdmId || (authenticated ? this.metadata.storedSmzdmId : '');
    if (smzdmId) this.smzdmId = smzdmId;
    return {
      profileName,
      username,
      smzdmId: authenticated ? this.smzdmId : '',
      platformAccountId: apiSmzdmId || (authenticated ? this.metadata.storedSmzdmId : ''),
      authenticated,
      raw: payload,
    };
  }

  /**
   * 什么值得买的个人资料接口不返回原创投稿封禁状态。
   * 复用编辑器首次自动保存请求作为一次发布权限探针；平台封禁响应会在这里明确返回。
   */
  async checkPublishPermission() {
    const articleId = await this.allocateArticleId();
    await this.prepareDraft(articleId);
    await this.publishArticle({
      articleId,
      title: '发布适配器账号状态检测',
      editorValue: '<p></p>',
      submitType: 'auto_save',
    });
    return { ok: true, articleId };
  }

  async checkLogin({ probePublishPermission = false } = {}) {
    try {
      const profile = await this.getAccountProfile();
      if (isZdmAccountBanned(profile)) {
        const raw = profile.raw && typeof profile.raw === 'object' ? profile.raw : null;
        return {
          ok: false,
          accountStatus: 'banned',
          profile,
          error: new ZdmApiError('什么值得买账号发布权限受限', {
            code: Number(raw?.error_code ?? raw?.code ?? 0),
            payload: raw,
          }),
        };
      }
      if (!profile.authenticated) return { ok: false, profile };
      if (probePublishPermission && profile.smzdmId) {
        try {
          await this.checkPublishPermission();
        } catch (error) {
          if (error instanceof ZdmApiError) {
            if (isZdmAccountBanned(error)) {
              return {
                ok: false,
                accountStatus: 'banned',
                profile,
                error,
              };
            }
            // 探针本身的其它接口异常不覆盖已经确认的登录态。
            return { ok: true, profile, publishPermission: 'unknown', error };
          }
          throw error;
        }
      }
      return { ok: true, profile };
    } catch (error) {
      if (error instanceof ZdmApiError) {
        return {
          ok: false,
          accountStatus: isZdmAccountBanned(error) ? 'banned' : undefined,
          profile: null,
          error,
        };
      }
      throw error;
    }
  }

  /** 读取创作中心生成的新文章入口，复用平台分配的动态 article_id。 */
  async allocateArticleId() {
    const html = await this.request('/tougao/', { parse: 'text' });
    const match = asString(html).match(/(?:href|url)=["']?[^"'\s>]*\/edit\/([a-z0-9]{8})/i);
    const articleId = match?.[1]?.toLowerCase() || '';
    if (!articleId) {
      throw new ZdmApiError(
        '什么值得买创作中心未返回新文章入口，通常是账号掉登录的特征；请先重新登录后重试',
      );
    }
    return articleId;
  }

  async uploadImage(filePath, { articleId, contentType = '' } = {}) {
    if (!articleId) throw new ZdmApiError('上传什么值得买图片时缺少 articleId');
    const bytes = await fs.readFile(filePath);
    const inferredType = contentType || (path.extname(filePath).toLowerCase() === '.jpg' || path.extname(filePath).toLowerCase() === '.jpeg' ? 'image/jpeg' : 'image/png');
    const form = new FormData();
    form.append('imgFile', new Blob([bytes], { type: inferredType }), path.basename(filePath));
    form.append('id', 'WU_FILE_0');
    form.append('type', inferredType);
    form.append('article_id', asString(articleId));
    const payload = await this.request('/api/images/upload/local', { method: 'POST', body: form });
    const data = payload?.data || {};
    if (!data.url) throw new ZdmApiError('什么值得买图片上传响应缺少 url', { payload });
    return { ...data, url: data.url, id: data.id || '' };
  }

  async getOriginalImage({ articleId, picUrl }) {
    const form = new URLSearchParams({ article_id: asString(articleId), pic_url: asString(picUrl) });
    const payload = await this.request('/api/image/original', { method: 'POST', body: form });
    const data = payload?.data || {};
    if (!data.original_url || !Number(data.width) || !Number(data.height)) {
      throw new ZdmApiError('什么值得买原图接口返回字段不完整', { payload });
    }
    return data;
  }

  async cropImage({ articleId, original, isHead = false }) {
    const width = Number(original.width);
    const height = Number(original.height);
    const targetAspect = isHead ? 1484 / 628 : 1;
    let cropWidth = width;
    let cropHeight = width / targetAspect;
    if (cropHeight > height) {
      cropHeight = height;
      cropWidth = height * targetAspect;
    }
    const srcX = Math.max(0, (width - cropWidth) / 2);
    const srcY = Math.max(0, (height - cropHeight) / 2);
    const sizeWidth = isHead ? 134.69510268562402 : 100.125;
    const sizeHeight = sizeWidth / targetAspect;
    const cropperData = JSON.stringify({
      x: srcX, y: srcY, width: cropWidth, height: cropHeight,
      rotate: 0, scaleX: 1, scaleY: 1,
    });
    const form = new FormData();
    const fields = {
      'cut_pic_list[0][src_x]': srcX,
      'cut_pic_list[0][src_y]': srcY,
      'cut_pic_list[0][src_w]': cropWidth,
      'cut_pic_list[0][src_h]': cropHeight,
      'cut_pic_list[0][article_id]': articleId,
      'cut_pic_list[0][size_w]': sizeWidth,
      'cut_pic_list[0][size_h]': sizeHeight,
      'cut_pic_list[0][cropperData]': cropperData,
      'cut_pic_list[0][original_pic_height]': height,
      'cut_pic_list[0][original_pic_width]': width,
      'cut_pic_list[0][cutUrl]': original.original_url,
      'cut_pic_list[0][is_head]': isHead ? 1 : 0,
    };
    for (const [key, value] of Object.entries(fields)) form.append(key, asString(value));
    const payload = await this.request('/api/image/crop', { method: 'POST', body: form });
    const data = Array.isArray(payload?.data) ? payload.data[0] : payload?.data;
    if (!data?.pic_url) throw new ZdmApiError('什么值得买封面裁剪接口未返回图片地址', { payload });
    return data;
  }

  async uploadCover(filePath, { articleId, isHead = false, contentType = 'image/jpeg' } = {}) {
    const uploaded = await this.uploadImage(filePath, { articleId, contentType });
    const original = await this.getOriginalImage({ articleId, picUrl: uploaded.url });
    const cropped = await this.cropImage({ articleId, original, isHead });
    return { ...cropped, uploaded, original };
  }

  /**
   * 页面端会先访问动态编辑地址，再调用草稿详情接口，平台随后才接受该 article_id 的写入。
   * 这里通过 HTTP 请求完成同一初始化，不启动浏览器。
   */
  async prepareDraft(articleId) {
    const id = asString(articleId).trim();
    if (!id) throw new ZdmApiError('初始化什么值得买草稿时缺少 articleId');
    await this.request(`/edit/${encodeURIComponent(id)}`, { parse: 'text' });
    return await this.request(`/api/draft/${encodeURIComponent(id)}`, {
      method: 'POST',
      body: new URLSearchParams(),
    });
  }

  async publishArticle(article = {}) {
    const articleId = asString(article.articleId ?? article.article_id ?? article.id).trim();
    const title = asString(article.title).trim();
    const editorValue = asString(article.editorValue ?? article.html ?? article.body);
    if (!articleId) throw new ZdmApiError('发布什么值得买文章时缺少 articleId');
    if (!title) throw new ZdmApiError('发布什么值得买文章时缺少标题');
    if (!editorValue) throw new ZdmApiError('发布什么值得买文章时缺少 editorValue');
    if (!this.smzdmId) await this.getAccountProfile();
    const textCount = Number.isInteger(article.textCount) ? article.textCount : textCountFromHtml(editorValue);
    const awne = buildAwne(article.smzdmId || this.smzdmId, textCount);
    const imageList = article.imageList || article.images || [];
    const form = buildPublishForm({
      articleId,
      title,
      editorValue,
      seriesTitle: article.seriesTitle ?? article.series_title,
      focusImage: article.focusImage ?? article.focus_image,
      seriesId: article.seriesId ?? article.series_id,
      anonymous: article.anonymous,
      firstPublish: article.firstPublish ?? article.first_publish,
      remark: article.remark,
      createStateType: article.createStateType ?? article.create_state_type,
      aiStateType: article.aiStateType ?? article.ai_state_type,
      squarePicUrl: article.squarePicUrl ?? article.square_pic_url,
      coverImageRectangle: article.coverImageRectangle ?? article.cover_image_rectangle,
      customTopics: article.customTopics ?? article.custom_topics,
      groupId: article.groupId ?? article.group_id,
      awne,
      wne: textCount,
      imageList,
      submitType: article.submitType || 'submit',
    });
    const payload = await this.request(SUBMIT_PATH, { method: 'POST', body: form, csrf: true });
    return { payload, articleId, title, textCount, awne, url: `${POST_BASE_URL}/p/${encodeURIComponent(articleId)}/` };
  }

  async findPublication(title, { articleId = '', minSimilarity = 0.82 } = {}) {
    const html = await this.request(USER_ARTICLE_PATH, { baseUrl: USER_BASE_URL, parse: 'text' });
    const candidates = publicationCandidates(html);
    const matched = candidates
      .map(candidate => ({
        candidate,
        score: Math.max(
          publicationTitleSimilarity(title, candidate.title),
          publicationTitleSimilarity(title, candidate.context),
        ),
      }))
      .filter(item => item.score >= minSimilarity || (articleId && item.candidate.articleId === asString(articleId)))
      .sort((left, right) => right.score - left.score)[0];
    if (!matched) return null;
    const status = statusFromText(matched.candidate.statusText || matched.candidate.context);
    const visibility = status.status === 'published'
      ? await probeZdmPublicVisibility(matched.candidate.url)
      : { healthStatus: 'unknown', detail: '' };
    return {
      ...status,
      ...(status.status === 'published' ? visibility : {}),
      detail: visibility.detail || status.detail,
      title: asString(title),
      articleId: matched.candidate.articleId,
      url: matched.candidate.url,
      similarity: matched.score,
    };
  }

  async waitForPublication(title, { articleId = '', timeoutMs = 60_000, intervalMs = 3_000 } = {}) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() <= deadline) {
      const result = await this.findPublication(title, { articleId });
      if (result && result.status !== 'unknown') return result;
      const waitMs = Math.min(intervalMs, Math.max(0, deadline - Date.now()));
      if (!waitMs) break;
      await new Promise(resolve => setTimeout(resolve, waitMs));
    }
    return null;
  }
}

export {
  POST_BASE_URL,
  USER_BASE_URL,
  TOKEN_PATH,
  SUBMIT_PATH,
  USER_INFO_PATH,
  USER_ARTICLE_PATH,
  sessionCookieHeader as cookieHeader,
  findStoredSmzdmId,
};
