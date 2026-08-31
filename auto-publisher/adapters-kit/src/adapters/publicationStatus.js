import { sleep } from '../browser/humanize.js';

const TERMINAL_LOOKUP_STATUSES = new Set(['published', 'reviewing', 'failed', 'scheduled', 'draft']);

export function normalizePublicationTitle(value) {
  return String(value || '')
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[\s\p{P}\p{S}]+/gu, '');
}

function levenshtein(a, b) {
  if (!a) return b.length;
  if (!b) return a.length;
  let previous = Array.from({ length: b.length + 1 }, (_, index) => index);
  for (let i = 1; i <= a.length; i += 1) {
    const current = [i];
    for (let j = 1; j <= b.length; j += 1) {
      current[j] = Math.min(
        current[j - 1] + 1,
        previous[j] + 1,
        previous[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1),
      );
    }
    previous = current;
  }
  return previous[b.length];
}

/**
 * 平台可能截断标题，逐字输入也可能偶发漏一个字；只比较候选标题长度对应的
 * 原标题前缀，再用编辑距离容错。低于 8 个有效字符不参与自动匹配，避免误链。
 */
export function publicationTitleSimilarity(expected, actual) {
  const source = normalizePublicationTitle(expected);
  const candidate = normalizePublicationTitle(actual);
  if (source.length < 8 || candidate.length < 8) return 0;
  if (source === candidate || source.startsWith(candidate) || candidate.startsWith(source)) return 1;

  const expectedPrefix = source.slice(0, candidate.length);
  const prefixScore = 1 - (levenshtein(expectedPrefix, candidate) / Math.max(expectedPrefix.length, candidate.length));
  const fullScore = 1 - (levenshtein(source, candidate) / Math.max(source.length, candidate.length));
  return Math.max(prefixScore, fullScore);
}

export function inferPublicationStatus(text, url = '') {
  const value = String(text || '').replace(/\s+/g, ' ').trim();
  if (/未通过|审核未通过|被驳回|已驳回|发布失败|处理失败|已删除/.test(value)) return 'failed';
  if (/草稿/.test(value)) return 'draft';
  if (/审核中|待审核|审核队列|审核/.test(value)) return 'reviewing';
  if (/待发布|定时发布|已排期/.test(value)) return 'scheduled';
  if (/已发布|发布成功|正常发布|展现|阅读/.test(value) || url) return 'published';
  return 'unknown';
}

function unique(items) {
  const seen = new Set();
  return items.filter((item) => {
    const key = `${item.title}\n${item.url}\n${item.text}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

async function extractCandidates(tab, selectors) {
  const rowSelectors = selectors.articleRow || [];
  const titleSelectors = selectors.articleTitle || [];
  const linkSelectors = selectors.articleLink || [];
  const candidates = [];

  for (const rowSelector of rowSelectors) {
    let rows = [];
    try {
      rows = await tab.locator(rowSelector).evaluateAll((elements, config) => elements.slice(0, 100).map((element) => {
        const pick = (items) => {
          for (const selector of items) {
            try {
              const hit = element.querySelector(selector);
              if (hit) return hit;
            } catch { /* 非标准 CSS 候选交给下一项 */ }
          }
          return null;
        };
        const text = String(element.innerText || '').trim();
        const titleNode = pick(config.titleSelectors);
        const linkNode = pick(config.linkSelectors);
        const fallbackTitle = text.split(/\n+/).map(item => item.trim()).find(Boolean) || '';
        return {
          title: String(titleNode?.textContent || linkNode?.textContent || fallbackTitle).trim(),
          url: String(linkNode?.href || ''),
          text: text.replace(/\s+/g, ' ').slice(0, 600),
        };
      }), { titleSelectors, linkSelectors });
    } catch { /* 页面改版导致某一行选择器失效时继续尝试 */ }
    candidates.push(...rows);
  }

  // 有些平台审核中没有标准行 class；公开标题链接仍可作为已发布兜底。
  for (const linkSelector of linkSelectors) {
    try {
      const links = await tab.locator(linkSelector).evaluateAll(elements => elements.slice(0, 100).map(element => ({
        title: String(element.textContent || '').trim(),
        url: String(element.href || ''),
        text: String(element.closest('li, article, [class*="card"], [class*="item"]')?.innerText || element.textContent || '')
          .replace(/\s+/g, ' ').slice(0, 600),
      })));
      candidates.push(...links);
    } catch { /* 继续下一候选 */ }
  }
  return unique(candidates.filter(item => item.title));
}

/** 打开平台内容管理页，按容错标题匹配返回平台真实状态与公开链接。 */
export async function findPublicationInManagement(context, selectors, title, { waitMs = 3000 } = {}) {
  if (!selectors?.managementUrl) return null;
  const tab = await context.newPage();
  try {
    await tab.goto(selectors.managementUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await sleep(waitMs);
    const candidates = await extractCandidates(tab, selectors);
    let best = null;
    for (const candidate of candidates) {
      const score = publicationTitleSimilarity(title, candidate.title);
      if (!best || score > best.score) best = { ...candidate, score };
    }
    if (!best || best.score < 0.82) return null;
    const status = inferPublicationStatus(best.text, best.url);
    return {
      status,
      url: best.url || '',
      title: best.title,
      detail: best.text,
      score: Number(best.score.toFixed(3)),
    };
  } finally {
    await tab.close().catch(() => {});
  }
}

/** 发布后的列表轮询；作品仍为草稿也立即返回，避免占住队列一直等待。 */
export async function pollPublicationInManagement(adapter, page, title, timeoutMs, intervalMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await sleep(Math.min(intervalMs, Math.max(0, deadline - Date.now())));
    if (page.isClosed()) return null;
    try {
      const result = await adapter.fetchPublicationStatus(page, title);
      if (result && TERMINAL_LOOKUP_STATUSES.has(result.status)) return result;
    } catch { /* 列表临时失败，下轮重试 */ }
  }
  return null;
}
