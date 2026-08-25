/**
 * adapter 通用小工具：候选选择器逐个尝试
 */

/** 在 page/frame 上按候选顺序找第一个可见元素，找不到返回 null */
export async function firstVisible(scope, candidates, { timeoutMs = 5000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const selector of candidates) {
      const locator = scope.locator(selector).first();
      try {
        if (await locator.isVisible()) return { locator, selector };
      } catch { /* selector 语法或上下文问题，试下一个 */ }
    }
    await new Promise(r => setTimeout(r, 300));
  }
  return null;
}

/** 必须命中，否则抛错（错误里带上候选列表便于校准 selectors.js） */
export async function mustFind(scope, candidates, label, opts) {
  const hit = await firstVisible(scope, candidates, opts);
  if (!hit) throw new Error(`未找到「${label}」元素，候选: ${candidates.join(' | ')}（请校准 selectors.js）`);
  return hit;
}
