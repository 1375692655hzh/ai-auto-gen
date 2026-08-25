/**
 * 平台适配器注册表。多维表格「目标平台」字段值 → adapter。
 */
import SohuAdapter from './sohu/index.js';
import ToutiaoAdapter from './toutiao/index.js';
import WangyiAdapter from './wangyi/index.js';
import ZdmAdapter from './zdm/index.js';
import { getPlatformDailyLimit } from '../domain/dailyQuota.js';
import { publicPlatformConstraints } from '../domain/platformConstraints.js';

const ADAPTERS = [SohuAdapter, ToutiaoAdapter, WangyiAdapter, ZdmAdapter];

const byId = new Map(ADAPTERS.map(A => [A.id, A]));
// 表格里的平台名（含常见别名）→ adapter id
const NAME_ALIASES = new Map([
  ['搜狐', 'sohu'], ['搜狐号', 'sohu'], ['sohu', 'sohu'],
  ['网易', 'wangyi'], ['网易号', 'wangyi'], ['wangyi', 'wangyi'], ['163', 'wangyi'],
  ['头条', 'toutiao'], ['今日头条', 'toutiao'], ['头条号', 'toutiao'], ['toutiao', 'toutiao'],
  ['什么值得买', 'zdm'], ['值得买', 'zdm'], ['zdm', 'zdm'], ['smzdm', 'zdm'],
]);

export function listPlatforms() {
  return ADAPTERS.map(A => ({
    id: A.id,
    name: A.name_,
    loginUrl: A.loginUrl,
    dailyLimit: getPlatformDailyLimit(A.id),
    // 前端分发弹窗用它做提交前预检，避免任务跑到 adapter 里才因标题超限失败。
    constraints: publicPlatformConstraints(A.id),
    managementUrl: A.selectors?.managementUrl || A.homeUrl,
    // false = 控制台扫码流不可用（如网易无二维码、值得买有滑块），前端引导走 companion 本机登录
    qrLogin: A.supportsQrLogin !== false,
  }));
}

export function getAdapter(platformNameOrId) {
  const key = String(platformNameOrId || '').trim();
  const id = byId.has(key) ? key : NAME_ALIASES.get(key) || NAME_ALIASES.get(key.toLowerCase());
  const Adapter = byId.get(id);
  if (!Adapter) {
    throw new Error(`不支持的平台「${platformNameOrId}」，当前支持: ${[...NAME_ALIASES.keys()].join('、')}`);
  }
  return new Adapter();
}
