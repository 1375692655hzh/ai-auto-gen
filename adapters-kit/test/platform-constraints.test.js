import test from 'node:test';
import assert from 'node:assert/strict';
import {
  checkArticleForPlatform,
  checkPlatformCover,
  checkPlatformContent,
  checkPlatformTitle,
  getPlatformConstraints,
  hasBlockingIssue,
  publicPlatformConstraints,
  titleLength,
} from '../src/domain/platformConstraints.js';
import {
  TOUTIAO_TITLE_MAX_LENGTH, TOUTIAO_TITLE_MIN_LENGTH,
} from '../src/adapters/toutiao/api.js';

test('标题按码点计数，emoji 不算两字', () => {
  assert.equal(titleLength('猫粮推荐'), 4);
  assert.equal(titleLength('  前后空格  '), 4);
  assert.equal(titleLength('猫粮🐱'), 3);
  assert.equal(titleLength(null), 0);
});

test('头条标题范围与 adapter 常量同源', () => {
  const constraints = getPlatformConstraints('toutiao');
  assert.equal(constraints.titleMin, TOUTIAO_TITLE_MIN_LENGTH);
  assert.equal(constraints.titleMax, TOUTIAO_TITLE_MAX_LENGTH);
});

test('头条标题超 30 字判定为 error', () => {
  const issue = checkPlatformTitle('猫'.repeat(31), 'toutiao', '今日头条');
  assert.equal(issue.severity, 'error');
  assert.equal(issue.code, 'TITLE_TOO_LONG');
  assert.match(issue.message, /最多 30 字/);
  assert.match(issue.message, /当前 31 字/);
});

test('头条标题不足 2 字判定为 error 并给出区间', () => {
  const issue = checkPlatformTitle('猫', 'toutiao', '今日头条');
  assert.equal(issue.code, 'TITLE_TOO_SHORT');
  assert.match(issue.message, /2~30 字/);
});

test('网易标题按 5~64 字限制校验', () => {
  const issue = checkPlatformTitle('短标题', 'wangyi', '网易号');
  assert.equal(issue.code, 'TITLE_TOO_SHORT');
  assert.match(issue.message, /5~64 字/);
  assert.equal(checkPlatformTitle('猫'.repeat(64), 'wangyi', '网易号'), null);
  assert.equal(checkPlatformTitle('猫'.repeat(65), 'wangyi', '网易号').code, 'TITLE_TOO_LONG');
});

test('什么值得买标题最多 30 字，搜狐允许超过 30 字', () => {
  assert.equal(checkPlatformTitle('猫'.repeat(30), 'zdm', '什么值得买'), null);
  const issue = checkPlatformTitle('猫'.repeat(31), 'zdm', '什么值得买');
  assert.equal(issue.code, 'TITLE_TOO_LONG');
  assert.equal(issue.severity, 'error');
  assert.equal(checkPlatformTitle('猫'.repeat(65), 'sohu', '搜狐号'), null);
});

test('合规标题与无约束平台都返回 null', () => {
  assert.equal(checkPlatformTitle('一篇正常长度的标题', 'toutiao', '今日头条'), null);
  assert.equal(checkPlatformTitle('短', 'sohu', '搜狐号'), null);
});

test('空标题在任何平台都是 error', () => {
  for (const platform of ['sohu', 'toutiao', 'wangyi', 'zdm']) {
    const issue = checkPlatformTitle('   ', platform, platform);
    assert.equal(issue.code, 'TITLE_EMPTY', `${platform} 应拦下空标题`);
    assert.equal(issue.severity, 'error');
  }
});

test('值得买字数图片门槛是 warning，不阻塞提交', () => {
  const issues = checkPlatformContent({ bodyChars: 500, imageCount: 2 }, 'zdm', '什么值得买');
  assert.equal(issues.length, 2);
  assert.ok(issues.every(item => item.severity === 'warning'));
  assert.equal(hasBlockingIssue(issues), false);
  assert.match(issues[0].message, /不少于 800 字/);
  assert.match(issues[1].message, /不少于 5 张/);
});

test('正文指标缺失时跳过正文预检，不误报', () => {
  assert.deepEqual(checkPlatformContent({}, 'zdm', '什么值得买'), []);
  assert.deepEqual(checkPlatformContent({ bodyChars: null, imageCount: undefined }, 'zdm', '什么值得买'), []);
  // 0 是真实值，应当照常判定
  assert.equal(checkPlatformContent({ imageCount: 0 }, 'zdm', '什么值得买').length, 1);
});

test('达标内容不产生任何问题', () => {
  assert.deepEqual(checkPlatformContent({ bodyChars: 1200, imageCount: 6 }, 'zdm', '什么值得买'), []);
});

test('网易号和什么值得买强制要求封面', () => {
  for (const [platformId, platformName] of [['wangyi', '网易号'], ['zdm', '什么值得买']]) {
    const issue = checkPlatformCover(false, platformId, platformName);
    assert.equal(issue.code, 'COVER_REQUIRED');
    assert.equal(issue.severity, 'error');
    assert.match(issue.message, /必须填写封面/);
  }
  assert.equal(checkPlatformCover(true, 'wangyi', '网易号'), null);
  assert.equal(checkPlatformCover(false, 'sohu', '搜狐号'), null);
  assert.equal(checkPlatformCover(undefined, 'zdm', '什么值得买'), null);
});

test('checkArticleForPlatform 合并标题与正文问题', () => {
  const issues = checkArticleForPlatform(
    { title: '猫', bodyChars: 100, imageCount: 1 },
    'zdm',
    '什么值得买',
  );
  // 值得买没有标题下限，所以只剩两条正文问题
  assert.equal(issues.length, 2);
  assert.ok(issues.every(item => item.field !== 'title'));

  const toutiaoIssues = checkArticleForPlatform({ title: '猫'.repeat(40) }, 'toutiao', '今日头条');
  assert.equal(toutiaoIssues.length, 1);
  assert.equal(hasBlockingIssue(toutiaoIssues), true);
});

test('下发给前端的约束只含预检需要的字段', () => {
  assert.deepEqual(publicPlatformConstraints('toutiao'), {
    titleMin: 2, titleMax: 30, minBodyChars: null, minImages: null, coverRequired: false, reviewBeforePublish: false,
  });
  assert.deepEqual(publicPlatformConstraints('zdm'), {
    titleMin: null, titleMax: 30, minBodyChars: 800, minImages: 5, coverRequired: true, reviewBeforePublish: true,
  });
  assert.deepEqual(publicPlatformConstraints('wangyi'), {
    titleMin: 5, titleMax: 64, minBodyChars: null, minImages: null, coverRequired: true, reviewBeforePublish: false,
  });
  // 未知平台走默认值而不是抛错
  assert.equal(publicPlatformConstraints('unknown').titleMax, null);
});
