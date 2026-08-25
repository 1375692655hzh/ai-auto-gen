import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildWangyiPublishForm,
  getWangyiSessionMetadata,
  mapWangyiContentStatus,
  replaceWangyiImageSources,
  WANGYI_CONTENT_STATUS,
  WANGYI_BANNED_ERROR_CODES,
  WANGYI_FORBIDDEN_ONLINE_STATE,
  WangyiApiClient,
  WangyiApiError,
  classifyWangyiAccountStatus,
  isWangyiCaptchaError,
} from '../src/adapters/wangyi/api.js';
import WangyiAdapter, {
  classifyWangyiSaveResponse,
  fillWangyiEditorPage,
  buildWangyiCaptchaCheckUrl,
  generateWangyiCaptchaCb,
  mergeWangyiRefreshedForm,
  parseWangyiCaptchaChallenge,
  parseWangyiRecoveryForm,
  recoverWangyiRequestWithTtOcr,
  WANGYI_CAPTCHA_PROBE_TEXT,
  WANGYI_CAPTCHA_PROBE_TITLE,
  waitForWangyiCaptchaElement,
} from '../src/adapters/wangyi/index.js';

test('网易号登录之外只走接口，不保留编辑器浏览器自动化入口', () => {
  assert.equal(WangyiAdapter.apiOnly, true);
  assert.equal(WangyiAdapter.nonLoginBrowserMode, 'none');
  assert.equal(Object.hasOwn(WangyiAdapter.prototype, 'openEditor'), false);
  assert.equal(Object.hasOwn(WangyiAdapter.prototype, 'fillTitle'), false);
  assert.equal(Object.hasOwn(WangyiAdapter.prototype, 'fillBody'), false);
  assert.equal(Object.hasOwn(WangyiAdapter.prototype, 'fillMeta'), false);
});

test('网易号验证码恢复只从表单提取标题正文，不把凭证带入编辑器数据', () => {
  const result = parseWangyiRecoveryForm(new URLSearchParams({
    articleId: 'ARTICLE',
    operation: 'saveDraft',
    title: '恢复测试标题',
    content: '<p>第一段</p><p>第二段&nbsp;内容</p>',
    ursToken: 'SECRET_TOKEN',
  }).toString());

  assert.deepEqual(result, {
    articleId: 'ARTICLE',
    operation: 'saveDraft',
    title: '恢复测试标题',
    html: '<p>第一段</p><p>第二段&nbsp;内容</p>',
    text: '第一段 第二段 内容',
  });
  assert.equal(Object.hasOwn(result, 'ursToken'), false);
});

test('网易号验证码恢复固定使用标题和正文各10个汉字的探针', () => {
  assert.equal([...WANGYI_CAPTCHA_PROBE_TITLE].length, 10);
  assert.equal([...WANGYI_CAPTCHA_PROBE_TEXT].length, 10);
  assert.match(WANGYI_CAPTCHA_PROBE_TITLE, /^[\u4e00-\u9fff]{10}$/);
  assert.match(WANGYI_CAPTCHA_PROBE_TEXT, /^[\u4e00-\u9fff]{10}$/);
});

test('网易号验证码恢复会真实填写标题正文并校验正文已进入编辑器', async () => {
  const titleSelector = 'input[placeholder*="请输入标题"]';
  const bodySelector = '.rich-editor-stage [contenteditable="true"]';
  let titleValue = '';
  let bodyText = '';
  const hidden = {
    first() { return this; },
    async isVisible() { return false; },
  };
  const title = {
    first() { return this; },
    async isVisible() { return true; },
    async fill(value) { titleValue = value; },
    async press() {},
  };
  const body = {
    first() { return this; },
    async isVisible() { return true; },
    async fill(value) { bodyText = value; },
    async innerText() { return bodyText; },
  };
  const page = {
    locator(selector) {
      if (selector === titleSelector) return title;
      if (selector === bodySelector) return body;
      return hidden;
    },
    async waitForResponse() {
      return { status: () => 200 };
    },
  };

  const result = await fillWangyiEditorPage(page, {
    title: '恢复测试标题',
    html: '<p>正文内容</p>',
    text: '正文内容',
  });

  assert.equal(titleValue, '恢复测试标题');
  assert.equal(bodyText, '正文内容');
  assert.equal(result.bodyChars, 4);
  assert.equal(result.titleSelector, titleSelector);
  assert.equal(result.bodySelector, bodySelector);
  assert.equal(result.preflightStatus, 200);
});

test('网易号验证码探测能解析 JSONP 题目并区分保存验证码响应', () => {
  const challenge = parseWangyiCaptchaChallenge('__JSONP_test_1__({"data":{"front":"亚握抬","type":3,"waitTime":300,"zoneId":"CN31","bg":["https://image.example/bg.jpg"]},"error":0,"msg":"ok"});');
  assert.deepEqual(challenge, {
    question: '亚握抬',
    type: 3,
    waitTime: 300,
    zoneId: 'CN31',
    backgroundCount: 1,
  });
  assert.equal(classifyWangyiSaveResponse({
    status: 200,
    ok: true,
    payload: { code: 1001, msg: '需要图形验证码验证', data: { captchaRequired: true } },
  }), 'captcha');
  assert.equal(classifyWangyiSaveResponse({
    status: 200,
    ok: true,
    payload: { code: 1, msg: 'ok', data: 'docId=TEST' },
  }), 'success');
});

test('网易号验证码校验请求使用当前会话参数和 TTOCR data', () => {
  const url = new URL(buildWangyiCaptchaCheckUrl({
    session: {
      request: {
        query: {
          referer: 'https://mp.163.com/subscribe_v4/index.html#/article-publish',
          zoneId: 'CN31',
          dt: 'DT',
          id: 'ID',
          width: '280',
          cb: 'CB',
          runEnv: '10',
        },
      },
      challenge: { token: 'CHALLENGE_TOKEN', type: 3 },
    },
    solvedData: 'TTOCR_DATA',
    callback: '__publishing-kit_test_callback',
  }));

  assert.equal(url.pathname, '/api/v3/check');
  assert.equal(url.searchParams.get('id'), 'ID');
  assert.equal(url.searchParams.get('token'), 'CHALLENGE_TOKEN');
  assert.equal(url.searchParams.get('data'), 'TTOCR_DATA');
  assert.equal(url.searchParams.get('type'), '3');
  assert.notEqual(url.searchParams.get('cb'), 'CB');
  assert.equal(url.searchParams.get('cb').length, 92);
  assert.equal(url.searchParams.get('callback'), '__publishing-kit_test_callback');
});

test('网易号验证码 cb 与易盾 2.28.5 官方生成结果一致', () => {
  const sequence = [0.001, 0.123, 0.456, 0.789, 0.999];
  let index = 0;
  const cb = generateWangyiCaptchaCb(() => sequence[index++ % sequence.length]);

  assert.equal(cb, 'Ls/oMsghz2cIU/uo2TVG4DBBRVJP8IA9zXd.V.+okua/q4v9NgTtcK2D+d.fxIHPTr8/ceJDTBHfrAuTMGau4gC8XNv7');
  assert.equal(index, 36);
});

test('网易号验证码校验默认使用易盾兼容的 JSONP 回调名', () => {
  const url = new URL(buildWangyiCaptchaCheckUrl({
    session: {
      request: { query: { id: 'challenge-id' } },
      challenge: { token: 'challenge-token', type: 3 },
    },
    solvedData: 'answer-data',
  }));

  assert.match(url.searchParams.get('callback'), /^__JSONP_[a-z0-9]+_\d+$/);
});

test('网易号验证码恢复只回写编辑页刷新的动态字段，不覆盖真实文章内容', () => {
  const merged = new URLSearchParams(mergeWangyiRefreshedForm(
    new URLSearchParams({
      operation: 'publish',
      articleId: 'ARTICLE',
      title: '真实标题',
      content: '<p>真实正文</p>',
      ursToken: 'OLD_TOKEN',
      sign: 'OLD_SIGN',
    }).toString(),
    new URLSearchParams({
      operation: 'saveDraft',
      title: '本地验证码检测测试文',
      content: '这是十个字检测文本啊',
      ursToken: 'NEW_TOKEN',
      sign: 'NEW_SIGN',
      timestamp: 'NEW_TIMESTAMP',
    }).toString(),
  ));

  assert.equal(merged.get('operation'), 'publish');
  assert.equal(merged.get('articleId'), 'ARTICLE');
  assert.equal(merged.get('title'), '真实标题');
  assert.equal(merged.get('content'), '<p>真实正文</p>');
  assert.equal(merged.get('ursToken'), 'NEW_TOKEN');
  assert.equal(merged.get('sign'), 'NEW_SIGN');
  assert.equal(merged.get('timestamp'), 'NEW_TIMESTAMP');
});

test('网易号验证码恢复可从编辑页状态补齐正式发布签名', () => {
  const merged = new URLSearchParams(mergeWangyiRefreshedForm(
    new URLSearchParams({
      operation: 'publish',
      articleId: 'ARTICLE',
      title: '真实标题',
      content: '<p>真实正文</p>',
    }).toString(),
    new URLSearchParams({ ursToken: 'NEW_TOKEN' }).toString(),
    { sign: 'PAGE_SIGN', timestamp: 'PAGE_TIMESTAMP' },
  ));

  assert.equal(merged.get('ursToken'), 'NEW_TOKEN');
  assert.equal(merged.get('sign'), 'PAGE_SIGN');
  assert.equal(merged.get('timestamp'), 'PAGE_TIMESTAMP');
});

test('网易号验证码恢复会把编辑页验证凭证带回正式发布表单', () => {
  const merged = new URLSearchParams(mergeWangyiRefreshedForm(
    new URLSearchParams({
      operation: 'publish',
      articleId: 'ARTICLE',
      title: '真实标题',
      content: '<p>真实正文</p>',
    }).toString(),
    new URLSearchParams({ ursToken: 'NEW_TOKEN' }).toString(),
    { NECaptchaValidate: 'PAGE_VALIDATE' },
  ));

  assert.equal(merged.get('operation'), 'publish');
  assert.equal(merged.get('articleId'), 'ARTICLE');
  assert.equal(merged.get('NECaptchaValidate'), 'PAGE_VALIDATE');
});

test('网易号验证码恢复在页面状态更新后再次触发页面保存', async () => {
  const session = {
    request: { query: { id: 'ID', referer: 'REFERER' } },
    challenge: { token: 'TOKEN', type: 3, zoneId: 'CN31' },
  };
  const monitor = {
    saveResponses: [{
      status: 200,
      ok: true,
      code: 100502,
      message: '需要进行图形验证码验证',
      classification: 'captcha',
      payload: { code: 100502, msg: '需要进行图形验证码验证' },
    }],
    latestCaptchaSession() { return session; },
    captchaSessionCount() { return 1; },
    async waitForCaptchaSession() { return session; },
    async waitForSaveResponseAfter() { return this.saveResponses[0]; },
  };
  let recognitionRequest;
  let submitRequest;
  let triggerRequest;
  const result = await recoverWangyiRequestWithTtOcr(
    {},
    monitor,
    { url: 'https://mp.163.com/wemedia/article/status/api/publishV2.do', method: 'POST' },
    new URLSearchParams({ operation: 'saveDraft', title: '标题', content: '<p>正文</p>' }).toString(),
    { bodyChars: 2, title: '标题', text: '正文' },
    {
      provider: { appKey: 'APPKEY', itemId: 500, timeoutMs: 1000 },
      recognize: async request => {
        recognitionRequest = request;
        return { data: 'SOLVED_DATA', validate: 'SOLVED_DATA', durationMs: 20, providerTimeMs: 20 };
      },
      submit: async (_page, currentSession, data) => {
        submitRequest = { currentSession, data };
        return { passed: true, validate: 'VALIDATE_TOKEN' };
      },
      triggerSave: async (_page, state) => {
        triggerRequest = state;
        return { status: 200, ok: true, payload: { code: 1, msg: '操作成功', data: 'docId=RECOVERED' } };
      },
    },
  );

  assert.equal(result.payload.code, 1);
  assert.equal(recognitionRequest.id, 'ID');
  assert.equal(recognitionRequest.referer, 'REFERER');
  assert.equal(submitRequest.currentSession, session);
  assert.equal(submitRequest.data, 'SOLVED_DATA');
  assert.deepEqual(triggerRequest, { bodyChars: 2, title: '标题', text: '正文' });
});

test('网易号验证码恢复优先使用已经触发的初次页面保存响应', async () => {
  const initialResponse = {
    status: 200,
    ok: true,
    payload: { code: 1, msg: '操作成功', data: 'docId=INITIAL' },
  };
  const monitor = {
    async waitForSaveResponseAfter() {
      throw new Error('不应重复等待初次保存');
    },
  };

  const result = await recoverWangyiRequestWithTtOcr(
    {},
    monitor,
    { method: 'POST' },
    '',
    null,
    { initialResponse },
  );

  assert.equal(result.payload.code, 1);
});

test('网易号验证码探测能轮询并读取容器和背景图的实际位置尺寸', async () => {
  const root = {
    first() { return this; },
    async waitFor() {},
    async isVisible() { return true; },
    async boundingBox() { return { x: 10, y: 20, width: 300, height: 220 }; },
  };
  const background = {
    first() { return this; },
    async isVisible() { return true; },
    async boundingBox() { return { x: 20, y: 30, width: 280, height: 180 }; },
    async evaluate() { return { naturalWidth: 560, naturalHeight: 360, complete: true }; },
  };
  const page = {
    locator(selector) {
      if (selector === '#captcha') return root;
      if (selector === '.yidun_bgimg') return background;
      throw new Error(`unexpected selector: ${selector}`);
    },
  };

  const result = await waitForWangyiCaptchaElement(page, { timeoutMs: 50, pollMs: 5 });
  assert.deepEqual(result, {
    rootSelector: '#captcha',
    backgroundSelector: '.yidun_bgimg',
    rootBox: { x: 10, y: 20, width: 300, height: 220 },
    backgroundBox: { x: 20, y: 30, width: 280, height: 180 },
    imageSize: { naturalWidth: 560, naturalHeight: 360, complete: true },
  });
});

test('网易号缺少封面时在发起平台请求前停止发布', async () => {
  await assert.rejects(
    new WangyiAdapter().publish(null, { topicImage: null }),
    error => error.code === 'COVER_REQUIRED' && /必须填写封面/.test(error.message),
  );
});

test('网易号发布表单包含草稿和正式发布共用字段', () => {
  const form = buildWangyiPublishForm({
    wemediaId: 'MEDIA', articleId: 'ARTICLE', title: '接口测试', html: '<p>正文</p>',
    operation: 'publish', cover: 'custom', picUrl: 'https://cdn.example/a.jpg',
    sign: 'SIGN', timestamp: 'TIME',
  });

  assert.equal(form.get('wemediaId'), 'MEDIA');
  assert.equal(form.get('articleId'), 'ARTICLE');
  assert.equal(form.get('operation'), 'publish');
  assert.equal(form.get('content'), '<p>正文</p>');
  assert.equal(form.get('cover'), 'custom');
  assert.equal(form.get('sign'), 'SIGN');
  assert.equal(form.get('timestamp'), 'TIME');
});

test('网易号会话元数据只提取网易相关 Cookie 和可选动态令牌', () => {
  const metadata = getWangyiSessionMetadata({
    cookies: [
      { domain: '.163.com', name: 'sid', value: 'SESSION' },
      { domain: 'dl.reg.163.com', name: 'gdxidpyhxdE', value: 'REG_ONLY' },
      { domain: 'mp.163.com', name: 'gdxidpyhxdE', value: 'MP_API' },
      { domain: 'c.dun.163.com', name: '_gid', value: 'CAPTCHA_ONLY' },
      { domain: 'mp.163.com', path: '/subscribe_v4', name: 'editorOnly', value: 'EDITOR_ONLY' },
      { domain: 'example.com', name: 'other', value: 'ignored' },
    ],
    origins: [{ origin: 'https://mp.163.com', localStorage: [{ name: 'ursToken', value: 'TOKEN' }] }],
  });
  assert.equal(metadata.cookies, 'gdxidpyhxdE=MP_API; sid=SESSION');
  assert.equal(metadata.storedUrsToken, 'TOKEN');
});

test('网易号图片 data URL 按上传顺序替换为 CDN 地址', () => {
  const html = '<p><img src="data:image/png;base64,AAA"></p><img src="data:image/jpeg;base64,BBB">';
  assert.equal(
    replaceWangyiImageSources(html, ['https://cdn.example/1.png', 'https://cdn.example/2.jpg']),
    '<p><img src="https://cdn.example/1.png"></p><img src="https://cdn.example/2.jpg">',
  );
});

test('网易号内容状态映射审核中、已发布、展示受限和失败', () => {
  assert.equal(mapWangyiContentStatus({ contentState: 1 }).status, 'reviewing');
  assert.deepEqual(
    mapWangyiContentStatus({ contentState: 3, articleId: 'ARTICLE' }),
    {
      platformState: 3, platformStatus: '已发布',
      status: 'published', healthStatus: 'normal',
      url: 'https://www.163.com/dy/article/ARTICLE.html', detail: '',
    },
  );
  assert.deepEqual(
    mapWangyiContentStatus({
      contentState: 3,
      articleId: 'LIMITED',
      unrecomReason: '该内容分发受限',
    }),
    {
      platformState: 3, platformStatus: '已发布',
      status: 'published', healthStatus: 'restricted',
      url: 'https://www.163.com/dy/article/LIMITED.html', detail: '该内容分发受限',
    },
  );
  const failed = mapWangyiContentStatus({ contentState: 5, reason: '不成功-不符合发文规定' });
  assert.equal(failed.status, 'failed');
  assert.equal(failed.healthStatus, 'rejected');
  assert.equal(failed.detail, '不成功-不符合发文规定');
  assert.equal(mapWangyiContentStatus({ contentState: 5, reason: '处理失败' }).healthStatus, undefined);
});

test('网易号识别平台真实的审核拒绝与已发布不展示文案', () => {
  for (const reason of [
    '与平台已有内容高度相似',
    '内容含有广告信息',
    '文章被平台判定为广告软文，具体原因请查看系统消息。',
    '含敏感词汇，不适宜发布',
  ]) {
    const result = mapWangyiContentStatus({ contentState: 5, reason });
    assert.equal(result.status, 'failed');
    assert.equal(result.healthStatus, 'rejected');
  }

  for (const reason of [
    '因该内容分发受限',
    '因内容分发受限，影响内容展现',
    '因内容含有广告信息，影响内容展现',
  ]) {
    const result = mapWangyiContentStatus({
      contentState: 3, articleId: 'LIMITED', isRecommend: 1, unrecomReason: reason,
    });
    assert.equal(result.status, 'published');
    assert.equal(result.healthStatus, 'restricted');
    assert.equal(result.detail, reason);
  }
});

test('网易号补齐 contentState 全量映射，并保留历史标准状态', () => {
  assert.deepEqual(Object.fromEntries(Object.entries(WANGYI_CONTENT_STATUS).map(([key, value]) => [key, value.label])), {
    '-1': '全部状态', 0: '草稿', 1: '审核中', 2: '未通过', 3: '已发布', 4: '处理中',
    5: '处理失败', 6: '未通过', 7: '作者下线', 8: '待发布', 9: '已删除', 10: '作者删除', 11: 'MCN主账号下线',
  });
  const cases = [
    [0, 'draft'], [1, 'reviewing'], [2, 'failed'], [4, 'processing'], [5, 'failed'],
    [6, 'failed'], [7, 'published'], [8, 'scheduled'], [9, 'published'],
    [10, 'published'], [11, 'published'],
  ];
  for (const [contentState, status] of cases) {
    const result = mapWangyiContentStatus({ contentState, articleId: 'ARTICLE' });
    assert.equal(result.status, status);
    assert.equal(result.platformState, contentState);
    assert.equal(result.platformStatus, WANGYI_CONTENT_STATUS[contentState].label);
  }
  assert.equal(mapWangyiContentStatus({ contentState: 7 }).healthStatus, 'offline');
  assert.equal(mapWangyiContentStatus({ contentState: 9 }).healthStatus, 'deleted');
  assert.equal(
    mapWangyiContentStatus({ contentState: 3, articleId: 'PRIVATE', isRecommend: 0, unrecomReason: '内容不符合社区规范，仅自己可见' }).healthStatus,
    'restricted',
  );
});

test('网易号 API 客户端允许显式提供动态 ursToken', async () => {
  const client = new WangyiApiClient(1, { cookies: [] }, {
    ursTokenProvider: async () => 'PROVIDED_TOKEN',
  });
  assert.equal(await client.getUrsToken({}), 'PROVIDED_TOKEN');
});

test('网易号 navinfo 账号资料提取手机号', async () => {
  const client = new WangyiApiClient(1, {
    cookies: [{ domain: '.163.com', name: 'sid', value: 'FIXTURE' }],
  });
  client.request = async () => ({
    data: {
      tname: '网易测试账号',
      loginUser: '10000000000',
      realUserId: '10000000000',
      wemediaId: 'WM-1',
    },
  });

  const profile = await client.getAccountProfile();

  assert.equal(profile.username, '10000000000');
  assert.equal(profile.phone, '10000000000');
});

test('网易号封禁判定优先识别接口错误码和 FORBIDDEN onlineState', () => {
  assert.deepEqual(WANGYI_BANNED_ERROR_CODES, [100023]);
  assert.equal(WANGYI_FORBIDDEN_ONLINE_STATE, 7);
  assert.equal(classifyWangyiAccountStatus({ code: 100023 }), 'banned');
  assert.equal(classifyWangyiAccountStatus({ profile: { onlineState: 7 } }), 'banned');
  assert.equal(classifyWangyiAccountStatus({ code: 1, profile: { onlineState: 2 } }), '');
});

test('网易号 navinfo 返回 FORBIDDEN 时登录检查会返回 banned', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    code: 1,
    msg: '操作成功',
    data: { wemediaId: 'WM-FORBIDDEN', realUserId: 'USER-FORBIDDEN', onlineState: 7 },
  }), { status: 200, headers: { 'content-type': 'application/json' } });

  try {
    const checked = await new WangyiApiClient(101, {
      cookies: [{ domain: '.163.com', name: 'sid', value: 'FIXTURE' }],
    }).checkLogin();
    assert.equal(checked.ok, false);
    assert.equal(checked.accountStatus, 'banned');
    assert.equal(checked.profile.onlineState, 7);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('网易号接口返回 100023 时登录检查会返回 banned 并保留错误标记', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    code: 100023,
    msg: '账号已被封禁',
  }), { status: 200, headers: { 'content-type': 'application/json' } });

  try {
    const checked = await new WangyiApiClient(102, {
      cookies: [{ domain: '.163.com', name: 'sid', value: 'FIXTURE' }],
    }).checkLogin();
    assert.equal(checked.ok, false);
    assert.equal(checked.accountStatus, 'banned');
    assert.equal(checked.error.code, 100023);
    assert.equal(checked.error.accountStatus, 'banned');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('网易号接口遇到验证码后调用恢复器并接续使用最新登录态', async () => {
  const originalFetch = globalThis.fetch;
  let apiCalls = 0;
  let recoveryCalls = 0;
  let recoveryRequest;
  globalThis.fetch = async () => {
    apiCalls += 1;
    return new Response(JSON.stringify({
      code: 1001,
      msg: '需要进行图形验证码验证',
      data: { captchaRequired: true },
    }), { status: 200, headers: { 'content-type': 'application/json' } });
  };

  try {
    const client = new WangyiApiClient(99, {
      cookies: [{ domain: '.163.com', name: 'sid', value: 'OLD' }],
    }, {
      captchaRecovery: async request => {
        recoveryCalls += 1;
        recoveryRequest = { method: request.method, body: request.body.toString() };
        return {
          status: 200,
          ok: true,
          payload: { code: 1, msg: '操作成功', data: 'docId=RECOVERED' },
          storageState: {
            cookies: [{ domain: '.163.com', name: 'sid', value: 'NEW' }],
            origins: [],
          },
        };
      },
    });
    const payload = await client.request('/wemedia/article/status/api/publishV2.do', {
      method: 'POST',
      body: new URLSearchParams({ operation: 'saveDraft', title: 'TEST' }),
    });

    assert.equal(isWangyiCaptchaError(new WangyiApiError('验证码提示', {
      status: 200,
      code: 1001,
      payload: { data: { captchaRequired: true } },
    })), true);
    assert.equal(apiCalls, 1);
    assert.equal(recoveryCalls, 1);
    assert.deepEqual(recoveryRequest, { method: 'POST', body: 'operation=saveDraft&title=TEST' });
    assert.deepEqual(payload, { code: 1, msg: '操作成功', data: 'docId=RECOVERED' });
    assert.equal(client.metadata.cookies, 'sid=NEW');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('网易号正式发布重试会使用验证码恢复后页面刷新的动态表单', async () => {
  const originalFetch = globalThis.fetch;
  const requestBodies = [];
  let apiCalls = 0;
  globalThis.fetch = async (_url, options = {}) => {
    apiCalls += 1;
    requestBodies.push(String(options.body || ''));
    const payload = apiCalls === 1
      ? { code: 1001, msg: '需要进行图形验证码验证', data: { captchaRequired: true } }
      : { code: 1, msg: '操作成功', data: 'docId=REPUBLISHED' };
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = new WangyiApiClient(100, {
      cookies: [{ domain: '.163.com', name: 'sid', value: 'OLD' }],
    }, {
      captchaRecovery: async () => ({
        storageState: {
          cookies: [{ domain: '.163.com', name: 'sid', value: 'NEW' }],
          origins: [],
        },
        requestBody: 'operation=publish&ursToken=REFRESHED',
      }),
    });
    const payload = await client.request('/wemedia/article/status/api/publishV2.do', {
      method: 'POST',
      body: new URLSearchParams({ operation: 'publish', ursToken: 'STALE' }),
    });

    assert.deepEqual(payload, { code: 1, msg: '操作成功', data: 'docId=REPUBLISHED' });
    assert.equal(apiCalls, 2);
    assert.equal(requestBodies[0], 'operation=publish&ursToken=STALE');
    assert.equal(requestBodies[1], 'operation=publish&ursToken=REFRESHED');
  } finally {
    globalThis.fetch = originalFetch;
  }
});
