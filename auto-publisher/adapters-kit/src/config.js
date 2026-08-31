function env(name, fallback = '') {
  const value = process.env[name];
  return typeof value === 'string' && value.trim() ? value.trim() : fallback;
}

const ttOcrAppKey = env('TTOCR_APPKEY');

/** 只保留网易验证码恢复链路需要的公开配置结构；不含任何固定凭证。 */
export const config = {
  captcha: {
    provider: env('WANGYI_CAPTCHA_PROVIDER', ttOcrAppKey ? 'ttocr' : 'none').toLowerCase(),
    ttOcr: {
      appKey: ttOcrAppKey,
      apiUrl: env('TTOCR_API_URL', 'http://api.ttocr.com/api/recognize2'),
      itemId: Math.max(1, Number(env('TTOCR_ITEM_ID', '500'))),
      proxy: env('TTOCR_PROXY'),
      devKey: env('TTOCR_DEVKEY'),
      userAgent: env('TTOCR_UA'),
      timeoutMs: Math.max(1000, Number(env('TTOCR_TIMEOUT_MS', '60000'))),
    },
  },
};
