import fs from 'node:fs/promises';
import path from 'node:path';
import { getStorageState } from '../../runtime/storage.js';
import { publicationTitleSimilarity } from '../publicationStatus.js';
import { withRetry } from '../../http/retry.js';

const BASE_URL = 'https://mp.sohu.com';
const API_OK = 2_000_000;
const FIND_PAGE_SIZE = 100;
const MAX_FIND_PAGES = 20;
const PAGE_BATCH_SIZE = 4;
const USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36';
const SOHU_BANNED_STATUS_PATTERN = /查封|封禁|封号|冻结|封停|禁用|banned|blocked|frozen|suspend/i;

export class SohuApiError extends Error {
  constructor(message, { status = 0, code = 0, payload = null } = {}) {
    super(message);
    this.name = 'SohuApiError';
    this.status = status;
    this.code = code;
    this.payload = payload;
  }
}

function parseJson(value, fallback = {}) {
  try { return JSON.parse(value); } catch { return fallback; }
}

function isPositiveStatusFlag(value) {
  if (value === true) return true;
  const normalized = String(value ?? '').trim().toLowerCase();
  return normalized === 'true' || normalized === 'yes' || normalized === '1' || Number(value) > 0;
}

/** 搜狐 register-info 的账号状态；statusName 是页面“已查封”的直接来源。 */
export function isSohuAccountBanned(account = {}) {
  const statusText = [
    account.statusName,
    account.statusText,
    account.banStatusName,
    account.freezeStatusName,
  ].map(value => String(value || '').trim()).filter(Boolean).join(' ');
  return SOHU_BANNED_STATUS_PATTERN.test(statusText)
    || isPositiveStatusFlag(account.banStatus)
    || isPositiveStatusFlag(account.freezeStatus);
}

export function getSohuSessionMetadata(storageState = {}) {
  const cookies = (storageState.cookies || [])
    .filter(cookie => String(cookie.domain || '').endsWith('sohu.com'))
    .map(cookie => `${cookie.name}=${cookie.value}`)
    .join('; ');
  const origin = (storageState.origins || []).find(item => item.origin === BASE_URL);
  const localStorage = Object.fromEntries((origin?.localStorage || []).map(item => [item.name, item.value]));
  const currentAccount = parseJson(localStorage.currentAccount, {});
  const vuex = parseJson(localStorage.vuex, {});
  const accountFromVuex = vuex?.app?.userInfo || {};
  const accountId = Number(currentAccount.id || accountFromVuex.id || 0) || 0;
  const spCm = Object.entries(localStorage).find(([key]) => /-sp-cm$/.test(key))?.[1]
    || localStorage['preview-sp-cm']
    || '';
  return {
    accountId,
    cookies,
    spCm,
    dvId: localStorage['preview-dv-id'] || '',
    localStorage,
  };
}

export function normalizeSohuAssetUrl(value) {
  const url = String(value || '').trim();
  if (!url) return '';
  return url.startsWith('//') ? `https:${url}` : url;
}

export function replaceSohuImageSources(html, uploadedUrls) {
  const urls = uploadedUrls.map(normalizeSohuAssetUrl);
  let index = 0;
  return String(html || '').replace(
    /(\bsrc\s*=\s*["'])data:image\/[^"']+(["'])/gi,
    (match, prefix, suffix) => `${prefix}${urls[index++] || match.slice(prefix.length, -suffix.length)}${suffix}`,
  );
}

export function mapSohuNewsStatus(news = {}, accountId = 0) {
  const status = Number(news.status);
  const auditStatus = Number(news.auditStatus);
  const detail = String(news.rejectReason || '').trim();
  const url = status === 4 && auditStatus === 4 && news.id
    ? `https://www.sohu.com/a/${news.id}_${accountId}`
    : '';

  if (detail || auditStatus === 8 || status === 3) {
    return { status: 'failed', url: '', detail: detail || '搜狐平台审核未通过' };
  }
  if (status === 4 && auditStatus === 4) return { status: 'published', url, detail: '' };
  if (status === 1) return { status: 'draft', url: '', detail: '搜狐内容仍为草稿' };
  if ([1, 2, 3].includes(auditStatus) || status === 2) {
    return { status: 'reviewing', url: '', detail: '搜狐内容审核中' };
  }
  return { status: 'unknown', url: '', detail: '搜狐返回了未识别的内容状态' };
}

export function buildSohuPublishPayload({
  accountId,
  title,
  html,
  categoryId = -1,
  channelId = 28,
  tags = '',
  cover = '',
} = {}) {
  const customTags = String(tags || '').split(/[，,]/).map(item => item.trim()).filter(Boolean);
  return {
    title: String(title || '').trim(),
    brief: '',
    content: String(html || ''),
    channelId: Number(channelId) || 28,
    categoryId: Number.isInteger(Number(categoryId)) ? Number(categoryId) : -1,
    id: 0,
    userColumnId: 0,
    columnNewsIds: [],
    businessCode: 0,
    declareOriginal: false,
    cover: String(cover || ''),
    topicIds: [],
    isAd: 0,
    userLabels: '[]',
    reprint: false,
    customTags: customTags.join(','),
    infoResource: 0,
    sourceUrl: '',
    visibleToLoginedUsers: 0,
    attrIds: [],
    accountId: Number(accountId),
  };
}

function findNewsMatch(items, title, newsId = 0) {
  if (newsId) {
    const byId = items.find(item => Number(item.id) === Number(newsId));
    if (byId) return byId;
  }
  let best = null;
  for (const item of items) {
    const score = publicationTitleSimilarity(title, item.title);
    if (!best || score > best.score) best = { item, score };
  }
  return best && best.score >= 0.82 ? best.item : null;
}

function numberFrom(...values) {
  for (const value of values) {
    const number = Number(value);
    if (Number.isFinite(number) && number >= 0) return number;
  }
  return 0;
}

function newsTotalPages(data, pageSize) {
  const pageInfo = data?.pagination || data?.pageInfo || {};
  const explicit = numberFrom(
    data?.totalPage, data?.totalPages, data?.pageCount,
    pageInfo.totalPage, pageInfo.totalPages, pageInfo.pageCount,
  );
  if (explicit) return Math.ceil(explicit);

  const total = numberFrom(data?.total, data?.totalCount, data?.count, pageInfo.total, pageInfo.totalCount);
  return total ? Math.ceil(total / pageSize) : 0;
}

function newsHasMore(data, items, pageSize, page) {
  const pageInfo = data?.pagination || data?.pageInfo || {};
  const explicit = data?.hasMore ?? data?.hasNext ?? pageInfo.hasMore ?? pageInfo.hasNext;
  if (typeof explicit === 'boolean') return explicit;
  const totalPages = newsTotalPages(data, pageSize);
  if (totalPages) return page < totalPages;
  return items.length >= pageSize;
}

export class SohuApiClient {
  constructor(accountId, storageState = getStorageState(accountId)) {
    this.storageAccountId = Number(accountId) || 0;
    this.storageState = storageState || {};
    this.metadata = getSohuSessionMetadata(this.storageState);
    this.accountId = this.metadata.accountId || this.storageAccountId;
    if (!this.accountId) throw new SohuApiError('搜狐登录态中缺少 accountId');
  }

  headers(extra = {}) {
    return {
      Accept: '*/*',
      Cookie: this.metadata.cookies,
      Origin: BASE_URL,
      Referer: `${BASE_URL}/mpfe/v4/contentManagement/news/addarticle`,
      'User-Agent': USER_AGENT,
      'X-Requested-With': 'XMLHttpRequest',
      ...(this.metadata.dvId ? { 'dv-id': this.metadata.dvId } : {}),
      ...(this.metadata.spCm ? { 'sp-cm': this.metadata.spCm } : {}),
      ...extra,
    };
  }

  async request(pathname, { method = 'GET', body, headers = {}, formData = false } = {}) {
    return withRetry(async () => {
      const url = new URL(pathname, BASE_URL);
      const requestHeaders = this.headers({ ...headers });
      if (!formData && body !== undefined) requestHeaders['Content-Type'] = 'application/json';
      const response = await fetch(url, {
        method,
        headers: requestHeaders,
        body: formData ? body : body === undefined ? undefined : JSON.stringify(body),
      });
      const text = await response.text();
      const payload = parseJson(text, { msg: text.slice(0, 300) });
      const code = Number(payload?.code || 0);
      if (!response.ok || (payload && payload.success === false) || (payload && payload.code && code !== API_OK)) {
        throw new SohuApiError(payload?.msg || payload?.detail || `搜狐接口请求失败（HTTP ${response.status}）`, {
          status: response.status,
          code,
          payload,
        });
      }
      return payload;
    }, { operationName: `sohu ${method} ${pathname}` });
  }

  async getAccountProfile() {
    const local = this.metadata.localStorage;
    const current = parseJson(local.currentAccount, {});
    const [pendingResult, registerResult] = await Promise.allSettled([
      this.request('/mpbp/bp/account/pending?accountId=' + this.accountId),
      this.request('/mpbp/bp/account/register-info'),
    ]);
    const pendingPayload = pendingResult.status === 'fulfilled' ? pendingResult.value : null;
    const registerPayload = registerResult.status === 'fulfilled' ? registerResult.value : null;
    if (!pendingPayload && !registerPayload) {
      const error = pendingResult.reason instanceof SohuApiError
        ? pendingResult.reason
        : registerResult.reason;
      if (error) throw error;
      throw new SohuApiError('搜狐账号资料获取失败');
    }

    const pending = pendingPayload?.data || {};
    const registration = registerPayload?.data || {};
    const account = registration.account || {};
    const user = registration.user || {};
    const accountId = Number(pending.accountId || account.id || current.id || this.accountId) || this.accountId;
    const phone = String(user.mobile || '').trim();
    return {
      profileName: String(pending.nickName || account.nickName || current.nickName || '').trim(),
      username: String(pending.userCode || pending.email || user.mobile || user.email || user.userCode || '').trim(),
      ...(phone ? { phone } : {}),
      accountId,
      channelId: Number(pending.channelId ?? account.channelId ?? current.channelId ?? 28) || 28,
      status: account.status ?? null,
      statusName: String(account.statusName || '').trim(),
      banStatus: account.banStatus ?? null,
      freezeStatus: account.freezeStatus ?? null,
    };
  }

  async checkLogin() {
    try {
      const profile = await this.getAccountProfile();
      if (isSohuAccountBanned(profile)) {
        return {
          ok: false,
          accountStatus: 'banned',
          profile,
          error: new SohuApiError(`搜狐账号${profile.statusName || '已查封'}`),
        };
      }
      return { ok: true, profile };
    } catch (error) {
      if (error instanceof SohuApiError) return { ok: false, profile: null, error };
      throw error;
    }
  }

  async getPublishLimit() {
    const payload = await this.request(`/mpbp/bp/news/v4/news/publishLimit?type=1&accountId=${this.accountId}&_=${Date.now()}`);
    return Number(payload?.data?.['1'] ?? 0);
  }

  async uploadImage(filePath, contentType = 'application/octet-stream') {
    const bytes = await fs.readFile(filePath);
    const form = new FormData();
    form.append('file', new Blob([bytes], { type: contentType }), path.basename(filePath));
    form.append('accountId', String(this.accountId));
    const payload = await this.request(`/commons/front/outerUpload/image/file?accountId=${this.accountId}`, {
      method: 'POST', body: form, formData: true,
    });
    const url = normalizeSohuAssetUrl(payload?.url || payload?.data?.url);
    if (!url) throw new SohuApiError('搜狐图片上传响应缺少 url', { payload });
    return { ...payload, url };
  }

  async publishArticle(article) {
    return await this.request(`/mpbp/bp/news/v4/news/publish/v2?accountId=${this.accountId}`, {
      method: 'POST', body: article,
    });
  }

  async fetchNewsPage(page, pageSize) {
    const params = new URLSearchParams({
      psize: String(pageSize), newsType: '0', statusType: '1', columnId: '',
      pno: String(page), streamId: '', accountId: String(this.accountId), _: String(Date.now()),
    });
    const payload = await this.request(`/mpbp/bp/news/v4/users/news?${params}`);
    const data = payload?.data || {};
    return { data, items: Array.isArray(data.news) ? data.news : [] };
  }

  async listNews({ page = 1, pageSize = 20 } = {}) {
    const result = await this.fetchNewsPage(page, pageSize);
    return result.items;
  }

  async findPublication(title, { newsId = 0, pageSize = FIND_PAGE_SIZE } = {}) {
    const first = await this.fetchNewsPage(1, pageSize);
    const items = [...first.items];
    const totalPages = Math.min(
      Math.max(newsTotalPages(first.data, pageSize), 1),
      MAX_FIND_PAGES,
    );

    if (totalPages > 1) {
      for (let start = 2; start <= totalPages; start += PAGE_BATCH_SIZE) {
        const pages = Array.from(
          { length: Math.min(PAGE_BATCH_SIZE, totalPages - start + 1) },
          (_, index) => start + index,
        );
        const results = await Promise.all(pages.map(page => this.fetchNewsPage(page, pageSize)));
        for (const result of results) items.push(...result.items);
      }
    } else if (newsHasMore(first.data, first.items, pageSize, 1)) {
      // 某些版本的接口不返回总页数，只能在拿到短页时停止；限制上限避免异常响应造成无界请求。
      for (let page = 2; page <= MAX_FIND_PAGES; page += 1) {
        const result = await this.fetchNewsPage(page, pageSize);
        items.push(...result.items);
        if (!newsHasMore(result.data, result.items, pageSize, page)) break;
      }
    }

    const item = findNewsMatch(items, title, newsId);
    return item ? { ...mapSohuNewsStatus(item, this.accountId), news: item } : null;
  }

  async waitForPublication(title, { newsId = 0, timeoutMs = 60_000, intervalMs = 3_000 } = {}) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() <= deadline) {
      const result = await this.findPublication(title, { newsId });
      if (result && result.status !== 'unknown') return result;
      const waitMs = Math.min(intervalMs, Math.max(0, deadline - Date.now()));
      if (!waitMs) break;
      await new Promise(resolve => setTimeout(resolve, waitMs));
    }
    return null;
  }
}
