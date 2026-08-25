/**
 * BrowserManager —— 常驻 Chromium + 按需注入 storageState 的临时 context
 *
 * 登录态不再存本地 profile，而是按账号存 storageState JSON 于 SQLite（platform_accounts，
 * 每平台可多账号）。每个任务/检查用 withAccountContext 包裹：取该账号登录态 → newContext →
 * 干活 → 成功后导出回写 DB（cookie 轮换保鲜）→ 关 context。
 *
 * 服务器上由 xvfb-run 提供虚拟显示器跑 headful（扫码登录等交互流程）；
 * 接口流程使用 headless Chromium。每次 context 结束后同步回收所属 browser，
 * 避免常驻 Chromium 及其子进程积累。
 */
import { chromium } from 'playwright';
import { launch as launchCloakBrowser } from 'cloakbrowser';
import { getStorageState, refreshStorageState } from '../runtime/storage.js';

const LAUNCH_OPTS = {
  headless: !!process.env.PUBLISHING_KIT_HEADLESS,
  args: [
    '--disable-blink-features=AutomationControlled',
    '--no-first-run',
    '--no-default-browser-check',
  ],
  ignoreDefaultArgs: ['--enable-automation'],
};

const VIEWPORT = { width: 1440, height: 900 };
const CLOSE_TIMEOUT_MS = Math.max(
  1000,
  Number(process.env.PUBLISHING_KIT_BROWSER_CLOSE_TIMEOUT_MS) || 10_000,
);

// 搜狐 CDN（g1.itc.cn）对 Linux UA 返回 403（2026-07-11 服务器实测），统一伪装 Mac Chrome。
// Chrome 版本号对齐 playwright 自带 Chromium（1.61 → 149），升级 playwright 时同步改。
const USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36';

// 可选代理只能由接收方通过环境变量注入，分享包不带任何地址或凭证。
const DEFAULT_CLOAKBROWSER_PROXY = '';

export function getCloakBrowserProxy() {
  return process.env.PUBLISHING_KIT_CLOAKBROWSER_PROXY?.trim() || DEFAULT_CLOAKBROWSER_PROXY;
}

const activeBrowsers = new Set();
const blankContextBrowsers = new WeakMap();

function resolveBrowserEngine(engine = 'playwright') {
  if (engine === 'playwright' || engine === 'cloakbrowser') return engine;
  throw new Error(`不支持的浏览器引擎: ${engine}`);
}

function getBrowserLaunchOptions(engine, options) {
  if (engine !== 'cloakbrowser') return options;
  const {
    ignoreDefaultArgs: _ignoreDefaultArgs,
    args = [],
    ...cloakOptions
  } = options;
  const proxy = getCloakBrowserProxy();
  return {
    ...cloakOptions,
    // CloakBrowser 自带 C++ 层自动化信号处理；同时启用其行为模拟。
    humanize: true,
    args: args.filter(arg => arg !== '--disable-blink-features=AutomationControlled'),
    ...(proxy ? { proxy } : {}),
  };
}

function getBrowserContextOptions(engine, storageState) {
  return {
    storageState,
    viewport: VIEWPORT,
    // Playwright 路径保留现有 Mac UA；CloakBrowser 使用其二进制匹配的真实 UA，
    // 避免 Chromium 版本与显式 UA 版本不一致。
    ...(engine === 'playwright' ? { userAgent: USER_AGENT } : {}),
  };
}

async function launchManagedBrowser(options, requestedEngine = 'playwright') {
  const engine = resolveBrowserEngine(requestedEngine);
  const launchOptions = getBrowserLaunchOptions(engine, options);
  const browser = engine === 'cloakbrowser'
    ? await launchCloakBrowser(launchOptions)
    : await chromium.launch(launchOptions);
  activeBrowsers.add(browser);
  browser.once('disconnected', () => activeBrowsers.delete(browser));
  return browser;
}

async function closeWithTimeout(operation, label) {
  let timer;
  try {
    return await Promise.race([
      operation,
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} close timeout after ${CLOSE_TIMEOUT_MS}ms`)), CLOSE_TIMEOUT_MS);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

async function closeManagedBrowser(browser) {
  activeBrowsers.delete(browser);
  if (!browser || !browser.isConnected()) return;
  try {
    await closeWithTimeout(browser.close(), 'browser');
  } catch (error) {
    console.warn('[browser] 关闭 Chromium 失败:', error.message);
  }
}

export async function closeBrowserContext(context) {
  if (!context) return;
  try {
    await closeWithTimeout(context.close(), 'context');
  } catch (error) {
    console.warn('[browser] 关闭 context 失败:', error.message);
  }
}

/**
 * 用指定账号的登录态开临时 context 执行 fn(page, context)。
 * fn 正常返回后把最新 storageState 回写该账号；无论成败都关闭 context。
 */
export async function withAccountContext(accountId, fn, { signal } = {}) {
  signal?.throwIfAborted();
  const browser = await launchManagedBrowser(LAUNCH_OPTS);
  let context;
  let rejectAbort;
  const aborted = signal ? new Promise((_, reject) => { rejectAbort = reject; }) : null;
  const abort = () => {
    closeBrowserContext(context).catch(() => {});
    rejectAbort(signal?.reason || new Error('任务已取消'));
  };
  try {
    signal?.throwIfAborted();
    const storageState = getStorageState(accountId) || undefined;
    context = await browser.newContext(getBrowserContextOptions('playwright', storageState));
    signal?.addEventListener('abort', abort, { once: true });
    signal?.throwIfAborted();
    const page = await context.newPage();
    const work = fn(page, context);
    const result = signal ? await Promise.race([work, aborted]) : await work;
    try {
      signal?.throwIfAborted();
      refreshStorageState(accountId, await context.storageState({ indexedDB: true }));
    } catch (e) {
      if (!signal?.aborted) console.warn(`[browser] 回写账号 #${accountId} storageState 失败:`, e.message);
    }
    return result;
  } finally {
    signal?.removeEventListener('abort', abort);
    await closeBrowserContext(context);
    await closeManagedBrowser(browser);
  }
}

/** 使用指定账号登录态创建独立无头 context，供接口流程获取动态参数。 */
export async function withHeadlessAccountContext(accountId, fn, {
  signal,
  headless = true,
  persistStorageState = false,
  browserEngine = 'playwright',
} = {}) {
  signal?.throwIfAborted();
  const engine = resolveBrowserEngine(browserEngine);
  const browser = await launchManagedBrowser({ ...LAUNCH_OPTS, headless }, engine);
  let context;
  let rejectAbort;
  const aborted = signal ? new Promise((_, reject) => { rejectAbort = reject; }) : null;
  const abort = () => {
    closeBrowserContext(context).catch(() => {});
    rejectAbort(signal?.reason || new Error('任务已取消'));
  };
  try {
    signal?.throwIfAborted();
    const storageState = getStorageState(accountId) || undefined;
    context = await browser.newContext(getBrowserContextOptions(engine, storageState));
    signal?.addEventListener('abort', abort, { once: true });
    signal?.throwIfAborted();
    const page = await context.newPage();
    const work = fn(page, context);
    return signal ? await Promise.race([work, aborted]) : await work;
  } finally {
    signal?.removeEventListener('abort', abort);
    if (persistStorageState && context && !signal?.aborted) {
      try {
        refreshStorageState(accountId, await context.storageState({ indexedDB: true }));
      } catch (error) {
        console.warn(`[browser] 账号 #${accountId} storageState 回写失败:`, error.message);
      }
    }
    await closeBrowserContext(context);
    await closeManagedBrowser(browser);
  }
}

/** 无登录态的空白 context（扫码登录用）。必须通过 closeBlankContext 回收。 */
export async function createBlankContext() {
  const browser = await launchManagedBrowser(LAUNCH_OPTS);
  try {
    const context = await browser.newContext({ viewport: VIEWPORT, userAgent: USER_AGENT });
    blankContextBrowsers.set(context, browser);
    return context;
  } catch (error) {
    await closeManagedBrowser(browser);
    throw error;
  }
}

/** 等待空白 context 和其所属 browser 完整退出，避免异步 close 事件留下 Chromium 子进程。 */
export async function closeBlankContext(context) {
  const browser = blankContextBrowsers.get(context);
  blankContextBrowsers.delete(context);
  try {
    await closeBrowserContext(context);
  } finally {
    await closeManagedBrowser(browser);
  }
}

export async function closeAll() {
  await Promise.all([...activeBrowsers].map(browser => closeManagedBrowser(browser)));
}

let processClosePromise;
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, async () => {
    processClosePromise ||= closeAll();
    await processClosePromise;
    process.exit(0);
  });
}
