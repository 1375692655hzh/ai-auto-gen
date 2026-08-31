/**
 * 平台发文限制元数据。
 * null 表示该平台不设置 发布适配器 的每日发文上限。
 */
export const PLATFORM_DAILY_LIMITS = Object.freeze({
  sohu: 5,
  wangyi: 6,
  toutiao: null,
  zdm: null,
});
export const DAILY_QUOTA_COOLDOWN_MS = 60 * 1000;
const CHINA_TIME_OFFSET_MS = 8 * 60 * 60 * 1000;

export function getPlatformDailyLimit(platform) {
  const limit = PLATFORM_DAILY_LIMITS[String(platform || '').trim()];
  return Number.isInteger(limit) && limit > 0 ? limit : null;
}

/** 返回指定时刻所在北京时间自然日对应的 UTC ISO 区间。 */
export function chinaDayRange(at = new Date()) {
  const instant = at instanceof Date ? at : new Date(at);
  if (Number.isNaN(instant.getTime())) throw new TypeError('无效的额度统计时间');
  const chinaTime = new Date(instant.getTime() + CHINA_TIME_OFFSET_MS);
  const startMs = Date.UTC(
    chinaTime.getUTCFullYear(),
    chinaTime.getUTCMonth(),
    chinaTime.getUTCDate(),
  ) - CHINA_TIME_OFFSET_MS;
  const endMs = startMs + 24 * 60 * 60 * 1000;
  return {
    date: new Date(startMs + CHINA_TIME_OFFSET_MS).toISOString().slice(0, 10),
    start: new Date(startMs).toISOString(),
    end: new Date(endMs).toISOString(),
  };
}

export function buildDailyQuota(platform, used = 0, at = new Date()) {
  const limit = getPlatformDailyLimit(platform);
  const safeUsed = Math.max(0, Number(used) || 0);
  const remaining = limit == null ? null : Math.max(0, limit - safeUsed);
  return {
    ...chinaDayRange(at),
    used: safeUsed,
    limit,
    remaining,
    full: limit != null && remaining === 0,
  };
}

/** 返回北京时间的自然日键，用于区分跨日后的新额度。 */
export function getDailyQuotaDate(value = new Date()) {
  return new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Shanghai',
  }).format(value);
}

export function isDailyQuotaFresh({ date, remaining, checkedAt } = {}, now = new Date()) {
  const checkedAtMs = Date.parse(checkedAt || '');
  return date === getDailyQuotaDate(now)
    && Number.isInteger(remaining)
    && Number.isFinite(checkedAtMs)
    && now.getTime() >= checkedAtMs
    && now.getTime() - checkedAtMs < DAILY_QUOTA_COOLDOWN_MS;
}
