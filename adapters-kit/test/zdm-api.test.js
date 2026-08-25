import test from 'node:test';
import assert from 'node:assert/strict';
import {
  ZdmApiClient,
  ZDM_ACCOUNT_BANNED_ERROR_CODE,
  ZdmApiError,
  buildAwne,
  buildPublishForm,
  htmlToText,
  isZdmAccountBanned,
  probeZdmPublicVisibility,
  publicationCandidates,
  statusFromText,
  textCountFromHtml,
} from '../src/adapters/zdm/api.js';
import ZdmAdapter from '../src/adapters/zdm/index.js';

test('什么值得买适配器使用纯接口发布', () => {
  assert.equal(ZdmAdapter.apiOnly, true);
  assert.equal(ZdmAdapter.nonLoginBrowserMode, 'none');
});

test('根据发布接口错误码和黑屋标记识别什么值得买账号发布权限受限', () => {
  assert.equal(isZdmAccountBanned({
    error_code: ZDM_ACCOUNT_BANNED_ERROR_CODE,
    is_in_black_room: true,
  }), true);
  assert.equal(isZdmAccountBanned({
    payload: { error_code: String(ZDM_ACCOUNT_BANNED_ERROR_CODE), is_in_black_room: '1' },
  }), true);
  assert.equal(isZdmAccountBanned({
    raw: { blackroom_desc: '账号发布权限受限' },
  }), true);
  assert.equal(isZdmAccountBanned({
    error_code: 0,
    is_in_black_room: false,
    blackroom_desc: '',
    banright: [],
  }), false);
});

test('什么值得买登录检查保留平台账号封禁状态', async () => {
  const client = new ZdmApiClient(42, { cookies: [] });
  client.request = async () => ({
    smzdm_id: '42',
    nickname: '测试账号',
    error_code: ZDM_ACCOUNT_BANNED_ERROR_CODE,
    is_in_black_room: true,
  });

  const checked = await client.checkLogin();
  assert.equal(checked.ok, false);
  assert.equal(checked.accountStatus, 'banned');
  assert.equal(checked.profile.smzdmId, '42');
});

test('什么值得买接口返回零用户 ID 且无昵称用户名时判定为未登录', async () => {
  const client = new ZdmApiClient(42, { cookies: [] });
  client.request = async () => ({ smzdm_id: 0, nickname: '', username: '' });

  const checked = await client.checkLogin();
  assert.equal(checked.ok, false);
  assert.equal(checked.profile.authenticated, false);
  assert.equal(checked.profile.profileName, '');
  assert.equal(checked.profile.username, '');
  assert.equal(checked.profile.smzdmId, '');
});

test('什么值得买接口返回正数用户 ID 时判定为已登录', async () => {
  const client = new ZdmApiClient(42, { cookies: [] });
  client.request = async () => ({ smzdm_id: 12345, nickname: '', username: '' });

  const checked = await client.checkLogin();
  assert.equal(checked.ok, true);
  assert.equal(checked.profile.authenticated, true);
  assert.equal(checked.profile.smzdmId, '12345');
  assert.equal(checked.profile.platformAccountId, '12345');
});

test('什么值得买账号检查通过自动保存探针识别资料接口未暴露的封禁状态', async () => {
  const client = new ZdmApiClient(42, { cookies: [] });
  client.request = async () => ({ smzdm_id: '42', nickname: '测试账号' });
  client.allocateArticleId = async () => 'a82l3n76';
  client.prepareDraft = async () => ({});
  client.publishArticle = async () => {
    throw new ZdmApiError('账号发布权限受限', {
      code: ZDM_ACCOUNT_BANNED_ERROR_CODE,
      payload: { error_code: ZDM_ACCOUNT_BANNED_ERROR_CODE, is_in_black_room: true },
    });
  };

  const checked = await client.checkLogin({ probePublishPermission: true });
  assert.equal(checked.ok, false);
  assert.equal(checked.accountStatus, 'banned');
  assert.equal(checked.profile.smzdmId, '42');
});

test('什么值得买发布接口返回封禁响应时回写账号状态并转为发布拒绝', async () => {
  const originals = {
    checkLogin: ZdmApiClient.prototype.checkLogin,
    allocateArticleId: ZdmApiClient.prototype.allocateArticleId,
    prepareDraft: ZdmApiClient.prototype.prepareDraft,
    publishArticle: ZdmApiClient.prototype.publishArticle,
  };
  const loginChecks = [];
  ZdmApiClient.prototype.checkLogin = async () => ({ ok: true, profile: { smzdmId: '42' } });
  ZdmApiClient.prototype.allocateArticleId = async () => 'a82l3n76';
  ZdmApiClient.prototype.prepareDraft = async () => ({});
  ZdmApiClient.prototype.publishArticle = async () => {
    throw new ZdmApiError(
      '账号发布权限受限',
      {
        code: ZDM_ACCOUNT_BANNED_ERROR_CODE,
        payload: { error_code: ZDM_ACCOUNT_BANNED_ERROR_CODE, is_in_black_room: true },
      },
    );
  };

  try {
    await assert.rejects(
      new ZdmAdapter().publish(null, {
        title: '测试标题',
        html: '<p>正文</p>',
        images: [],
        topicImage: { longPath: '/tmp/long.jpg', squarePath: '/tmp/square.jpg' },
      }, {
        accountId: 42,
        onLoginChecked: (ok, accountStatus) => loginChecks.push({ ok, accountStatus }),
      }),
      error => error.code === 'PUBLISH_REJECTED' && /限制发布原创文章/.test(error.message),
    );
    assert.deepEqual(loginChecks, [
      { ok: true, accountStatus: undefined },
      { ok: false, accountStatus: 'banned' },
    ]);
  } finally {
    ZdmApiClient.prototype.checkLogin = originals.checkLogin;
    ZdmApiClient.prototype.allocateArticleId = originals.allocateArticleId;
    ZdmApiClient.prototype.prepareDraft = originals.prepareDraft;
    ZdmApiClient.prototype.publishArticle = originals.publishArticle;
  }
});

test('什么值得买缺少任一封面尺寸时在发起平台请求前停止发布', async () => {
  await assert.rejects(
    new ZdmAdapter().publish(null, { topicImage: { longPath: '/tmp/cover.jpg' } }),
    error => error.code === 'COVER_REQUIRED' && /长图和方图/.test(error.message),
  );
});

test('什么值得买 awne 使用 MD5 + AES-256-ECB-PKCS7', () => {
  assert.equal(buildAwne('12345', 85), '9zYQ0w88N0Jqm482TBZCJw==');
});

test('什么值得买正文文字数按 HTML 文本计算', () => {
  const html = '<h2>标题</h2><p><strong>正文</strong><img src="x">你好</p>';
  assert.equal(htmlToText(html).replace(/\s+/g, ''), '标题正文你好');
  assert.equal(textCountFromHtml(html), 6);
});

test('什么值得买发布表单包含 CSRF 外的业务字段和图片列表', () => {
  const form = buildPublishForm({
    articleId: 'TARGET',
    title: '测试标题',
    editorValue: '<p>正文</p>',
    awne: 'PAYLOAD',
    wne: 2,
    focusImage: '//a.zdmimg.com/cover.jpg',
    squarePicUrl: '//a.zdmimg.com/square.jpg',
    imageList: [{ id: 99, pic_url: 'https://am.zdmimg.com/body.jpg' }],
  });
  assert.equal(form.get('article_id'), 'TARGET');
  assert.equal(form.get('submit_type'), 'submit');
  assert.equal(form.get('editorValue'), '<p>正文</p>');
  assert.equal(form.get('awne'), 'PAYLOAD');
  assert.equal(form.get('wne'), '2');
  assert.equal(form.get('image_list[0][picture_id]'), '99');
  assert.equal(form.get('image_list[0][pic_url]'), 'https://am.zdmimg.com/body.jpg');
});

test('什么值得买客户端生成短文章 ID', () => {
  const id = ZdmApiClient.createArticleId();
  assert.match(id, /^[a-z0-9]{8}$/);
});

test('什么值得买创作中心缺少新文章入口时提示优先检查掉登录', async () => {
  const client = new ZdmApiClient(42, { cookies: [] });
  client.request = async () => '<html><body>请登录</body></html>';

  await assert.rejects(
    client.allocateArticleId(),
    error => error instanceof ZdmApiError
      && /通常是账号掉登录的特征/.test(error.message)
      && /请先重新登录后重试/.test(error.message),
  );
});

test('什么值得买以匿名访问 404 识别仅发布账号可见的展示受限', async () => {
  const result = await probeZdmPublicVisibility('https://post.smzdm.com/p/limited/', {
    fetchImpl: async () => new Response('', { status: 404 }),
    retryDelayMs: 0,
  });
  assert.deepEqual(result, {
    healthStatus: 'restricted',
    detail: '公开访问连续返回 404，仅发布账号可见',
  });

  let attempts = 0;
  const propagated = await probeZdmPublicVisibility('https://post.smzdm.com/p/propagated/', {
    fetchImpl: async () => new Response('', { status: attempts++ === 0 ? 404 : 200 }),
    retryDelayMs: 0,
  });
  assert.equal(propagated.healthStatus, 'normal');

  const uncertain = await probeZdmPublicVisibility('https://post.smzdm.com/p/protected/', {
    fetchImpl: async () => new Response('', { status: 403 }),
  });
  assert.equal(uncertain.healthStatus, 'unknown');
});

test('什么值得买文章列表按标题链接匹配，并读取该文章自己的状态', async () => {
  const title = '新手养幼猫，猫粮到底该怎么选？';
  const html = `
    <div class="pandect-content-common">
      <div class="pandect-content-stuff common article">
        <div class="p-pandect-content-title">
          <a href="https://post.smzdm.com/p/aqr0pwrv/">${title}</a>
          <em class="greed">已发布</em>
        </div>
        <div class="p-pandect-content-detail"><a href="https://post.smzdm.com/p/aqr0pwrv/">正文摘要</a></div>
      </div>
    </div>
    <div class="pandect-line"></div>
    <div class="pandect-content-common">
      <div class="p-pandect-content-title"><a href="https://post.smzdm.com/p/other1234/">另一篇文章</a><em class="greed">审核中</em></div>
    </div>
    <div class="pandect-line"></div>
  `;
  const candidates = publicationCandidates(html);
  assert.equal(candidates[0].title, title);
  assert.equal(candidates[0].statusText, '已发布');
  assert.equal(statusFromText(candidates[0].statusText).status, 'published');

  const originalFetch = global.fetch;
  global.fetch = async () => new Response(html, {
    status: 200,
    headers: { 'content-type': 'text/html; charset=utf-8' },
  });
  try {
    const result = await new ZdmApiClient(5, { cookies: [] }).findPublication(title);
    assert.equal(result.status, 'published');
    assert.equal(result.articleId, 'aqr0pwrv');
    assert.equal(result.url, 'https://post.smzdm.com/p/aqr0pwrv/');

    const resultByArticleId = await new ZdmApiClient(5, { cookies: [] }).findPublication(
      '标题已经变化但文章 ID 仍然准确',
      { articleId: 'aqr0pwrv' },
    );
    assert.equal(resultByArticleId.status, 'published');
    assert.equal(resultByArticleId.articleId, 'aqr0pwrv');
  } finally {
    global.fetch = originalFetch;
  }
});
