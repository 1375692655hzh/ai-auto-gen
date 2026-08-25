import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildSohuPublishPayload,
  getSohuSessionMetadata,
  isSohuAccountBanned,
  mapSohuNewsStatus,
  normalizeSohuAssetUrl,
  replaceSohuImageSources,
  SohuApiClient,
} from '../src/adapters/sohu/api.js';

test('根据搜狐 register-info 的状态字段识别已查封账号', () => {
  assert.equal(isSohuAccountBanned({ statusName: '查封' }), true);
  assert.equal(isSohuAccountBanned({ banStatus: 1 }), true);
  assert.equal(isSohuAccountBanned({ freezeStatus: 'true' }), true);
  assert.equal(isSohuAccountBanned({ statusName: '正常', banStatus: 0, freezeStatus: 0 }), false);
});

test('搜狐登录检查保留平台查封状态，而不是归类为普通掉登录', async () => {
  const client = new SohuApiClient(42, {
    cookies: [],
    origins: [{
      origin: 'https://mp.sohu.com',
      localStorage: [{ name: 'currentAccount', value: JSON.stringify({ id: 42 }) }],
    }],
  });
  client.request = async pathname => pathname.includes('/pending?')
    ? { data: { accountId: 42, nickName: '已查封账号', channelId: 28 } }
    : {
      data: {
        account: { id: 42, nickName: '已查封账号', status: 3, statusName: '查封', banStatus: 0, freezeStatus: 0 },
        user: { userCode: 'account@example' },
      },
    };

  const checked = await client.checkLogin();

  assert.equal(checked.ok, false);
  assert.equal(checked.accountStatus, 'banned');
  assert.equal(checked.profile.statusName, '查封');
});

test('搜狐 register-info 账号资料提取手机号', async () => {
  const client = new SohuApiClient(42, {
    cookies: [],
    origins: [{
      origin: 'https://mp.sohu.com',
      localStorage: [{ name: 'currentAccount', value: JSON.stringify({ id: 42 }) }],
    }],
  });
  client.request = async pathname => pathname.includes('/pending?')
    ? { data: { accountId: 42, nickName: '搜狐测试账号' } }
    : { data: { account: { id: 42 }, user: { mobile: '10000000000' } } };

  const profile = await client.getAccountProfile();

  assert.equal(profile.username, '10000000000');
  assert.equal(profile.phone, '10000000000');
});

test('搜狐发布次数错误可由账号状态核验进一步识别查封', async () => {
  const client = new SohuApiClient(42, {
    cookies: [],
    origins: [{
      origin: 'https://mp.sohu.com',
      localStorage: [{ name: 'currentAccount', value: JSON.stringify({ id: 42 }) }],
    }],
  });
  client.request = async pathname => {
    if (pathname.includes('publishLimit')) {
      const error = new Error('用户不存在');
      error.code = 4002000;
      throw error;
    }
    if (pathname.includes('/pending?')) return { data: { accountId: 42, nickName: '已查封账号' } };
    return { data: { account: { id: 42, nickName: '已查封账号', statusName: '查封' } } };
  };

  await assert.rejects(() => client.getPublishLimit(), /用户不存在/);
  const checked = await client.checkLogin();
  assert.equal(checked.accountStatus, 'banned');
});

test('搜狐发布 payload 使用新文章 id=0，并保留平台必需默认字段', () => {
  const payload = buildSohuPublishPayload({
    accountId: 122492937,
    title: '接口发布测试',
    html: '<p>正文</p>',
    channelId: 28,
    tags: 'AI，搜狐',
  });

  assert.equal(payload.id, 0);
  assert.equal(payload.accountId, 122492937);
  assert.equal(payload.channelId, 28);
  assert.equal(payload.customTags, 'AI,搜狐');
  assert.deepEqual(payload.topicIds, []);
  assert.equal(payload.userLabels, '[]');
  assert.equal(payload.content, '<p>正文</p>');
});

test('搜狐图片地址与正文 data URL 按顺序替换，兼容单双引号', () => {
  assert.equal(normalizeSohuAssetUrl('//res.mp.sohu.com/a.jpg'), 'https://res.mp.sohu.com/a.jpg');
  const html = '<p><img src=\"data:image/png;base64,AAA\"></p><img SRC=\'data:image/jpeg;base64,BBB\'>';
  const replaced = replaceSohuImageSources(html, ['//res.mp.sohu.com/1.png', 'https://res.mp.sohu.com/2.jpg']);
  assert.equal(
    replaced,
    '<p><img src=\"https://res.mp.sohu.com/1.png\"></p><img SRC=\'https://res.mp.sohu.com/2.jpg\'>',
  );
});

test('搜狐会话元数据从 Playwright storageState 提取账号与动态请求头', () => {
  const storageState = {
    cookies: [
      { domain: '.sohu.com', name: 'sid', value: 'SESSION' },
      { domain: 'example.com', name: 'other', value: 'ignored' },
    ],
    origins: [{
      origin: 'https://mp.sohu.com',
      localStorage: [
        { name: 'currentAccount', value: JSON.stringify({ id: 42, channelId: 28 }) },
        { name: 'preview-dv-id', value: 'DV-ID' },
        { name: 'preview-sp-cm', value: 'SP-CM' },
      ],
    }],
  };
  const metadata = getSohuSessionMetadata(storageState);

  assert.equal(metadata.accountId, 42);
  assert.equal(metadata.cookies, 'sid=SESSION');
  assert.equal(metadata.dvId, 'DV-ID');
  assert.equal(metadata.spCm, 'SP-CM');
  assert.equal(new SohuApiClient(1, storageState).accountId, 42);
});

test('搜狐作品状态映射包含已发布、审核中与审核失败', () => {
  assert.deepEqual(
    mapSohuNewsStatus({ id: 100, status: 4, auditStatus: 4 }, 42),
    { status: 'published', url: 'https://www.sohu.com/a/100_42', detail: '' },
  );
  assert.equal(mapSohuNewsStatus({ status: 2, auditStatus: 1 }, 42).status, 'reviewing');
  assert.equal(mapSohuNewsStatus({ status: 3, auditStatus: 8, rejectReason: '内容不合规' }, 42).status, 'failed');
});

test('搜狐核验会快速遍历接口返回的全部分页，而不是只查第一页', async () => {
  const client = new SohuApiClient(42, {
    cookies: [],
    origins: [{
      origin: 'https://mp.sohu.com',
      localStorage: [{ name: 'currentAccount', value: JSON.stringify({ id: 42 }) }],
    }],
  });
  const requestedPages = [];
  client.request = async pathname => {
    const page = Number(new URL(pathname, 'https://mp.sohu.com').searchParams.get('pno'));
    requestedPages.push(page);
    return {
      data: {
        totalPage: 2,
        news: page === 1
          ? [{ id: 1, title: '第一页文章', status: 4, auditStatus: 4 }]
          : [{ id: 2, title: '第二页目标测试文章标题', status: 4, auditStatus: 4 }],
      },
    };
  };

  const result = await client.findPublication('第二页目标测试文章标题');

  assert.equal(result.status, 'published');
  assert.deepEqual(requestedPages.sort((a, b) => a - b), [1, 2]);
});

test('搜狐核验在没有分页元数据时，遇到短页立即停止', async () => {
  const client = new SohuApiClient(42, {
    cookies: [],
    origins: [{
      origin: 'https://mp.sohu.com',
      localStorage: [{ name: 'currentAccount', value: JSON.stringify({ id: 42 }) }],
    }],
  });
  const requestedPages = [];
  client.request = async pathname => {
    const page = Number(new URL(pathname, 'https://mp.sohu.com').searchParams.get('pno'));
    requestedPages.push(page);
    return { data: { news: page === 1 ? Array.from({ length: 100 }, (_, id) => ({ id, title: `文章${id}` })) : [] } };
  };

  const result = await client.findPublication('不存在的文章');

  assert.equal(result, null);
  assert.deepEqual(requestedPages, [1, 2]);
});
