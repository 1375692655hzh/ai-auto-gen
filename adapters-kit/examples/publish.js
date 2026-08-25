import fs from 'node:fs/promises';
import {
  getAdapter, setStorageState, withHeadlessAccountContext, checkArticleForPlatform, hasBlockingIssue,
} from '../src/index.js';

const [platform = '', accountId = 'demo-account', storageFile = '', articleFile = ''] = process.argv.slice(2);
if (!platform || !storageFile || !articleFile) {
  console.error('用法: node examples/publish.js <sohu|toutiao|wangyi|zdm> <accountId> <storageState.json> <article.json>');
  process.exitCode = 1;
} else {
  const storageState = JSON.parse(await fs.readFile(storageFile, 'utf8'));
  const article = JSON.parse(await fs.readFile(articleFile, 'utf8'));
  setStorageState(accountId, storageState);

  const adapter = getAdapter(platform);
  const issues = checkArticleForPlatform({
    ...article,
    bodyChars: String(article.text || '').replace(/\s/g, '').length,
    imageCount: article.images?.length || 0,
    coverAvailable: Boolean(article.topicImage?.path || article.topicImage?.longPath),
  }, adapter.id, adapter.name);
  for (const issue of issues) console.warn(`[预检][${issue.severity}] ${issue.message}`);
  if (hasBlockingIssue(issues)) throw new Error('平台预检未通过');

  const hooks = {
    accountId,
    mode: 'auto',
    onStage: (stage, detail = '') => console.log(`[${adapter.id}] ${stage}`, detail),
    onLoginChecked: ok => console.log(`[${adapter.id}] 登录态: ${ok ? '有效' : '失效'}`),
  };

  const run = page => adapter.publish(page, article, hooks);
  const result = adapter.constructor.apiOnly
    ? await run(null)
    : await withHeadlessAccountContext(accountId, run, { headless: process.env.PUBLISHING_KIT_HEADLESS !== '0' });
  console.log(JSON.stringify(result, null, 2));
}
