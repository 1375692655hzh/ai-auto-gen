/**
 * 网易号 adapter —— 登录使用浏览器，登录后的检查、发文和状态核验全部走接口。
 */
import { BaseAdapter, NeedLoginError, PublishRejectedError, PublishResultUnknownError } from '../base.js';
import { firstVisible } from '../helpers.js';
import { sleep } from '../../browser/humanize.js';
import { getCloakBrowserProxy, withHeadlessAccountContext } from '../../browser/manager.js';
import { config } from '../../config.js';
import { recognizeYidunWithTtOcr } from '../../captcha/ttOcrClient.js';
import {
  WangyiApiClient, WangyiApiError, replaceWangyiImageSources,
} from './api.js';
import { checkPlatformCover } from '../../domain/platformConstraints.js';
import S from './selectors.js';

const WANGYI_EDITOR_URL = 'https://mp.163.com/subscribe_v4/index.html#/article-publish';

function browserRequestBody(body) {
  if (body instanceof URLSearchParams) return body.toString();
  if (typeof body === 'string') return body;
  return null;
}

function htmlToPlainText(html) {
  return String(html || '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(?:p|div|li|h[1-6])>/gi, '\n')
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/\s+/g, ' ')
    .trim();
}

/** 从原始 publishV2 表单提取 API 重试所需的业务字段，不读取或记录凭证字段。 */
export function parseWangyiRecoveryForm(body) {
  const form = new URLSearchParams(body || '');
  const html = form.get('content') || '';
  return {
    articleId: form.get('articleId') || '-1',
    operation: form.get('operation') || '',
    title: form.get('title') || '',
    html,
    text: htmlToPlainText(html),
  };
}

/**
 * 将编辑页保存后刷新的动态凭证合并回原始业务表单，保留真实文章标题、正文和文章 ID。
 * 编辑页探针只用于刷新会话，不能把探针内容带入正式 publish 请求。
 */
export function mergeWangyiRefreshedForm(originalBody, refreshedBody, dynamicFields = {}) {
  const original = new URLSearchParams(originalBody || '');
  const refreshed = new URLSearchParams(refreshedBody || '');
  for (const key of ['ursToken', 'sign', 'timestamp', 'NECaptchaValidate']) {
    const value = refreshed.get(key) || dynamicFields[key] || '';
    if (value) original.set(key, value);
  }
  return original.toString();
}

function summarizeWangyiFormFields(body) {
  const form = new URLSearchParams(body || '');
  const keys = [...new Set([...form.keys()])].sort();
  return {
    keys,
    hasArticleId: Boolean(form.get('articleId')),
    hasUrsToken: Boolean(form.get('ursToken')),
    hasSign: Boolean(form.get('sign')),
    hasTimestamp: Boolean(form.get('timestamp')),
    hasCaptcha: ['captcha', 'captchaValidate', 'NECaptchaValidate', 'validate'].some(key => Boolean(form.get(key))),
  };
}

/**
 * 验证码恢复时先走一次真实编辑器输入，触发标题校验、富文本事件和易盾行为采集。
 * 这一步只使用页面上下文，不打印标题、正文或任何会话字段。
 */
export async function fillWangyiEditorPage(page, {
  title = '', html = '', text = '',
} = {}) {
  const titleHit = await firstVisible(page, S.titleInput, { timeoutMs: 20_000 });
  if (!titleHit) throw new Error('网易号验证码恢复未找到标题输入框');

  const bodyHit = await firstVisible(page, S.editorBody, { timeoutMs: 20_000 });
  if (!bodyHit) throw new Error('网易号验证码恢复未找到正文编辑区');

  const visibleText = String(text || htmlToPlainText(html)).trim();
  if (!title || !visibleText) throw new Error('网易号验证码恢复缺少可填写的标题或正文');

  // CloakBrowser 的 humanize 会接管 Locator.fill/press：自动清空、逐字输入、停顿和纠错。
  // 这里不再叠加自定义逐字输入、随机延迟或 DOM 注入。
  const preflight = page.waitForResponse(
    response => /\/wemedia\/article\/checkTitle|ir-sdk\.dun\.163\.com\/v4\/j\/up/.test(response.url()),
    { timeout: 8_000 },
  ).catch(() => null);
  await titleHit.locator.fill(title);
  await titleHit.locator.press('Tab').catch(() => {});
  await bodyHit.locator.fill(visibleText);

  const preflightResponse = await preflight;
  const actualText = await bodyHit.locator.innerText().catch(() => '');
  const bodyChars = String(actualText || '').replace(/\s/g, '').length;
  const expectedChars = visibleText.replace(/\s/g, '').length;
  if (expectedChars > 0 && bodyChars <= 0) {
    throw new Error('网易号验证码恢复正文填写后校验为空');
  }

  return {
    titleSelector: titleHit.selector,
    bodySelector: bodyHit.selector,
    title,
    text: visibleText,
    bodyChars,
    preflightStatus: preflightResponse?.status?.() || 0,
  };
}

const WANGYI_SAVE_PATH = '/wemedia/article/status/api/publishV2.do';
const WANGYI_CAPTCHA_GET_PATH = '/api/v3/get';
const WANGYI_CAPTCHA_CHECK_PATH = '/api/v3/check';
let wangyiCaptchaJsonpSequence = 0;
const WANGYI_CAPTCHA_CB_ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
const WANGYI_CAPTCHA_CB_SEED = 'fd6a43ae25f74398b61c03c83be37449';
const WANGYI_CAPTCHA_CB_SBOX = 'a7be3f3933fa8c5fcf86c4b6908b569ba1e26c1a6d7cfbf60ae4b00e074a194dac4b73e7f898541159a39d08183b76eedee3ed341e6685d2357440158394b1ff03a9004cbbb5ca7dcb7f41489a16e03dcc9c71eb3c9796685b1d01b4d56193a6e1f1a2470445c191ae49c5d82765dc82c350f263387a24a502fcbf442e2dddaad0e936d9ea22b89275307b42518fbc3a626ba806d4ecd6d725f50cc8c72fefa4551ccd6fc9b2b7ab954f815c7264c6e51f4eaf99885a79892b1b60a0b3526e57ba5d178d370958847eb9fd28f9ce0bc023f4148a2adfe632126769057043d3bd8eda0df7872629f3809ef05310e83113216afe202c460fc23e789f77d1addb5e';
const WANGYI_CAPTCHA_CB_BASE64_ALPHABET = 'MB.CfHUzEeJpsuGkgNwhqiSaI4Fd9L6jYKZAxn1/Vml0c5rbXRP+8tD3QTO2vWyo';
const WANGYI_CAPTCHA_CB_PADDING = '7';

function wangyiCaptchaToByte(value) {
  let byte = Number(value);
  while (byte < -128) byte += 256;
  while (byte > 127) byte -= 256;
  return byte;
}

function wangyiCaptchaXor(left, right) {
  return wangyiCaptchaToByte(wangyiCaptchaToByte(left) ^ wangyiCaptchaToByte(right));
}

function wangyiCaptchaXors(values, key) {
  return values.map((value, index) => wangyiCaptchaXor(value, key[index % key.length]));
}

function wangyiCaptchaShifts(values, key) {
  return values.map((value, index) => wangyiCaptchaToByte(
    wangyiCaptchaToByte(value) + wangyiCaptchaToByte(key[index % key.length]),
  ));
}

function wangyiCaptchaStringToBytes(value) {
  return Array.from(String(value || '')).map(character => wangyiCaptchaToByte(character.charCodeAt(0)));
}

function wangyiCaptchaHexToBytes(hex) {
  const bytes = [];
  for (let index = 0; index < hex.length; index += 2) {
    const value = Number.parseInt(hex.slice(index, index + 2), 16);
    bytes.push(wangyiCaptchaToByte(value));
  }
  return bytes;
}

function wangyiCaptchaIntToBytes(value) {
  return [
    wangyiCaptchaToByte(value >>> 24 & 0xff),
    wangyiCaptchaToByte(value >>> 16 & 0xff),
    wangyiCaptchaToByte(value >>> 8 & 0xff),
    wangyiCaptchaToByte(value & 0xff),
  ];
}

function wangyiCaptchaCrc32(values) {
  const table = [];
  for (let index = 0; index < 256; index += 1) {
    let value = index;
    for (let bit = 0; bit < 8; bit += 1) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    table[index] = value >>> 0;
  }
  let checksum = 0xffffffff;
  for (const value of values) checksum = (checksum >>> 8) ^ table[(checksum ^ value) & 0xff];
  return wangyiCaptchaIntToBytes((0xffffffff ^ (checksum >>> 0)) >>> 0)
    .map(value => (value & 0xff).toString(16).padStart(2, '0'))
    .join('');
}

function wangyiCaptchaRoundTransform(values) {
  let key = 0x76;
  let transformed = values.map(value => wangyiCaptchaXor(value, key++));
  key = 0xda;
  transformed = transformed.map(value => wangyiCaptchaToByte(value + key--));
  transformed = transformed.map(value => wangyiCaptchaToByte(value + 0x96));
  key = 0x5c;
  return transformed.map(value => wangyiCaptchaXor(value, key--));
}

function wangyiCaptchaSubBytes(values, sbox) {
  return values.map(value => sbox[0x10 * (value >>> 4 & 0xf) + (value & 0xf)]);
}

function wangyiCaptchaBase64Encode(values) {
  let encoded = '';
  for (let index = 0; index < values.length; index += 3) {
    const count = Math.min(3, values.length - index);
    const first = values[index] & 0xff;
    const second = count > 1 ? values[index + 1] & 0xff : 0;
    const third = count > 2 ? values[index + 2] & 0xff : 0;
    encoded += WANGYI_CAPTCHA_CB_BASE64_ALPHABET[first >>> 2 & 0x3f];
    encoded += WANGYI_CAPTCHA_CB_BASE64_ALPHABET[(first << 4 & 0x30) + (second >>> 4 & 0xf)];
    encoded += count > 1
      ? WANGYI_CAPTCHA_CB_BASE64_ALPHABET[(second << 2 & 0x3c) + (third >>> 6 & 0x3)]
      : WANGYI_CAPTCHA_CB_PADDING;
    encoded += count > 2
      ? WANGYI_CAPTCHA_CB_BASE64_ALPHABET[third & 0x3f]
      : WANGYI_CAPTCHA_CB_PADDING;
  }
  return encoded;
}

function wangyiCaptchaAes(value, random = Math.random) {
  const sbox = wangyiCaptchaHexToBytes(WANGYI_CAPTCHA_CB_SBOX);
  const seed = wangyiCaptchaStringToBytes(WANGYI_CAPTCHA_CB_SEED);
  const iv = Array.from({ length: 4 }, () => wangyiCaptchaToByte(Math.floor(0x100 * random())));
  const key = Array.from({ length: 64 }, (_, index) => seed[index % seed.length]);
  const mixedKey = wangyiCaptchaXors(key, iv);
  const input = wangyiCaptchaStringToBytes(value);
  const checksum = wangyiCaptchaStringToBytes(wangyiCaptchaCrc32(input));
  const data = input.concat(checksum);
  const padding = data.length % 0x40 <= 0x3c
    ? 0x40 - data.length % 0x40 - 4
    : 0x80 - data.length % 0x40 - 4;
  const padded = data.concat(Array(padding).fill(0), wangyiCaptchaIntToBytes(data.length));
  let previous = mixedKey;
  const output = [...iv];
  for (let offset = 0; offset < padded.length; offset += 0x40) {
    const block = padded.slice(offset, offset + 0x40);
    let encrypted = wangyiCaptchaXors(wangyiCaptchaRoundTransform(block), mixedKey);
    encrypted = wangyiCaptchaShifts(encrypted, previous);
    encrypted = wangyiCaptchaXors(encrypted, previous);
    previous = wangyiCaptchaSubBytes(wangyiCaptchaSubBytes(encrypted, sbox), sbox);
    output.push(...previous);
  }
  return wangyiCaptchaBase64Encode(output);
}

export function generateWangyiCaptchaCb(random = Math.random) {
  const chars = Array.from({ length: 32 }, () => (
    WANGYI_CAPTCHA_CB_ALPHABET[Math.floor(random() * WANGYI_CAPTCHA_CB_ALPHABET.length)]
  ));
  for (const [index, character] of [
    [1, 'v'], [10, 'f'], [12, 'n'], [13, 'v'], [26, '4'], [31, '6'],
  ]) chars[index] = character;
  return wangyiCaptchaAes(chars.join(''), random);
}

export const WANGYI_CAPTCHA_PROBE_TITLE = '本地验证码检测测试文';
export const WANGYI_CAPTCHA_PROBE_TEXT = '这是十个字检测文本啊';

function pathOnly(rawUrl) {
  try {
    return new URL(rawUrl).pathname;
  } catch {
    return String(rawUrl || '').split('?')[0];
  }
}

function isWangyiCaptchaApiUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    return (url.hostname === 'c.dun.163.com' || url.hostname.endsWith('.dun.163.com'))
      && [WANGYI_CAPTCHA_GET_PATH, WANGYI_CAPTCHA_CHECK_PATH].includes(url.pathname);
  } catch {
    return false;
  }
}

function parseJsonOrJsonp(text) {
  const source = String(text || '').trim();
  if (!source) return null;
  try {
    return JSON.parse(source);
  } catch {
    const open = source.indexOf('(');
    const close = source.lastIndexOf(')');
    if (open < 0 || close <= open) return null;
    try {
      return JSON.parse(source.slice(open + 1, close));
    } catch {
      return null;
    }
  }
}

function extractWangyiCaptchaChallenge(payload) {
  const data = payload?.data || {};
  const question = String(data.front || data.question || '').trim();
  if (!question) return null;
  return {
    question,
    type: data.type == null ? null : Number(data.type),
    waitTime: data.waitTime == null ? null : Number(data.waitTime),
    zoneId: String(data.zoneId || ''),
    backgroundCount: Array.isArray(data.bg) ? data.bg.length : 0,
    backgroundUrls: Array.isArray(data.bg) ? data.bg.map(value => String(value || '')).filter(Boolean) : [],
    token: String(data.token || ''),
  };
}

function publicWangyiCaptchaChallenge(challenge) {
  if (!challenge) return null;
  const {
    question, type, waitTime, zoneId, backgroundCount,
  } = challenge;
  return { question, type, waitTime, zoneId, backgroundCount };
}

function summarizeWangyiResponse({ status, ok, payload }) {
  const code = payload?.code == null ? null : Number(payload.code);
  const message = String(payload?.msg || payload?.message || '').slice(0, 160);
  return { status, ok: Boolean(ok), code, message };
}

export function classifyWangyiSaveResponse({ status, ok, payload }) {
  const data = payload?.data;
  const code = Number(payload?.code);
  const message = String(payload?.msg || payload?.message || '');
  if (
    code === 1001
    || data?.captchaRequired === true
    || data?.needCaptcha === true
    || /图形验证码|验证码验证|captcha/i.test(message)
  ) return 'captcha';
  if (!ok || status < 200 || status >= 300) return 'failed';
  if (payload?.code != null && code !== 1) return 'failed';
  return 'success';
}

export function parseWangyiCaptchaChallenge(text) {
  return publicWangyiCaptchaChallenge(extractWangyiCaptchaChallenge(parseJsonOrJsonp(text)));
}

/**
 * 依据当前页面发出的 /api/v3/get 会话参数构造易盾 /api/v3/check JSONP 请求。
 * TTOCR 返回的是 check 接口的 data 字段，最终 validate 必须以易盾返回值为准。
 */
export function buildWangyiCaptchaCheckUrl({ session, solvedData, callback = '' } = {}) {
  const query = session?.request?.query || {};
  const challenge = session?.challenge || {};
  const params = new URLSearchParams();
  const values = {
    referer: query.referer || WANGYI_EDITOR_URL,
    zoneId: query.zoneId || challenge.zoneId || 'CN31',
    dt: query.dt || '',
    id: query.id || '',
    token: challenge.token || query.token || '',
    data: solvedData || '',
    width: query.width || '280',
    type: challenge.type ?? query.type ?? '',
    version: query.version || '',
    // 易盾 2.28.5 的 get/check 每次都会独立生成 cb，check 不复用 get 的会话参数。
    cb: generateWangyiCaptchaCb(),
    user: query.user || '',
    extraData: query.extraData || '',
    bf: query.bf || '0',
    runEnv: query.runEnv || '10',
    sdkVersion: query.sdkVersion || '',
    loadVersion: query.loadVersion || '',
    iv: query.iv || '',
    // 易盾 SDK 使用 __JSONP_<随机串>_<序号> 形式的回调名；自定义前缀会被接口判定为参数错误。
    callback: callback || `__JSONP_${Math.random().toString(36).slice(2, 10)}_${++wangyiCaptchaJsonpSequence}`,
  };
  for (const [name, value] of Object.entries(values)) params.set(name, String(value));
  return `https://c.dun.163.com${WANGYI_CAPTCHA_CHECK_PATH}?${params.toString()}`;
}

async function waitPage(page, timeoutMs) {
  if (timeoutMs <= 0) return;
  if (typeof page.waitForTimeout === 'function') {
    await page.waitForTimeout(timeoutMs);
    return;
  }
  await new Promise(resolve => setTimeout(resolve, timeoutMs));
}

function compactBox(box) {
  if (!box) return null;
  return {
    x: Number(box.x),
    y: Number(box.y),
    width: Number(box.width),
    height: Number(box.height),
  };
}

async function readElementBox(locator) {
  try {
    return compactBox(await locator.boundingBox());
  } catch {
    return null;
  }
}

async function readImageSize(locator) {
  try {
    if (typeof locator.evaluate !== 'function') return null;
    return await locator.evaluate(element => ({
      naturalWidth: Number(element.naturalWidth || 0),
      naturalHeight: Number(element.naturalHeight || 0),
      complete: Boolean(element.complete),
    }));
  } catch {
    return null;
  }
}

/** 轮询 YiDun 容器和背景图，返回相对当前视口的实际显示位置与大小。 */
export async function waitForWangyiCaptchaElement(page, {
  timeoutMs = 30_000,
  pollMs = 250,
} = {}) {
  const root = page.locator(S.captchaRoot).first();
  const background = page.locator(S.captchaBackground).first();
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const remaining = deadline - Date.now();
    try {
      if (typeof root.waitFor === 'function') {
        await root.waitFor({ state: 'visible', timeout: Math.min(pollMs, remaining) });
      }
    } catch {
      // 轮询窗口内尚未显示，继续观察。
    }

    const rootVisible = await root.isVisible().catch(() => false);
    const backgroundVisible = await background.isVisible().catch(() => false);
    const backgroundBox = backgroundVisible ? await readElementBox(background) : null;
    if (rootVisible && backgroundVisible && backgroundBox?.width > 0 && backgroundBox?.height > 0) {
      return {
        rootSelector: S.captchaRoot,
        backgroundSelector: S.captchaBackground,
        rootBox: await readElementBox(root),
        backgroundBox,
        imageSize: await readImageSize(background),
      };
    }
    await waitPage(page, Math.min(pollMs, Math.max(0, deadline - Date.now())));
  }
  return null;
}

async function clickWangyiCaptchaRefresh(page, { timeoutMs = 30_000 } = {}) {
  const root = page.locator(S.captchaRoot).first();
  try { await root.scrollIntoViewIfNeeded?.(); } catch { /* 页面已在可见区域 */ }
  await waitPage(page, 250);
  const visible = await firstVisible(page, S.captchaRefresh, { timeoutMs });
  if (visible) {
    await visible.locator.click();
    return { clicked: true, forced: false, selector: visible.selector };
  }
  for (const selector of S.captchaRefresh) {
    const refresh = page.locator(selector).first();
    const count = typeof refresh.count === 'function' ? await refresh.count().catch(() => 0) : 0;
    if (count > 0) {
      await refresh.click({ force: true });
      return { clicked: true, forced: true, selector };
    }
  }
  throw new Error(`验证码刷新按钮未出现: ${S.captchaRefresh.join(', ')}`);
}

export function createWangyiCaptchaMonitor(page) {
  const saveRequests = [];
  const saveRequestDetails = [];
  const saveResponses = [];
  const captchaRequests = [];
  const captchaResponses = [];
  const captchaRequestDetails = [];
  const captchaSessions = [];
  const pending = new Set();

  const onRequest = request => {
    const url = request.url();
    const path = pathOnly(url);
    if (path === WANGYI_SAVE_PATH) {
      let operation = '';
      try {
        const postData = typeof request.postData === 'function' ? request.postData() : request.postData;
        operation = new URLSearchParams(postData || '').get('operation') || '';
      } catch {
        operation = '';
      }
      const postData = typeof request.postData === 'function' ? request.postData() : request.postData;
      saveRequests.push({ method: request.method(), path, operation });
      saveRequestDetails.push({
        method: request.method(),
        path,
        operation,
        body: typeof postData === 'string' ? postData : '',
      });
    } else if (isWangyiCaptchaApiUrl(url)) {
      captchaRequests.push({ method: request.method(), path });
      try {
        const parsed = new URL(url);
        captchaRequestDetails.push({
          method: request.method(),
          path,
          url,
          query: Object.fromEntries(parsed.searchParams.entries()),
        });
      } catch {
        // 仅保留可解析的请求详情，日志仍使用上面的脱敏摘要。
      }
    }
  };

  const onResponse = response => {
    const url = response.url();
    const path = pathOnly(url);
    const isSave = path === WANGYI_SAVE_PATH;
    const isCaptcha = isWangyiCaptchaApiUrl(url);
    if (!isSave && !isCaptcha) return;

    const task = (async () => {
      const rawText = await response.text().catch(() => '');
      const payload = parseJsonOrJsonp(rawText);
      const status = response.status();
      const ok = response.ok();
      if (isSave) {
        const record = {
          path,
          ...summarizeWangyiResponse({ status, ok, payload }),
          classification: classifyWangyiSaveResponse({ status, ok, payload }),
        };
        // 保存响应正文只在内存中供恢复流程继续使用，snapshot/log 不序列化凭证字段。
        Object.defineProperty(record, 'payload', { value: payload, enumerable: false });
        saveResponses.push(record);
      } else {
        const record = {
          path,
          ...summarizeWangyiResponse({ status, ok, payload }),
        };
        const requestDetail = [...captchaRequestDetails]
          .reverse()
          .find(item => item.url === url)
          || [...captchaRequestDetails].reverse().find(item => item.path === path);
        if (path === WANGYI_CAPTCHA_GET_PATH) {
          const challenge = extractWangyiCaptchaChallenge(payload);
          record.challenge = publicWangyiCaptchaChallenge(challenge);
          if (challenge) {
            captchaSessions.push({
              request: requestDetail || null,
              response: record,
              payload,
              challenge,
            });
          }
        }
        captchaResponses.push(record);
      }
    })();
    pending.add(task);
    task.then(() => pending.delete(task), () => pending.delete(task));
  };

  page.on('request', onRequest);
  page.on('response', onResponse);

  return {
    saveRequests,
    saveResponses,
    captchaRequests,
    captchaResponses,
    async flush() {
      if (pending.size) await Promise.allSettled([...pending]);
    },
    async waitForSaveResponse(timeoutMs = 15_000) {
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        await this.flush();
        if (saveResponses.length) return saveResponses[0];
        await waitPage(page, Math.min(100, Math.max(0, deadline - Date.now())));
      }
      await this.flush();
      return saveResponses[0] || null;
    },
    async waitForSaveResponseAfter(minIndex = 0, timeoutMs = 15_000) {
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        await this.flush();
        if (saveResponses.length > minIndex) return saveResponses[saveResponses.length - 1];
        await waitPage(page, Math.min(100, Math.max(0, deadline - Date.now())));
      }
      await this.flush();
      return saveResponses.length > minIndex ? saveResponses[saveResponses.length - 1] : null;
    },
    latestSaveResponse() {
      return saveResponses[saveResponses.length - 1] || null;
    },
    latestSaveRequest() {
      return saveRequestDetails[saveRequestDetails.length - 1] || null;
    },
    async waitForCaptchaQuestion(minIndex = 0, timeoutMs = 8_000) {
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        await this.flush();
        const result = captchaResponses
          .slice(minIndex)
          .find(item => item.path === WANGYI_CAPTCHA_GET_PATH && item.challenge);
        if (result) return result;
        await waitPage(page, Math.min(100, Math.max(0, deadline - Date.now())));
      }
      await this.flush();
      return captchaResponses
        .slice(minIndex)
        .find(item => item.path === WANGYI_CAPTCHA_GET_PATH && item.challenge) || null;
    },
    latestCaptchaQuestion() {
      return [...captchaResponses]
        .reverse()
        .find(item => item.path === WANGYI_CAPTCHA_GET_PATH && item.challenge) || null;
    },
    latestCaptchaSession() {
      return [...captchaSessions].reverse()[0] || null;
    },
    async waitForCaptchaSession(minIndex = 0, timeoutMs = 8_000) {
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        await this.flush();
        if (captchaSessions.length > minIndex) return captchaSessions[captchaSessions.length - 1];
        await waitPage(page, Math.min(100, Math.max(0, deadline - Date.now())));
      }
      await this.flush();
      return captchaSessions.length > minIndex ? captchaSessions[captchaSessions.length - 1] : null;
    },
    captchaSessionCount() {
      return captchaSessions.length;
    },
    snapshot() {
      return {
        saveRequests: [...saveRequests],
        saveResponses: [...saveResponses],
        captchaRequests: [...captchaRequests],
        captchaResponses: [...captchaResponses],
      };
    },
    dispose() {
      page.off?.('request', onRequest);
      page.off?.('response', onResponse);
    },
  };
}

function wangyiCaptchaProviderConfig() {
  if (config.captcha?.provider !== 'ttocr') return null;
  return config.captcha.ttOcr || {};
}

async function readWangyiPageCaptchaState(page) {
  try {
    return await page.evaluate(() => {
      const nodes = [];
      const captchaNode = document.querySelector('#captcha');
      if (captchaNode) nodes.push(captchaNode);
      nodes.push(...document.querySelectorAll('*'));
      const seen = new Set();
      for (const node of nodes) {
        const fiberKey = Object.keys(node)
          .find(name => name.startsWith('__reactFiber$') || name.startsWith('__reactInternalInstance$'));
        let fiber = fiberKey ? node[fiberKey] : null;
        while (fiber) {
          const instance = fiber.stateNode;
          if (
            instance
            && !seen.has(instance)
            && instance.state
            && Object.prototype.hasOwnProperty.call(instance.state, 'NECaptchaValidate')
          ) {
            seen.add(instance);
            return {
              found: true,
              validate: String(instance.state.NECaptchaValidate || ''),
              showCaptcha: Boolean(instance.state.showCaptcha),
            };
          }
          if (instance && typeof instance === 'object') seen.add(instance);
          fiber = fiber.return;
        }
      }
      return { found: false, validate: '', showCaptcha: false };
    });
  } catch {
    return { found: false, validate: '', showCaptcha: false };
  }
}

async function readWangyiPagePublishFields(page) {
  try {
    return await page.evaluate(() => {
      const nodes = [...document.querySelectorAll('*')];
      const seen = new Set();
      for (const node of nodes) {
        const fiberKey = Object.keys(node)
          .find(name => name.startsWith('__reactFiber$') || name.startsWith('__reactInternalInstance$'));
        let fiber = fiberKey ? node[fiberKey] : null;
        while (fiber) {
          const instance = fiber.stateNode;
          if (
            instance
            && !seen.has(instance)
            && typeof instance.handleSubmit === 'function'
            && instance.state
          ) {
            return {
              found: true,
              ursToken: String(instance.state.ursToken || ''),
              sign: String(instance.state.sign || ''),
              timestamp: String(instance.state.timestamp || ''),
              NECaptchaValidate: String(
                instance.state.NECaptchaValidate
                  || instance.props?.values?.NECaptchaValidate
                  || '',
              ),
              propsCaptchaValidate: String(instance.props?.values?.NECaptchaValidate || ''),
            };
          }
          if (instance && typeof instance === 'object') seen.add(instance);
          fiber = fiber.return;
        }
      }
      return { found: false, ursToken: '', sign: '', timestamp: '' };
    });
  } catch {
    return { found: false, ursToken: '', sign: '', timestamp: '' };
  }
}

async function readWangyiPageUserAgent(page) {
  try {
    return String(await page.evaluate(() => navigator.userAgent) || '').trim();
  } catch {
    return '';
  }
}

async function waitForWangyiPageCaptchaSuccess(page, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const state = await readWangyiPageCaptchaState(page);
    if (state.found && state.validate) return state;
    await waitPage(page, Math.min(100, Math.max(0, deadline - Date.now())));
  }
  return await readWangyiPageCaptchaState(page);
}

async function applyWangyiPageCaptchaValidate(page, validate) {
  return await page.evaluate(({ token }) => {
    const nodes = [];
    const captchaNode = document.querySelector('#captcha');
    if (captchaNode) nodes.push(captchaNode);
    nodes.push(...document.querySelectorAll('*'));
    const seen = new Set();
    for (const node of nodes) {
      const fiberKey = Object.keys(node)
        .find(name => name.startsWith('__reactFiber$') || name.startsWith('__reactInternalInstance$'));
      let fiber = fiberKey ? node[fiberKey] : null;
      while (fiber) {
        const instance = fiber.stateNode;
        if (
          instance
          && !seen.has(instance)
          && typeof instance.captchaDone === 'function'
          && instance.state
          && Object.prototype.hasOwnProperty.call(instance.state, 'NECaptchaValidate')
        ) {
          // captchaDone 就是编辑页易盾组件 onVerify 的页面回调；交给它更新页面状态，
          // 后续 handleSubmit 会读取新的 NECaptchaValidate 并生成全新的保存请求。
          instance.captchaDone({ validate: token });
          return { found: true, method: 'captchaDone' };
        }
        const done = fiber.memoizedProps?.done || fiber.pendingProps?.done;
        if (
          instance
          && !seen.has(instance)
          && typeof done === 'function'
          && instance.state
          && Object.prototype.hasOwnProperty.call(instance.state, 'NECaptchaValidate')
        ) {
          done({ validate: token });
          return { found: true, method: 'done' };
        }
        if (instance && typeof instance === 'object') seen.add(instance);
        fiber = fiber.return;
      }
    }
    return { found: false, method: '' };
  }, { token: String(validate || '') });
}

async function triggerWangyiPageSave(page, editorState, timeoutMs = 30_000, operation = 'saveDraft') {
  const responsePromise = page.waitForResponse(
    response => pathOnly(response.url()) === WANGYI_SAVE_PATH,
    { timeout: timeoutMs },
  );
  let invocation;
  try {
    invocation = await page.evaluate(async ({ title, text, operation: submitOperation }) => {
      const nodes = [...document.querySelectorAll('*')];
      const seen = new Set();
      let fiberCount = 0;
      let handleSubmitCount = 0;
      for (const node of nodes) {
        const fiberKey = Object.keys(node)
          .find(name => name.startsWith('__reactFiber$') || name.startsWith('__reactInternalInstance$'));
        let fiber = fiberKey ? node[fiberKey] : null;
        while (fiber) {
          fiberCount += 1;
          const instance = fiber.stateNode;
          if (
            instance
            && !seen.has(instance)
            && typeof instance.handleSubmit === 'function'
          ) {
            handleSubmitCount += 1;
            const values = { ...(instance.props?.values || {}) };
            if (title && !values.title) values.title = title;
            if (text && !values.content) values.content = text;
            await instance.handleSubmit(values, submitOperation);
            return { found: true };
          }
          if (instance && typeof instance === 'object') seen.add(instance);
          fiber = fiber.return;
        }
      }
      return {
        found: false,
        diagnostics: {
          nodeCount: nodes.length,
          fiberCount,
          handleSubmitCount,
          buttons: [...document.querySelectorAll('button')]
            .map(button => ({
              text: String(button.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 80),
              className: String(button.className || '').slice(0, 120),
              disabled: Boolean(button.disabled),
            }))
            .filter(item => item.text || item.className)
            .slice(0, 30),
        },
      };
    }, {
      title: String(editorState?.title || ''),
      text: String(editorState?.text || ''),
      operation: String(operation || 'saveDraft'),
    });
  } catch (error) {
    await responsePromise.catch(() => null);
    const wrapped = new Error(`网易号页面保存触发失败: ${error.message || error}`);
    wrapped.code = 'WANGYI_PAGE_SAVE_TRIGGER_FAILED';
    throw wrapped;
  }
  if (!invocation?.found) {
    await responsePromise.catch(() => null);
    const diagnostics = invocation?.diagnostics ? `: ${JSON.stringify(invocation.diagnostics)}` : '';
    const error = new Error(`网易号编辑页未找到保存实例${diagnostics}`);
    error.code = 'WANGYI_PAGE_SAVE_TRIGGER_FAILED';
    throw error;
  }

  const response = await responsePromise;
  const rawText = await response.text().catch(() => '');
  const payload = parseJsonOrJsonp(rawText);
  return {
    status: response.status(),
    ok: response.ok(),
    payload,
    editorState,
  };
}

async function submitWangyiCaptchaData(page, session, solvedData, timeoutMs = 30_000) {
  const validate = String(solvedData || '').trim();
  if (!validate) {
    return {
      status: 0,
      ok: false,
      payload: null,
      passed: false,
      validate: '',
    };
  }

  const captchaElement = await waitForWangyiCaptchaElement(page, { timeoutMs });
  if (!captchaElement) throw new Error('网易号验证码背景图未就绪');

  // TTOCR /api/recognize2 返回的 data 本身就是可交给易盾组件 onVerify 的
  // validate 串，不是 /api/v3/check 的 d/m/p/ext JSON。直接交给编辑页回调，
  // 让组件更新 NECaptchaValidate、隐藏验证码并由页面重新生成保存表单。
  const applied = await applyWangyiPageCaptchaValidate(page, validate);
  if (!applied?.found) {
    const error = new Error('网易号验证码页面回调未找到');
    error.code = 'WANGYI_CAPTCHA_CALLBACK_NOT_FOUND';
    throw error;
  }
  const state = await waitForWangyiPageCaptchaSuccess(page, Math.min(timeoutMs, 10_000));
  const pageValidate = String(state?.validate || '');
  return {
    status: 200,
    ok: true,
    payload: { source: 'ttocr-data-as-validate', data: { result: pageValidate === validate, validate: pageValidate } },
    passed: pageValidate === validate,
    validate: pageValidate,
    pageState: {
      found: Boolean(state?.found),
      hasValidate: Boolean(state?.validate),
      showCaptcha: Boolean(state?.showCaptcha),
      rootBox: captchaElement.rootBox,
      backgroundBox: captchaElement.backgroundBox,
      imageSize: captchaElement.imageSize,
      callback: applied.method,
    },
  };
}

export async function solveWangyiCaptchaWithTtOcr(page, monitor, {
  timeoutMs = 30_000,
  maxAttempts = 3,
  minSessionIndex = 0,
  allowLatestFallback = false,
  provider = wangyiCaptchaProviderConfig(),
  recognize = recognizeYidunWithTtOcr,
  submit = submitWangyiCaptchaData,
} = {}) {
  if (!provider) return null;

  let session = minSessionIndex < monitor.captchaSessionCount()
    ? monitor.latestCaptchaSession()
    : null;
  let nextSessionIndex = minSessionIndex;
  let lastReason = 'unknown';
  for (let attempt = 1; attempt <= Math.min(3, Math.max(1, Number(maxAttempts) || 3)); attempt += 1) {
    if (!session) {
      session = await monitor.waitForCaptchaSession(nextSessionIndex, Math.min(timeoutMs, 10_000));
      if (!session && allowLatestFallback && attempt === 1) session = monitor.latestCaptchaSession();
    }
    if (!session?.challenge?.token || !session?.request?.query?.id) {
      lastReason = 'captcha-session-incomplete';
    } else {
      const recognition = await recognize({
        appKey: provider.appKey,
        id: session.request.query.id,
        referer: session.request.query.referer,
        itemId: provider.itemId,
        proxy: provider.proxy || getCloakBrowserProxy(),
        devKey: provider.devKey,
        // 让 TTOCR 生成 data 时使用和当前 CloakBrowser 相同的 UA；易盾校验会把
        // 识别侧的设备参数与当前页面会话绑定，配置显式 UA 时仍以配置为准。
        userAgent: provider.userAgent || await readWangyiPageUserAgent(page),
        type: session.challenge.type,
        apiUrl: provider.apiUrl,
        timeoutMs: provider.timeoutMs || timeoutMs,
      });
      const checked = await submit(page, session, recognition.validate || recognition.data, timeoutMs);
      if (checked.passed) {
        return {
          provider: 'ttocr',
          attempt,
          validate: checked.validate,
          providerStatus: recognition.providerStatus,
          pageState: checked.pageState || null,
          durationMs: recognition.durationMs,
          providerTimeMs: recognition.providerTimeMs,
        };
      }
      lastReason = checked?.checkSummary
        ? `yidun-validation-failed:${JSON.stringify(checked.checkSummary)}`
        : 'yidun-validation-failed';
    }

    if (attempt >= Math.min(3, Math.max(1, Number(maxAttempts) || 3))) break;
    nextSessionIndex = monitor.captchaSessionCount();
    await clickWangyiCaptchaRefresh(page, { timeoutMs });
    session = await monitor.waitForCaptchaSession(nextSessionIndex, Math.min(timeoutMs, 10_000));
  }

  const error = new Error(`TT OCR 验证未通过: ${lastReason}`);
  error.code = 'WANGYI_CAPTCHA_PROVIDER_FAILED';
  throw error;
}

function saveResponseRecordToResult(record) {
  if (!record) return null;
  return {
    status: Number(record.status) || 0,
    ok: Boolean(record.ok),
    payload: record.payload || {
      code: record.code,
      msg: record.message,
    },
  };
}

async function waitForInitialWangyiSaveResponse(monitor, minIndex, timeoutMs) {
  if (typeof monitor.waitForSaveResponseAfter === 'function') {
    return await monitor.waitForSaveResponseAfter(minIndex, timeoutMs);
  }
  if (typeof monitor.waitForSaveResponse === 'function') {
    return await monitor.waitForSaveResponse(timeoutMs);
  }
  return monitor.latestSaveResponse?.() || monitor.saveResponses?.[monitor.saveResponses.length - 1] || null;
}

export async function recoverWangyiRequestWithTtOcr(page, monitor, request, requestBody, editorState, {
  provider = wangyiCaptchaProviderConfig(),
  recognize = recognizeYidunWithTtOcr,
  submit = submitWangyiCaptchaData,
  triggerSave = triggerWangyiPageSave,
  initialResponse = null,
  initialSaveIndex = 0,
  initialCaptchaSessionIndex = 0,
  timeoutMs = config.captcha?.ttOcr?.timeoutMs || 30_000,
} = {}) {
  // 第一次保存由编辑器页面自身明确触发；传入响应时避免重复等待同一请求。
  let response = initialResponse
    || await waitForInitialWangyiSaveResponse(monitor, initialSaveIndex, timeoutMs);
  if (!response) {
    const error = new Error('网易号编辑页保存响应超时');
    error.code = 'WANGYI_PAGE_SAVE_TIMEOUT';
    throw error;
  }

  for (let attempt = 1; attempt <= 3; attempt += 1) {
    const classification = classifyWangyiSaveResponse(response);
    if (classification !== 'captcha') return saveResponseRecordToResult(response);

    const captchaSessionIndex = attempt === 1
      ? initialCaptchaSessionIndex
      : monitor.captchaSessionCount();
    const solved = await solveWangyiCaptchaWithTtOcr(page, monitor, {
      timeoutMs,
      maxAttempts: 3,
      minSessionIndex: captchaSessionIndex,
      allowLatestFallback: attempt === 1,
      provider,
      recognize,
      submit,
    });
    if (!solved?.validate) {
      const error = new Error('网易号验证码页面状态未更新');
      error.code = 'WANGYI_CAPTCHA_STATE_NOT_UPDATED';
      throw error;
    }

    // 校验成功后由编辑页实例再次执行 saveDraft，刷新 Cookie 和页面会话；
    // sign/timestamp 直接从同一编辑页实例的状态读取，正式文章仍由 API 客户端提交。
    response = await triggerSave(page, editorState, timeoutMs);
    if (!response) {
      const error = new Error('网易号验证码处理后的页面保存没有响应');
      error.code = 'WANGYI_PAGE_SAVE_TIMEOUT';
      throw error;
    }
  }

  throw new Error('网易号验证码恢复重试次数已用尽');
}

/**
 * 仅探测保存时是否触发验证码：填入 10 字测试内容，不点击发布。
 * 成功时返回保存响应并依靠 storageState 持久化最新登录态；验证码时返回题目、元素位置和显示尺寸。
 */
export async function probeWangyiCaptchaForSave(accountId, {
  maxAttempts = 3,
  saveTimeoutMs = 30_000,
  captchaTimeoutMs = 30_000,
  headless = true,
  browserEngine = 'cloakbrowser',
} = {}) {
  const attempts = Math.min(3, Math.max(1, Number(maxAttempts) || 3));
  let lastReason = 'unknown';

  return await withHeadlessAccountContext(accountId, async page => {
    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      if (attempt === 1) {
        await page.goto(WANGYI_EDITOR_URL, { waitUntil: 'domcontentloaded', timeout: 45_000 });
      } else {
        await page.reload({ waitUntil: 'domcontentloaded', timeout: 45_000 });
      }

      const monitor = createWangyiCaptchaMonitor(page);
      try {
        const editor = await fillWangyiEditorPage(page, {
          title: WANGYI_CAPTCHA_PROBE_TITLE,
          text: WANGYI_CAPTCHA_PROBE_TEXT,
        });
        const save = await triggerWangyiPageSave(page, editor, saveTimeoutMs);
        if (!save) {
          lastReason = 'save-timeout';
          continue;
        }
        if (save.classification === 'success') {
          await monitor.flush();
          return {
            status: 'saved',
            attempt,
            editor,
            save,
            storageStatePersisted: true,
            events: monitor.snapshot(),
          };
        }
        if (save.classification !== 'captcha') {
          const error = new Error(save.message || '网易号保存请求返回失败');
          error.code = 'WANGYI_SAVE_FAILED';
          throw error;
        }

        const captchaElement = await waitForWangyiCaptchaElement(page, {
          timeoutMs: captchaTimeoutMs,
        });
        if (!captchaElement) {
          lastReason = 'captcha-element-timeout';
          continue;
        }

        const beforeRefresh = monitor.captchaResponses.length;
        const existingChallenge = await monitor.waitForCaptchaQuestion(0, 1_000)
          || monitor.latestCaptchaQuestion();
        let refresh = { clicked: false, forced: false, error: '' };
        try {
          refresh = await clickWangyiCaptchaRefresh(page, { timeoutMs: captchaTimeoutMs });
        } catch (error) {
          refresh.error = String(error.message || error).slice(0, 240);
        }
        const refreshedChallenge = refresh.clicked
          ? await monitor.waitForCaptchaQuestion(beforeRefresh, 8_000)
          : null;
        const challenge = refreshedChallenge || existingChallenge;
        if (!challenge?.challenge) {
          lastReason = 'captcha-question-timeout';
          continue;
        }

        await monitor.flush();
        return {
          status: 'captcha',
          attempt,
          editor,
          save,
          captcha: {
            question: challenge.challenge.question,
            type: challenge.challenge.type,
            waitTime: challenge.challenge.waitTime,
            zoneId: challenge.challenge.zoneId,
            response: {
              path: challenge.path,
              status: challenge.status,
              code: challenge.code,
            },
            refresh,
            element: await waitForWangyiCaptchaElement(page, { timeoutMs: 5_000 }) || captchaElement,
          },
          storageStatePersisted: true,
          events: monitor.snapshot(),
        };
      } catch (error) {
        lastReason = error.message || 'probe-error';
        if (error.code === 'WANGYI_SAVE_FAILED') throw error;
      } finally {
        await monitor.flush();
        monitor.dispose();
      }
    }

    const error = new Error('验证码加载失败');
    error.code = 'WANGYI_CAPTCHA_LOAD_FAILED';
    error.reason = lastReason;
    throw error;
  }, {
    headless,
    persistStorageState: true,
    browserEngine,
  });
}

async function readWangyiPageToken(page) {
  try {
    return await page.evaluate(() => {
      const names = ['ursToken', 'urs_token', 'urs-token'];
      for (const name of names) {
        const value = window.localStorage?.getItem(name);
        if (value) return value;
      }
      const cookieMap = Object.fromEntries(document.cookie.split(';').map(item => {
        const index = item.indexOf('=');
        return index < 0 ? [item.trim(), ''] : [item.slice(0, index).trim(), item.slice(index + 1)];
      }));
      return names.map(name => cookieMap[name]).find(Boolean) || '';
    });
  } catch {
    return '';
  }
}

async function recoverWangyiRequestInHeadlessBrowser(accountId, request) {
  const method = String(request.method || 'GET').toUpperCase();
  const body = browserRequestBody(request.body);
  if (body === null && method !== 'GET') {
    throw new Error('网易号验证码恢复当前仅支持表单请求');
  }
  const form = body === null ? null : parseWangyiRecoveryForm(body);

  return await withHeadlessAccountContext(accountId, async (page, context) => {
    await page.goto(WANGYI_EDITOR_URL, { waitUntil: 'domcontentloaded', timeout: 45_000 });
    const monitor = createWangyiCaptchaMonitor(page);
    const initialSaveIndex = monitor.saveResponses.length;
    const initialCaptchaSessionIndex = monitor.captchaSessionCount();

    let editorState = null;
    let requestBody = body;
    const pageOperation = form?.operation === 'publish' || form?.operation === 'date-publish'
      ? form.operation
      : 'saveDraft';
    let publishProbePhase = 'inactive';
    let publishProbeRouteHits = 0;
    const publishProbeRoute = async route => {
      publishProbeRouteHits += 1;
      if (publishProbePhase === 'first') {
        // 这一请求只用于让编辑页进入真实的“需要验证码”状态；探针内容和探针请求都不送到
        // 网易业务接口，正式文章仍由 API 客户端在验证码恢复后单独提交。
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            code: 100502,
            msg: '需要进行图形验证码验证',
            data: { captchaRequired: true },
          }),
        });
        return;
      }
      if (publishProbePhase === 'blocked') {
        // 验证成功后的第二次页面触发只用于刷新页面状态；拦截其业务请求，避免固定探针真正发布。
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ code: 1, msg: '操作成功', data: 'docId=CAPTCHA_PROBE_BLOCKED' }),
        });
        return;
      }
      await route.continue();
    };
    try {
      if (method !== 'GET') {
        // 页面只填写固定探针，真实文章内容保留在 requestBody 中，后续仍由 API 完成正式发文。
        editorState = await fillWangyiEditorPage(page, {
          title: WANGYI_CAPTCHA_PROBE_TITLE,
          text: WANGYI_CAPTCHA_PROBE_TEXT,
        });
        // 编辑器输入可能刷新页面里的动态 ursToken；优先使用刷新后的值，保留其余原始业务字段。
        const pageToken = await readWangyiPageToken(page);
        if (pageToken) {
          const refreshedForm = new URLSearchParams(body);
          if (refreshedForm.has('ursToken')) refreshedForm.set('ursToken', pageToken);
          requestBody = refreshedForm.toString();
        }
      }

      if (pageOperation === 'publish') {
        publishProbePhase = 'first';
        await page.route(/\/wemedia\/article\/status\/api\/publishV2\.do(?:\?|$)/, publishProbeRoute);
      }
      const initialResponse = method === 'GET'
        ? null
        : await triggerWangyiPageSave(
          page,
          editorState,
          config.captcha?.ttOcr?.timeoutMs || 30_000,
          'saveDraft',
        );

      const result = await recoverWangyiRequestWithTtOcr(
        page,
        monitor,
        { ...request, method },
        requestBody,
        editorState,
        {
          initialResponse,
          initialSaveIndex,
        initialCaptchaSessionIndex,
        triggerSave: async (currentPage, currentEditorState, timeoutMs) => {
          if (pageOperation === 'publish') publishProbePhase = 'blocked';
          return await triggerWangyiPageSave(currentPage, currentEditorState, timeoutMs, 'saveDraft');
        },
      },
      );
      await monitor.flush();
      const storageState = await context.storageState({ indexedDB: true });
      const operation = form?.operation || new URLSearchParams(requestBody || '').get('operation') || '';
      const latestSaveForm = new URLSearchParams(monitor.latestSaveRequest()?.body || '');
      const pagePublishFields = await readWangyiPagePublishFields(page);
      const pageSavePayload = result?.payload || {};
      const recoveryDiagnostics = {
        pageSaveClassification: classifyWangyiSaveResponse({
          status: result?.status,
          ok: result?.ok,
          payload: pageSavePayload,
        }),
        pageSaveCode: pageSavePayload?.code ?? null,
        pageSaveMessage: String(pageSavePayload?.msg || pageSavePayload?.message || '').slice(0, 120),
        saveRequestCount: monitor.saveRequests.length,
        latestSaveOperation: monitor.latestSaveRequest()?.operation || '',
        latestSaveHasUrsToken: Boolean(latestSaveForm.get('ursToken')),
        latestSaveHasSign: Boolean(latestSaveForm.get('sign')),
        latestSaveHasTimestamp: Boolean(latestSaveForm.get('timestamp')),
        latestSaveHasCaptcha: Boolean(latestSaveForm.get('NECaptchaValidate')),
        pagePublishFieldsFound: Boolean(pagePublishFields.found),
        pagePublishHasSign: Boolean(pagePublishFields.sign),
        pagePublishHasTimestamp: Boolean(pagePublishFields.timestamp),
        pagePublishHasCaptcha: Boolean(pagePublishFields.NECaptchaValidate),
        originalPublishForm: summarizeWangyiFormFields(requestBody),
        latestSaveForm: summarizeWangyiFormFields(monitor.latestSaveRequest()?.body || ''),
        publishProbeRouteHits,
      };
      // 正式发布请求只借用本次页面保存后的最新会话，交回 API 客户端重试原始 publish。
      if (operation === 'publish' || operation === 'date-publish') {
        const refreshedRequestBody = mergeWangyiRefreshedForm(
          requestBody,
          monitor.latestSaveRequest()?.body || '',
          pagePublishFields,
        );
        recoveryDiagnostics.refreshedPublishForm = summarizeWangyiFormFields(refreshedRequestBody);
        return { storageState, requestBody: refreshedRequestBody, recoveryDiagnostics };
      }
      return { ...result, storageState };
    } finally {
      await monitor.flush();
      monitor.dispose();
      if (pageOperation === 'publish') await page.unroute(/\/wemedia\/article\/status\/api\/publishV2\.do(?:\?|$)/, publishProbeRoute).catch(() => {});
    }
  }, {
    headless: true,
    persistStorageState: true,
    browserEngine: 'cloakbrowser',
  });
}

export default class WangyiAdapter extends BaseAdapter {
  static id = 'wangyi';
  static name_ = '网易号';
  static homeUrl = S.homeUrl;
  static loginUrl = S.loginUrl;
  static supportsQrLogin = false; // URS 登录框只有邮箱/手机登录，无二维码（2026-07-11 实测）
  static selectors = S;
  static apiOnly = true;
  // 网易登录保留可视化浏览器；登录完成后的检查、发文、状态核验均直接走接口，不启动浏览器。
  static nonLoginBrowserMode = 'none';
  static detectionTimeoutMs = 60 * 1000;

  async loginCheck(page) {
    await page.goto(S.homeUrl, { waitUntil: 'domcontentloaded' });
    await sleep(3000);
    if (S.loginUrlPattern.test(page.url())) return false;
    const probe = await firstVisible(page, S.loggedInProbe, { timeoutMs: 8000 });
    return !!probe;
  }

  /**
   * 网易号首页通过登录会话请求 navinfo；tname 是公开账号名，loginUser 是登录标识。
   * 直接读会话接口比抓页面 DOM 稳定，也避免把导航栏里的其它文字误当成昵称。
   */
  async getAccountProfile(page) {
    try {
      const profile = await page.evaluate(async () => {
        let response;
        let lastError;
        for (let attempt = 1; attempt <= 3; attempt += 1) {
          try {
            response = await fetch('/wemedia/navinfo.do', { credentials: 'include' });
            if (![403, 408, 425, 429].includes(response.status) && response.status < 500) break;
            lastError = new Error(`HTTP ${response.status}`);
            lastError.status = response.status;
          } catch (error) {
            lastError = error;
          }
          if (attempt < 3) await new Promise(resolve => setTimeout(resolve, 250 * (2 ** (attempt - 1))));
        }
        if (!response || lastError && response.status >= 500) throw lastError;
        if (!response.ok) return null;
        const payload = await response.json();
        const data = payload?.data || {};
        const username = String(data.loginUser || data.realUserId || '').trim();
        return {
          profileName: String(data.tname || '').trim(),
          username,
          ...(/^\d{11}$/.test(username) ? { phone: username } : {}),
        };
      });
      if (profile?.profileName || profile?.username) return profile;
    } catch { /* 接口临时失败时降级页面昵称 */ }
    return await super.getAccountProfile(page);
  }

  async apiCheck(accountId) {
    try {
      const client = new WangyiApiClient(accountId);
      return await client.checkLogin();
    } catch (error) {
      if (error instanceof WangyiApiError) {
        return {
          ok: false,
          profile: null,
          ...(error.accountStatus ? { accountStatus: error.accountStatus } : {}),
          error,
        };
      }
      throw error;
    }
  }

  async createApiClient(accountId) {
    const client = new WangyiApiClient(accountId);
    await client.getAccountProfile();
    return client;
  }

  /** 网易号 API 直发：账户、图片、校验、草稿、发布和状态回读全部走接口。 */
  async publish(_page, article, hooks = {}) {
    const coverIssue = checkPlatformCover(Boolean(article.topicImage?.path), this.id, this.name);
    if (coverIssue) {
      const error = new Error(`${coverIssue.message}，系统已停止发布`);
      error.code = coverIssue.code;
      error.status = 400;
      throw error;
    }
    const onStage = hooks.onStage || (() => {});
    const client = new WangyiApiClient(hooks.accountId, undefined, {
      ursTokenProvider: hooks.ursTokenProvider,
      captchaRecovery: async request => {
        await onStage('captcha-recovery', '网易号接口提示验证码，使用 CloakBrowser 填写 10 字探针后刷新登录态');
        return await recoverWangyiRequestInHeadlessBrowser(hooks.accountId, request);
      },
    });

    await onStage('login-check');
    const checked = await client.checkLogin();
    await hooks.onLoginChecked?.(checked.ok, checked.accountStatus);
    if (!checked.ok) {
      if (checked.accountStatus === 'banned') {
        throw new PublishRejectedError('网易号账号已查封，已拦截本次发布');
      }
      throw new NeedLoginError(this.name);
    }

    await onStage('open-editor', '网易号 API 直发');
    await onStage('fill-title');
    await onStage('fill-body');
    let html = article.html;
    const uploadedUrls = [];
    let coverUrl = '';
    if (article.topicImage?.path) {
      const cover = await client.uploadImage(article.topicImage.path, 'image/jpeg');
      coverUrl = cover.url;
      await client.addMaterialPicture(coverUrl);
    }
    for (const image of article.images || []) {
      if (!image?.path) continue;
      const uploaded = await client.uploadImage(image.path, image.contentType || 'application/octet-stream');
      const url = uploaded.url;
      uploadedUrls.push(url);
      await client.addMaterialPicture(url);
    }
    if (uploadedUrls.length) html = replaceWangyiImageSources(html, uploadedUrls);

    const cover = 'custom';
    await onStage('fill-meta');

    if (hooks.mode === 'confirm') {
      if (typeof hooks.createPreview !== 'function') throw new Error('人工确认模式缺少预览链接生成器');
      await hooks.createPreview();
      await onStage('waiting-confirm', '内容已准备，请打开预览链接确认发布');
      await hooks.waitConfirm();
    }

    // 先保存一次服务端草稿，让正式发布复用服务端生成的 articleId。
    let draft;
    try {
      await onStage('save-draft');
      draft = await client.saveDraft({
        title: article.title, html, cover, picUrl: coverUrl,
        onlineState: checked.profile?.onlineState ?? 2,
        original: 0,
        ursToken: article.ursToken,
      });
    } catch (error) {
      if (error instanceof WangyiApiError) {
        if (error.accountStatus === 'banned') await hooks.onLoginChecked?.(false, 'banned');
        throw new PublishRejectedError(error.message);
      }
      throw error;
    }

    await onStage('click-publish');
    try {
      await client.publishArticle({
        articleId: draft.articleId,
        title: article.title,
        html,
        cover,
        picUrl: coverUrl,
        onlineState: checked.profile?.onlineState ?? 2,
        original: 0,
        ursToken: article.ursToken,
      });
    } catch (error) {
      if (error instanceof WangyiApiError) {
        if (error.accountStatus === 'banned') await hooks.onLoginChecked?.(false, 'banned');
        throw new PublishRejectedError(error.message);
      }
      throw error;
    }

    await onStage('detect-published');
    const result = await client.waitForPublication(article.title, {
      articleId: draft.articleId,
      timeoutMs: this.detectionTimeoutMs,
    });
    if (!result) throw new PublishResultUnknownError('网易号已接受提交，列表暂未出现目标文章，系统将继续自动核验');
    if (result.status === 'failed' || result.status === 'draft') throw new PublishRejectedError(result.detail);
    if (result.status === 'unknown') throw new PublishResultUnknownError(result.detail);
    await onStage(result.status === 'published' ? 'published' : result.status, result.url || '');
    return result;
  }
}
