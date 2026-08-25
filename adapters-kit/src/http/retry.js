import { annotateError, writeErrorLog } from '../logging.js';

/**
 * 服务端外部 HTTP 请求的统一重试策略。
 * maxAttempts 包含第一次请求，默认最多执行 3 次。
 */
export const DEFAULT_MAX_ATTEMPTS = 3;

const RETRYABLE_STATUS = new Set([403, 408, 425, 429]);
const RETRYABLE_NETWORK_CODES = new Set([
  'ECONNRESET', 'ECONNREFUSED', 'ECONNABORTED', 'ETIMEDOUT', 'EAI_AGAIN', 'ENETUNREACH',
]);

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

export function isRetryableRequestError(error) {
  const status = Number(error?.status || 0);
  if (RETRYABLE_STATUS.has(status) || status >= 500) return true;
  if (error?.name === 'AbortError' || error?.name === 'TimeoutError') return true;
  if (error instanceof TypeError) return true;
  return RETRYABLE_NETWORK_CODES.has(String(error?.code || '').toUpperCase());
}

export async function withRetry(operation, {
  maxAttempts = DEFAULT_MAX_ATTEMPTS,
  baseDelayMs = 250,
  maxDelayMs = 2000,
  operationName = 'HTTP request',
  shouldRetry = isRetryableRequestError,
} = {}) {
  const attempts = Math.max(1, Math.floor(Number(maxAttempts) || DEFAULT_MAX_ATTEMPTS));
  let lastError;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await operation({ attempt, maxAttempts: attempts });
    } catch (error) {
      lastError = annotateError(error, { location: operationName, attempt, maxAttempts: attempts });
      const retryable = shouldRetry(lastError);
      if (attempt >= attempts || !retryable) {
        await writeErrorLog(lastError, {
          event: 'http_error',
          location: operationName,
          attempt,
          maxAttempts: attempts,
        });
        throw lastError;
      }

      const retryAfterMs = Number(error?.retryAfterMs);
      const backoffMs = Math.min(maxDelayMs, baseDelayMs * (2 ** (attempt - 1)));
      const delayMs = Number.isFinite(retryAfterMs) && retryAfterMs > 0
        ? retryAfterMs
        : backoffMs;
      console.warn(JSON.stringify({
        event: 'http_retry',
        operation: operationName,
        attempt,
        nextAttempt: attempt + 1,
        maxAttempts: attempts,
        delayMs,
        status: lastError?.status || 0,
        error: lastError?.message || String(lastError),
      }));
      await sleep(delayMs);
    }
  }

  throw lastError;
}
