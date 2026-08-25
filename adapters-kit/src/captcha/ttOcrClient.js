const DEFAULT_API_URL = 'http://api.ttocr.com/api/recognize2';
const DEFAULT_TIMEOUT_MS = 60_000;

export class TtOcrError extends Error {
  constructor(message, { code = 'TTOCR_ERROR', status = 0, payload = null } = {}) {
    super(message);
    this.name = 'TtOcrError';
    this.code = code;
    this.status = status;
    this.payload = payload;
  }
}

function asString(value) {
  return value == null ? '' : String(value);
}

function responseData(payload) {
  const candidates = [
    payload?.data,
    payload?.validate,
    payload?.result?.data,
    payload?.result?.validate,
  ];
  return candidates.find(value => typeof value === 'string' && value.trim())?.trim() || '';
}

export function buildTtOcrForm({
  appKey,
  id,
  referer,
  itemId = 500,
  proxy = '',
  devKey = '',
  userAgent = '',
  type = '',
} = {}) {
  const form = new URLSearchParams({
    appkey: asString(appKey),
    id: asString(id),
    referer: asString(referer),
    itemid: asString(itemId),
  });
  if (proxy) form.set('proxy', asString(proxy));
  if (devKey) form.set('devkey', asString(devKey));
  if (userAgent) form.set('ua', asString(userAgent));
  if (type !== '' && type != null) form.set('type', asString(type));
  return form;
}

export function parseTtOcrResponse(payload, { status = 200 } = {}) {
  const providerStatus = Number(payload?.status);
  const data = responseData(payload);
  if (providerStatus !== 1 || !data) {
    throw new TtOcrError(
      asString(payload?.msg || payload?.message || 'TT OCR 识别失败'),
      { code: 'TTOCR_REJECTED', status, payload },
    );
  }
  return {
    data,
    // TT OCR 的 data 已经是易盾最终 validate；保留 data 兼容旧调用方。
    validate: data,
    providerStatus,
    message: asString(payload?.msg || payload?.message),
    providerTimeMs: Number(payload?.time) || 0,
  };
}

export async function recognizeYidunWithTtOcr({
  appKey,
  id,
  referer,
  itemId = 500,
  proxy = '',
  devKey = '',
  userAgent = '',
  type = '',
  apiUrl = DEFAULT_API_URL,
  timeoutMs = DEFAULT_TIMEOUT_MS,
  fetchImpl = globalThis.fetch,
} = {}) {
  if (!asString(appKey).trim()) {
    throw new TtOcrError('TT OCR 缺少 TTOCR_APPKEY', { code: 'TTOCR_NOT_CONFIGURED' });
  }
  if (!asString(id).trim() || !asString(referer).trim()) {
    throw new TtOcrError('TT OCR 缺少易盾 id 或 referer', { code: 'TTOCR_REQUEST_INVALID' });
  }
  if (typeof fetchImpl !== 'function') {
    throw new TtOcrError('当前运行时缺少 fetch', { code: 'TTOCR_FETCH_MISSING' });
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), Math.max(1_000, Number(timeoutMs) || DEFAULT_TIMEOUT_MS));
  const startedAt = Date.now();
  try {
    const response = await fetchImpl(apiUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: buildTtOcrForm({ appKey, id, referer, itemId, proxy, devKey, userAgent, type }),
      signal: controller.signal,
    });
    const text = await response.text();
    let payload;
    try {
      payload = JSON.parse(text);
    } catch {
      throw new TtOcrError('TT OCR 返回了非 JSON 响应', {
        code: 'TTOCR_BAD_RESPONSE',
        status: response.status,
      });
    }
    if (!response.ok) {
      throw new TtOcrError(
        asString(payload?.msg || payload?.message || `TT OCR HTTP ${response.status}`),
        { code: 'TTOCR_HTTP_ERROR', status: response.status, payload },
      );
    }
    return {
      ...parseTtOcrResponse(payload, { status: response.status }),
      durationMs: Date.now() - startedAt,
    };
  } catch (error) {
    if (error instanceof TtOcrError) throw error;
    if (controller.signal.aborted) {
      throw new TtOcrError('TT OCR 请求超时', { code: 'TTOCR_TIMEOUT' });
    }
    throw new TtOcrError(`TT OCR 请求失败: ${error.message || error}`, {
      code: 'TTOCR_NETWORK_ERROR',
    });
  } finally {
    clearTimeout(timeout);
  }
}

export const TT_OCR_DEFAULTS = Object.freeze({
  apiUrl: DEFAULT_API_URL,
  timeoutMs: DEFAULT_TIMEOUT_MS,
  itemId: 500,
});
