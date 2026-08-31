import test from 'node:test';
import assert from 'node:assert/strict';
import { isRetryableRequestError, withRetry } from '../src/http/retry.js';

test('HTTP 重试默认最多 3 次，包含第一次请求', async () => {
  let attempts = 0;
  await assert.rejects(
    () => withRetry(async () => {
      attempts += 1;
      const error = new Error('临时 403');
      error.status = 403;
      throw error;
    }, { baseDelayMs: 0 }),
    /临时 403/,
  );
  assert.equal(attempts, 3);
});

test('HTTP 重试覆盖网络错误和临时状态码，不重试普通 4xx', async () => {
  assert.equal(isRetryableRequestError(Object.assign(new Error('限流'), { status: 429 })), true);
  assert.equal(isRetryableRequestError(Object.assign(new Error('拒绝'), { status: 403 })), true);
  assert.equal(isRetryableRequestError(new TypeError('网络中断')), true);
  assert.equal(isRetryableRequestError(Object.assign(new Error('参数错误'), { status: 400 })), false);
});

test('HTTP 重试成功后返回最终结果', async () => {
  let attempts = 0;
  const result = await withRetry(async () => {
    attempts += 1;
    if (attempts < 3) throw Object.assign(new Error('网关暂时不可用'), { status: 502 });
    return 'ok';
  }, { baseDelayMs: 0 });
  assert.equal(result, 'ok');
  assert.equal(attempts, 3);
});
