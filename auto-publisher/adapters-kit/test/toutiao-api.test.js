import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildToutiaoPublishForm,
  mapToutiaoArticleStatus,
  normalizeToutiaoTitle,
  replaceToutiaoImageSources,
  ToutiaoApiClient,
  validateToutiaoTitle,
} from '../src/adapters/toutiao/api.js';

test('今日头条发布表单保持真实接口字段与格式', () => {
  const form = buildToutiaoPublishForm({
    accountId: 3,
    title: '混合接口测试',
    html: '<p data-track="1">正文</p><table><tr><td>A</td></tr></table>',
    text: '正文 A',
  });
  assert.equal(form.get('source'), '29');
  assert.equal(form.get('content'), '<p data-track="1">正文</p><table><tr><td>A</td></tr></table>');
  assert.deepEqual(JSON.parse(form.get('draft_form_data')), { coverType: 2 });
  assert.deepEqual(JSON.parse(form.get('pgc_feed_covers')), []);
  assert.equal(JSON.parse(form.get('extra')).content_word_cnt, 4);
  assert.equal(JSON.parse(form.get('mp_editor_stat')).image, 1);
  assert.equal(form.get('article_ad_type'), '2');
});

test('今日头条标题匹配时可规范化，但发布表单拒绝超限标题', () => {
  const title = '老年猫肠胃消化变差、体重难控？适合7岁+老猫的肠胃友好猫粮推荐';
  assert.equal([...title].length, 31);
  assert.equal(normalizeToutiaoTitle(title), [...title].slice(0, 30).join(''));
  assert.throws(
    () => validateToutiaoTitle(title),
    error => error.code === 'TITLE_TOO_LONG'
      && /当前 31 字/.test(error.message)
      && /最多 30 字/.test(error.message)
      && /不会自动截断/.test(error.message),
  );
  assert.throws(() => buildToutiaoPublishForm({ title }), /标题超过平台限制/);
});

test('今日头条短标题按 2~30 字限制校验', () => {
  assert.equal(validateToutiaoTitle('猫粮推荐'), '猫粮推荐');
  assert.throws(() => validateToutiaoTitle('猫'), /2~30 字/);
});

test('今日头条作品状态映射已发布、审核中和草稿', () => {
  assert.deepEqual(
    mapToutiaoArticleStatus({
      item_id: '123', status_desc: '已发布',
      pgc_cell: JSON.stringify({ status: 3, status_desc: '已发布', is_passed: true }),
    }),
    { status: 'published', url: 'https://www.toutiao.com/item/123/', detail: '已发布' },
  );
  assert.equal(mapToutiaoArticleStatus({ status_desc: '审核中' }).status, 'reviewing');
  assert.equal(mapToutiaoArticleStatus({ status_desc: '草稿' }).status, 'draft');
  assert.equal(mapToutiaoArticleStatus({
    article_attr: { item_id: '789', status: 1, status_desc: '审核中', pgc_cell: '' },
    previewUrl: 'https://mp.toutiao.com/preview_article/?pgc_id=789',
  }).url, 'https://mp.toutiao.com/preview_article/?pgc_id=789');
  assert.equal(mapToutiaoArticleStatus({
    article_attr: {
      item_id: '456', status: 2, status_desc: '已发布',
      pgc_cell: JSON.stringify({ status: 3, is_passed: true }),
    },
  }).url, 'https://www.toutiao.com/item/456/');
});

test('今日头条接口客户端要求浏览器上下文获取账号 Cookie', async () => {
  const client = new ToutiaoApiClient(3, null, null);
  await assert.rejects(() => client.refreshCookies(), /浏览器上下文/);
});

test('今日头条按 pgc_id 回查时跳过列表相似标题并继续查询 Feed', async () => {
  const title = '老年猫肠胃消化变差、体重难控？适合7岁+老猫的肠胃友好猫粮推荐';
  const pgcId = '7670836259137159706';
  const truncatedTitle = normalizeToutiaoTitle(title);
  const client = new ToutiaoApiClient(3, null, null);
  let feedCalls = 0;
  client.listArticles = async () => [{
    article_attr: {
      item_id: '1872761978903708',
      title: truncatedTitle,
      rich_title: truncatedTitle,
      status: 2,
      status_desc: '由文章生成',
    },
  }];
  client.listFeedArticles = async () => {
    feedCalls += 1;
    return [{
      article_attr: {
        item_id: pgcId,
        gid: pgcId,
        title: truncatedTitle,
        rich_title: truncatedTitle,
        status: 1,
        status_desc: '审核中',
      },
      previewUrl: `https://i.snssdk.com/feoffline/mp-article-preview/graphic?pgc_id=${pgcId}`,
    }];
  };

  const result = await client.findPublication(title, { pgcId });
  assert.equal(feedCalls, 1);
  assert.equal(result.status, 'reviewing');
  assert.equal(result.article.article_attr.item_id, pgcId);
  assert.match(result.url, new RegExp(`pgc_id=${pgcId}`));
});

test('今日头条 pgc_id 对应未知记录时优先使用同标题的正式作品', async () => {
  const title = '幼猫断奶后吃什么猫粮好？适合 4-12 月龄幼猫的猫粮推荐';
  const client = new ToutiaoApiClient(3, null, null);
  let feedCalls = 0;
  client.listArticles = async () => [
    { article_attr: { item_id: '1872771345419264', title, status: 2, status_desc: '由文章生成' } },
    {
      article_attr: {
        item_id: '7670868771279520265', title, status: 2, status_desc: '已发布',
        pgc_cell: JSON.stringify({ status: 3, is_passed: true }),
      },
    },
  ];
  client.listFeedArticles = async () => {
    feedCalls += 1;
    throw Object.assign(new Error('HTTP 403'), { status: 403 });
  };

  const result = await client.findPublication(title, { pgcId: '1872771345419264' });
  assert.equal(feedCalls, 0);
  assert.equal(result.status, 'published');
  assert.equal(result.url, 'https://www.toutiao.com/item/7670868771279520265/');
});

test('今日头条 Feed 403 时保留可用列表状态', async () => {
  const title = 'Feed 403 降级测试';
  const client = new ToutiaoApiClient(3, null, null);
  client.listArticles = async () => [{
    article_attr: { item_id: '123', title, status: 2, status_desc: '审核中' },
  }];
  client.listFeedArticles = async () => {
    throw Object.assign(new Error('HTTP 403'), { status: 403 });
  };

  const result = await client.findPublication(title, { pgcId: '123' });
  assert.equal(result.status, 'reviewing');
});

test('今日头条正文按上传顺序替换上游内容源图片 data URL', () => {
  const html = '<p><img src="data:image/png;base64,AAA"></p><img SRC=\'data:image/jpeg;base64,BBB\'>';
  assert.equal(
    replaceToutiaoImageSources(html, ['https://image.example/1.png', 'https://image.example/2.jpg']),
    '<p><img src="https://image.example/1.png"></p><img SRC=\'https://image.example/2.jpg\'>',
  );
});
