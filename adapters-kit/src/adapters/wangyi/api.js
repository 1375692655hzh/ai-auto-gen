import fs from 'node:fs/promises';
import path from 'node:path';
import { getStorageState } from '../../runtime/storage.js';
import { publicationTitleSimilarity } from '../publicationStatus.js';
import { withRetry } from '../../http/retry.js';
import { isNonRepeatableRejection } from '../../domain/publicationPolicy.js';

const BASE_URL = 'https://mp.163.com';
const EDITOR_URL = 'https://mp.163.com/subscribe_v4/index.html#/article-publish';
const USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36';
const API_COOKIE_URL = 'https://mp.163.com/wemedia/article/status/api/publishV2.do';

/** 网易号内容管理接口的 contentState 字典；-1 只用于列表筛选，不代表单篇文章。 */
export const WANGYI_CONTENT_STATUS = Object.freeze({
  '-1': { label: '全部状态' },
  0: { label: '草稿', status: 'draft' },
  1: { label: '审核中', status: 'reviewing' },
  2: { label: '未通过', status: 'failed' },
  3: { label: '已发布', status: 'published' },
  4: { label: '处理中', status: 'processing' },
  5: { label: '处理失败', status: 'failed' },
  6: { label: '未通过', status: 'failed' },
  7: { label: '作者下线', status: 'published', healthStatus: 'offline' },
  8: { label: '待发布', status: 'scheduled' },
  9: { label: '已删除', status: 'published', healthStatus: 'deleted' },
  10: { label: '作者删除', status: 'published', healthStatus: 'deleted' },
  11: { label: 'MCN主账号下线', status: 'published', healthStatus: 'offline' },
});

// 网易号当前接口对账号封禁的稳定信号：navinfo.do / publishV2.do 返回 code=100023，
// 资料接口成功返回时 onlineState=7 表示 FORBIDDEN。
export const WANGYI_BANNED_ERROR_CODES = Object.freeze([100023]);
export const WANGYI_FORBIDDEN_ONLINE_STATE = 7;

export class WangyiApiError extends Error {
  constructor(message, { status = 0, code = 0, payload = null, accountStatus = '' } = {}) {
    super(message);
    this.name = 'WangyiApiError';
    this.status = status;
    this.code = code;
    this.payload = payload;
    this.accountStatus = accountStatus;
  }
}

export function isWangyiCaptchaError(error) {
  const payloadData = error?.payload?.data;
  const message = asString(error?.message || error?.payload?.msg || error?.payload?.message);
  return (error instanceof WangyiApiError || error?.name === 'WangyiApiError') && (
    Number(error.code) === 1001
    || payloadData?.captchaRequired === true
    || payloadData?.needCaptcha === true
    || /图形验证码|验证码验证|captcha/i.test(message)
  );
}

function parseJson(value, fallback = {}) {
  try { return JSON.parse(value); } catch { return fallback; }
}

function asString(value) {
  return value == null ? '' : String(value);
}

export function classifyWangyiAccountStatus({ code, payload = null, profile = null } = {}) {
  const responseCode = Number(code ?? payload?.code ?? 0);
  const data = payload?.data || payload || {};
  const onlineState = Number(
    profile?.onlineState
      ?? profile?.online_state
      ?? data?.onlineState
      ?? data?.online_state
      ?? 0,
  );
  const message = asString(
    payload?.msg
      || payload?.message
      || payload?.errorMsg
      || data?.msg
      || data?.message,
  ).trim();

  if (
    WANGYI_BANNED_ERROR_CODES.includes(responseCode)
    || onlineState === WANGYI_FORBIDDEN_ONLINE_STATE
    || /(?:账号|帐号|账户|帐户).*(?:封禁|查封|封停|冻结)|(?:account|user).*(?:banned|blocked)|(?:banned|blocked).*(?:account|user)/i.test(message)
  ) {
    return 'banned';
  }
  return '';
}

function validateResponsePayload({ status, ok, text = '', payload, allowedCodes }) {
  const parsed = payload || parseJson(text, { msg: text.slice(0, 300) });
  const code = Number(parsed?.code ?? 0);
  const accountStatus = classifyWangyiAccountStatus({ code, payload: parsed });
  if (!ok || (parsed?.code != null && !allowedCodes.includes(code))) {
    throw new WangyiApiError(
      parsed?.msg || parsed?.message || `网易号接口请求失败（HTTP ${status}）`,
      { status, code, payload: parsed, accountStatus },
    );
  }
  return parsed;
}

function cookieDomainMatches(cookieDomain, hostname) {
  const domain = String(cookieDomain || '').trim().replace(/^\./, '').toLowerCase();
  const host = String(hostname || '').trim().toLowerCase();
  return Boolean(domain) && (host === domain || host.endsWith(`.${domain}`));
}

function cookiePathMatches(cookiePath, pathname) {
  const path = String(cookiePath || '/');
  const target = String(pathname || '/');
  if (path === '/') return true;
  if (!target.startsWith(path)) return false;
  return path.endsWith('/') || target.length === path.length || target[path.length] === '/';
}

function cookieHeader(cookies = [], requestUrl = API_COOKIE_URL) {
  let url;
  try {
    url = new URL(requestUrl, BASE_URL);
  } catch {
    url = new URL(API_COOKIE_URL);
  }
  const now = Date.now() / 1000;
  const eligible = cookies
    .filter(cookie => cookie && cookie.name && cookieDomainMatches(cookie.domain, url.hostname))
    .filter(cookie => cookiePathMatches(cookie.path, url.pathname))
    .filter(cookie => Number(cookie.expires || -1) <= 0 || Number(cookie.expires) > now)
    .sort((left, right) => {
      const pathDelta = String(right.path || '/').length - String(left.path || '/').length;
      if (pathDelta) return pathDelta;
      return String(right.domain || '').length - String(left.domain || '').length;
    });
  const seen = new Set();
  return eligible
    .filter(cookie => {
      if (seen.has(cookie.name)) return false;
      seen.add(cookie.name);
      return true;
    })
    .map(cookie => `${cookie.name}=${cookie.value}`)
    .join('; ');
}

function localStorageEntries(storageState = {}) {
  return (storageState.origins || []).flatMap(origin => (
    (origin.localStorage || []).map(item => ({ ...item, origin: origin.origin }))
  ));
}

function findStoredToken(storageState = {}) {
  const entries = localStorageEntries(storageState);
  const tokenEntry = entries.find(item => /^(ursToken|urs_token|urs-token)$/i.test(item.name));
  if (tokenEntry?.value) return String(tokenEntry.value);
  const cookie = (storageState.cookies || []).find(item => /^(ursToken|urs_token|urs-token)$/i.test(item.name));
  return cookie?.value ? String(cookie.value) : '';
}

export function getWangyiSessionMetadata(storageState = {}) {
  return {
    cookies: cookieHeader(storageState.cookies || []),
    storedUrsToken: findStoredToken(storageState),
  };
}

export function replaceWangyiImageSources(html, uploadedUrls = []) {
  const urls = uploadedUrls.map(value => asString(value).trim()).filter(Boolean);
  let index = 0;
  return asString(html)
    .replace(/(\bsrc\s*=\s*["'])data:image\/[^"']+(["'])/gi, (match, prefix, suffix) => {
      const url = urls[index++];
      return url ? `${prefix}${url}${suffix}` : match;
    });
}

export function buildWangyiPublishForm({
  wemediaId,
  articleId = '-1',
  title,
  html,
  operation = 'publish',
  cover = 'auto',
  scheduled = 0,
  firstPub = 2,
  onlineState = 2,
  picUrl = '',
  original = 0,
  ursToken = '',
  sign = '',
  timestamp = '',
  subjectId = '',
  essayId = '',
  essayTitle = '',
  essayUrl = '',
  essayClassify = '',
} = {}) {
  const form = new URLSearchParams();
  const fields = {
    wemediaId, articleId, title, content: html, cover, operation, scheduled,
    ...(operation === 'publish' ? { firstPub } : {}),
    ursToken, onlineState, picUrl, original, subjectId, essayId, essayTitle,
    essayUrl, essayClassify,
    ...(operation === 'publish' ? { sign, timestamp } : {}),
  };
  for (const [key, value] of Object.entries(fields)) form.set(key, asString(value));
  return form;
}

export function mapWangyiContentStatus(item = {}) {
  const state = Number(item.contentState);
  const articleId = asString(item.articleId || item.commentId).trim();
  const publicUrl = articleId ? `https://www.163.com/dy/article/${articleId}.html` : '';
  const definition = WANGYI_CONTENT_STATUS[state];
  const base = {
    platformState: Number.isInteger(state) ? state : null,
    platformStatus: definition?.label || '未知状态',
  };
  if (state === 3) {
    const restrictionReason = asString(
      item.unrecomReason
      || item.unrecommendReason
      || item.recommendReason
      || item.reason,
    ).trim();
    // 网易把“已发布”和“游客可见”拆成两个字段；只要有分发限制原因，
    // 即便文案不是“受限”，也应归入线上异常，保留原因为运营排查依据。
    const restricted = Boolean(restrictionReason)
      && (
        item.isRecommend === undefined
        || Number(item.isRecommend) === 0
        || /仅自己可见|受限|不展示|影响(?:内容)?展现|广告信息/.test(restrictionReason)
      );
    return {
      ...base,
      status: 'published',
      healthStatus: restricted ? 'restricted' : 'normal',
      url: publicUrl,
      detail: restricted ? restrictionReason : '',
    };
  }
  if (!definition?.status) {
    return { ...base, status: 'unknown', url: '', detail: '网易号返回了未识别的内容状态' };
  }
  const detail = asString(
    item.reason
    || item.unrecomReason
    || item.unrecommendReason
    || item.auditReason
    || item.errorMsg,
  ).trim();
  const details = {
    draft: '网易号内容仍为草稿',
    reviewing: '网易号内容审核中',
    failed: detail || (state === 5 ? '网易号内容处理失败' : '网易号内容审核未通过'),
    processing: '网易号内容处理中',
    scheduled: '网易号内容待发布',
    7: '网易号内容已由作者下线',
    9: '网易号内容已删除',
    10: '网易号内容已由作者删除',
    11: '网易号内容已由 MCN 主账号下线',
  };
  const result = {
    ...base,
    status: definition.status,
    url: definition.status === 'published' ? publicUrl : '',
    detail: details[definition.status] || details[state] || detail || definition.label,
  };
  if (
    definition.status === 'failed'
    && (state === 2 || state === 6 || isNonRepeatableRejection(result.detail))
  ) {
    result.healthStatus = 'rejected';
  }
  if (definition.healthStatus) result.healthStatus = definition.healthStatus;
  return result;
}

function findContentMatch(items, title, articleId = '') {
  if (articleId) {
    const exact = items.find(item => asString(item.articleId || item.commentId) === asString(articleId));
    if (exact) return exact;
  }
  let best = null;
  for (const item of items) {
    const score = publicationTitleSimilarity(title, item.title || '');
    if (!best || score > best.score) best = { item, score };
  }
  return best && best.score >= 0.82 ? best.item : null;
}

function appendSessionQuery(url, session) {
  if (session.wemediaId) url.searchParams.set('wemediaId', session.wemediaId);
  if (session.realUserId) url.searchParams.set('realUserId', session.realUserId);
  url.searchParams.set('_', String(Date.now()));
  return url;
}

export class WangyiApiClient {
  constructor(accountId, storageState = getStorageState(accountId), {
    ursTokenProvider = null,
    captchaRecovery = null,
  } = {}) {
    this.accountId = Number(accountId) || 0;
    this.storageState = storageState || {};
    this.metadata = getWangyiSessionMetadata(this.storageState);
    this.ursTokenProvider = ursTokenProvider;
    this.captchaRecovery = captchaRecovery;
    this.session = { wemediaId: '', realUserId: '' };
  }

  reloadStorageState(storageState = getStorageState(this.accountId)) {
    this.storageState = storageState || {};
    this.metadata = getWangyiSessionMetadata(this.storageState);
    return this.storageState;
  }

  headers(extra = {}) {
    return {
      Accept: 'application/json, text/javascript, */*; q=0.01',
      Cookie: this.metadata.cookies,
      Origin: BASE_URL,
      Referer: EDITOR_URL,
      'User-Agent': USER_AGENT,
      'X-Requested-With': 'XMLHttpRequest',
      ...extra,
    };
  }

  sessionUrl(pathname, query = {}) {
    const url = new URL(pathname, BASE_URL);
    appendSessionQuery(url, this.session);
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null) url.searchParams.set(key, asString(value));
    }
    return url;
  }

  async request(pathname, {
    method = 'GET', body, headers = {}, query = {}, json = false, multipart = false,
    allowedCodes = [1], includeSession = true,
  } = {}) {
    const operationName = `wangyi ${method} ${pathname}`;
    let replayBody = body;
    let replayQuery = query;
    const requestUrl = () => includeSession ? this.sessionUrl(pathname, replayQuery) : new URL(pathname, BASE_URL);
    const execute = async () => {
      const url = requestUrl();
      const requestHeaders = this.headers(headers);
      let requestBody = replayBody;
      if (json && replayBody !== undefined) {
        requestHeaders['Content-Type'] = 'application/json';
        requestBody = JSON.stringify(replayBody);
      } else if (!multipart && replayBody instanceof URLSearchParams) {
        requestHeaders['Content-Type'] = 'application/x-www-form-urlencoded; charset=utf-8';
        requestBody = replayBody.toString();
      }
      const response = await fetch(url, {
        method,
        headers: requestHeaders,
        body: requestBody,
      });
      const text = await response.text();
      return validateResponsePayload({
        status: response.status,
        ok: response.ok,
        text,
        allowedCodes,
      });
    };

    try {
      return await withRetry(execute, { operationName });
    } catch (error) {
      if (!this.captchaRecovery || !isWangyiCaptchaError(error)) throw error;

      const recovered = await this.captchaRecovery({
        accountId: this.accountId,
        url: requestUrl().toString(),
        pathname,
        method,
        body,
        headers: this.headers(headers),
        query,
      });
      this.reloadStorageState(recovered?.storageState || undefined);

      // 页面验证码恢复会同时刷新编辑器里的动态表单凭证；正式 publish 重试必须带上页面最新表单，
      // 仅更新 Cookie 仍可能让网易号再次返回验证码。
      if (recovered?.requestBody !== undefined) {
        replayBody = body instanceof URLSearchParams
          ? new URLSearchParams(recovered.requestBody)
          : recovered.requestBody;
      }
      if (recovered?.query !== undefined) replayQuery = recovered.query;

      if (recovered?.payload) {
        try {
          return validateResponsePayload({
            status: recovered.status ?? 200,
            ok: recovered.ok ?? true,
            payload: recovered.payload,
            allowedCodes,
          });
        } catch (browserError) {
          if (!isWangyiCaptchaError(browserError)) throw browserError;
        }
      }

      // 浏览器侧同样遇到验证码时，使用浏览器刚回写的最新状态再走一次接口。
      try {
        return await withRetry(execute, { maxAttempts: 1, operationName });
      } catch (retryError) {
        if (recovered?.recoveryDiagnostics) {
          retryError.message = `${retryError.message} [验证码恢复诊断: ${JSON.stringify(recovered.recoveryDiagnostics)}]`;
        }
        throw retryError;
      }
    }
  }

  updateSession(data = {}) {
    this.session.wemediaId = asString(data.wemediaId).trim();
    this.session.realUserId = asString(data.realUserId).trim();
    return data;
  }

  async getAccountProfile() {
    if (!this.metadata.cookies) throw new WangyiApiError('网易号登录态中没有可用 Cookie');
    const payload = await this.request('/wemedia/navinfo.do', { includeSession: false });
    const data = this.updateSession(payload?.data || {});
    const username = asString(data.loginUser || data.realUserId || '').trim();
    const profile = {
      profileName: asString(data.tname || '').trim(),
      username,
      ...(/^\d{11}$/.test(username) ? { phone: username } : {}),
      wemediaId: this.session.wemediaId,
      realUserId: this.session.realUserId,
      todayPubCount: Number(data.todayPubCount || 0),
      maxDailyPublishCount: Number(data.maxDailyPublishCount || 0),
      onlineState: Number(data.onlineState ?? 0),
    };
    const accountStatus = classifyWangyiAccountStatus({ profile });
    return accountStatus ? { ...profile, accountStatus } : profile;
  }

  async checkLogin() {
    try {
      const profile = await this.getAccountProfile();
      const accountStatus = profile.accountStatus || classifyWangyiAccountStatus({ profile });
      return {
        ok: Boolean(profile.wemediaId) && accountStatus !== 'banned',
        profile,
        ...(accountStatus ? { accountStatus } : {}),
      };
    } catch (error) {
      if (error instanceof WangyiApiError) {
        const accountStatus = error.accountStatus || classifyWangyiAccountStatus({
          code: error.code,
          payload: error.payload,
        });
        return {
          ok: false,
          profile: null,
          ...(accountStatus ? { accountStatus } : {}),
          error,
        };
      }
      throw error;
    }
  }

  async getPublishLimit() {
    const profile = await this.getAccountProfile();
    if (profile.accountStatus === 'banned') {
      throw new WangyiApiError('网易号账号已被封禁', {
        code: WANGYI_BANNED_ERROR_CODES[0],
        payload: profile,
        accountStatus: 'banned',
      });
    }
    return Math.max(0, profile.maxDailyPublishCount - profile.todayPubCount);
  }

  async getClassifies() {
    const payload = await this.request('/wemedia/article/status/api/classifies/get.do');
    return payload?.data || {};
  }

  async uploadImage(filePath, contentType = 'application/octet-stream') {
    const bytes = await fs.readFile(filePath);
    const form = new FormData();
    form.append('file', new Blob([bytes], { type: contentType }), path.basename(filePath));
    form.append('from', 'neteasecode_mp');
    const payload = await this.request('/api/v3/upload/picupload', {
      method: 'POST', body: form, multipart: true, allowedCodes: [200],
    });
    const data = payload?.data || {};
    if (!data.url) throw new WangyiApiError('网易号图片上传响应缺少 url', { payload });
    return data;
  }

  async addMaterialPicture(picUrl) {
    return await this.request('/wemedia/material/picture/addPic.do', {
      method: 'POST', query: {
        title: '上传图片', picUrl, watermarkUrl: picUrl, state: 1, source: 'publish',
      },
    });
  }

  async batchUploadImageUrls(urls = []) {
    const form = new URLSearchParams({ uploadtype: 'cms', from: 'neteasecode_mp', bucketName: 'dingyue', fixWidth: '' });
    for (const url of urls) form.append('urls', asString(url));
    return await this.request('/api/v2/upload/batchUploadImgUrl', {
      method: 'POST', body: form,
    });
  }

  async getUrsToken(context = {}) {
    if (typeof this.ursTokenProvider === 'function') {
      const provided = await this.ursTokenProvider(context);
      if (provided) return asString(provided);
    }
    return asString(context.ursToken || this.metadata.storedUrsToken || '').trim();
  }

  async saveDraft({ articleId = '-1', title, html, cover = 'auto', picUrl = '', onlineState = 2, original = 0, ursToken = '' } = {}) {
    const token = await this.getUrsToken({ title, html, ursToken });
    const form = buildWangyiPublishForm({
      wemediaId: this.session.wemediaId, articleId, title, html, cover,
      operation: 'saveDraft', onlineState, original, picUrl, ursToken: token,
    });
    const payload = await this.request('/wemedia/article/status/api/publishV2.do', {
      method: 'POST', body: form,
    });
    const data = asString(payload?.data);
    const matched = data.match(/(?:docId|articleId)=([^&,]+)/i);
    return { payload, articleId: matched?.[1] || articleId };
  }

  async publishArticle({ articleId = '-1', title, html, cover = 'auto', picUrl = '', onlineState = 2, original = 0, ursToken = '', sign = '', timestamp = '', subjectId = '', essayId = '', essayTitle = '', essayUrl = '', essayClassify = '' } = {}) {
    const token = await this.getUrsToken({ title, html, ursToken });
    const form = buildWangyiPublishForm({
      wemediaId: this.session.wemediaId, articleId, title, html, cover,
      operation: 'publish', onlineState, original, picUrl, ursToken: token,
      sign, timestamp, subjectId, essayId,
      essayTitle, essayUrl, essayClassify,
    });
    return await this.request('/wemedia/article/status/api/publishV2.do', {
      method: 'POST', body: form,
    });
  }

  async listArticles({ pageNo = 1, size = 20 } = {}) {
    if (!this.session.wemediaId) await this.getAccountProfile();
    const payload = await this.request('/wemedia/content/manage/list.do', {
      method: 'POST', body: new URLSearchParams({
        pageNo: String(pageNo), size: String(size), contentType: '0',
        contentState: '-1', mergeUnPassed: 'false', filterState: '0',
      }),
    });
    return payload?.data?.list || [];
  }

  async findPublication(title, { articleId = '' } = {}) {
    for (let pageNo = 1; pageNo <= 5; pageNo += 1) {
      const items = await this.listArticles({ pageNo, size: 20 });
      const item = findContentMatch(items, title, articleId);
      if (item) return { ...mapWangyiContentStatus(item), article: item };
      if (items.length < 20) break;
    }
    return null;
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
