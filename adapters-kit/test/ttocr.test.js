import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildTtOcrForm,
  parseTtOcrResponse,
  recognizeYidunWithTtOcr,
  TtOcrError,
} from '../src/captcha/ttOcrClient.js';

test('TT OCR 易盾请求按官方字段提交并读取 data 结果', async () => {
  let request;
  const result = await recognizeYidunWithTtOcr({
    appKey: 'APPKEY',
    id: 'CAPTCHA_ID',
    referer: 'https://mp.163.com/subscribe_v4/index.html#/article-publish',
    itemId: 500,
    proxy: 'http://proxy.example:8080',
    devKey: 'DEVKEY',
    userAgent: 'UA',
    type: 3,
    apiUrl: 'http://ttocr.test/api/recognize2',
    fetchImpl: async (url, options) => {
      request = { url, options };
      return new Response(JSON.stringify({
        status: 1,
        msg: '识别成功',
        time: 4085,
        data: 'YIDUN_SOLVED_DATA',
      }), { status: 200 });
    },
  });

  assert.equal(request.url, 'http://ttocr.test/api/recognize2');
  assert.equal(request.options.method, 'POST');
  const form = new URLSearchParams(request.options.body);
  assert.equal(form.get('appkey'), 'APPKEY');
  assert.equal(form.get('id'), 'CAPTCHA_ID');
  assert.equal(form.get('referer'), 'https://mp.163.com/subscribe_v4/index.html#/article-publish');
  assert.equal(form.get('itemid'), '500');
  assert.equal(form.get('proxy'), 'http://proxy.example:8080');
  assert.equal(form.get('devkey'), 'DEVKEY');
  assert.equal(form.get('ua'), 'UA');
  assert.equal(form.get('type'), '3');
  assert.equal(result.data, 'YIDUN_SOLVED_DATA');
  assert.equal(result.providerTimeMs, 4085);
});

test('TT OCR 能兼容 validate 字段并对失败响应给出供应商错误码', () => {
  assert.deepEqual(parseTtOcrResponse({ status: 1, validate: 'VALIDATE' }), {
    data: 'VALIDATE',
    validate: 'VALIDATE',
    providerStatus: 1,
    message: '',
    providerTimeMs: 0,
  });
  assert.throws(
    () => parseTtOcrResponse({ status: 0, msg: '点数不足' }),
    error => error instanceof TtOcrError && error.code === 'TTOCR_REJECTED',
  );
});

test('TT OCR 表单构造只包含可选的非空扩展字段', () => {
  const form = buildTtOcrForm({
    appKey: 'APPKEY', id: 'ID', referer: 'REFERER', itemId: 500,
  });
  assert.deepEqual(Object.fromEntries(form.entries()), {
    appkey: 'APPKEY', id: 'ID', referer: 'REFERER', itemid: '500',
  });
});
