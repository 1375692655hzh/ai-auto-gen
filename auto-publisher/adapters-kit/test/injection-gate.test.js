import test from 'node:test';
import assert from 'node:assert/strict';
import {
  InjectionVerificationError, requireCompleteInjection, verifyInjectedImages,
} from '../src/adapters/richtext.js';

/**
 * 假的 Playwright frame：按队列依次返回 countImages 的结果，
 * 队列耗尽后一直返回最后一个值，用来模拟图片异步转存到齐的过程。
 */
function fakeFrame(counts) {
  const queue = [...counts];
  let calls = 0;
  return {
    get calls() { return calls; },
    async evaluate() {
      calls += 1;
      return queue.length > 1 ? queue.shift() : queue[0];
    },
  };
}

const FAST = { timeoutMs: 200, intervalMs: 10 };

test('图片数一次就齐时直接通过，不额外轮询', async () => {
  const frame = fakeFrame([7]);
  const result = await verifyInjectedImages(frame, '.ql-editor', {
    expectedImages: 7, ...FAST,
  });
  assert.deepEqual(result, { ok: true, count: 7, expected: 7 });
  assert.equal(frame.calls, 1);
});

test('图片多于文档数也算通过（编辑器可能补占位图）', async () => {
  const result = await verifyInjectedImages(fakeFrame([9]), '.ql-editor', {
    expectedImages: 7, ...FAST,
  });
  assert.equal(result.ok, true);
});

test('转存有延迟时轮询等到齐，不误判失败', async () => {
  const frame = fakeFrame([0, 3, 5, 7]);
  const result = await verifyInjectedImages(frame, '.ql-editor', {
    expectedImages: 7, ...FAST,
  });
  assert.equal(result.ok, true);
  assert.equal(result.count, 7);
  assert.ok(frame.calls >= 4, `应轮询多次，实际 ${frame.calls} 次`);
});

test('等满超时仍缺图则判失败并带上实际数量', async () => {
  const result = await verifyInjectedImages(fakeFrame([3]), '.ql-editor', {
    expectedImages: 7, ...FAST,
  });
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'missing-images');
  assert.equal(result.count, 3);
  assert.equal(result.expected, 7);
});

test('文档本身没有图片时直接通过，不查询页面', async () => {
  const frame = fakeFrame([0]);
  const result = await verifyInjectedImages(frame, '.ql-editor', { expectedImages: 0, ...FAST });
  assert.deepEqual(result, { ok: true, count: 0, expected: 0 });
  assert.equal(frame.calls, 0);
});

test('选择器没命中时单独标记，不与缺图混为一谈', async () => {
  const result = await verifyInjectedImages(fakeFrame([-1]), '.gone', {
    expectedImages: 7, ...FAST,
  });
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'selector-missed');
});

test('requireCompleteInjection 缺图时抛错阻断发布', async () => {
  await assert.rejects(
    () => requireCompleteInjection(fakeFrame([3]), '.ql-editor', {
      platform: 'sohu', expectedImages: 7, tempDir: '/tmp/publishing-kit-abc', ...FAST,
    }),
    (error) => {
      assert.ok(error instanceof InjectionVerificationError);
      assert.equal(error.code, 'INJECTION_INCOMPLETE');
      assert.equal(error.actualImages, 3);
      assert.equal(error.expectedImages, 7);
      assert.match(error.message, /编辑器内 3 张，文档共 7 张/);
      assert.match(error.message, /没有提交/);
      assert.match(error.message, /\/tmp\/publishing-kit-abc/);
      return true;
    },
  );
});

test('requireCompleteInjection 在选择器丢失时只警告不阻断', async () => {
  const warnings = [];
  const original = console.warn;
  console.warn = message => warnings.push(String(message));
  try {
    const result = await requireCompleteInjection(fakeFrame([-1]), '.gone', {
      platform: 'zdm', expectedImages: 7, ...FAST,
    });
    assert.equal(result.ok, false);
  } finally {
    console.warn = original;
  }
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /未能定位正文区/);
});

test('requireCompleteInjection 通过时返回校验结果', async () => {
  const result = await requireCompleteInjection(fakeFrame([7]), '.ql-editor', {
    platform: 'sohu', expectedImages: 7, ...FAST,
  });
  assert.equal(result.ok, true);
});

test('没有 tempDir 时错误信息不留空引用', async () => {
  await assert.rejects(
    () => requireCompleteInjection(fakeFrame([1]), '.ql-editor', {
      platform: 'sohu', expectedImages: 5, ...FAST,
    }),
    (error) => {
      assert.doesNotMatch(error.message, /本地副本在\s*$/);
      assert.match(error.message, /没有提交$/);
      return true;
    },
  );
});
