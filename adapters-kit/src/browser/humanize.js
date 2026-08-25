/**
 * 拟人化操作节奏 —— 避免机械式瞬间填充触发风控
 */
export const sleep = (ms) => new Promise(r => setTimeout(r, ms));

export const jitter = (base, spread = 0.5) =>
  Math.round(base * (1 - spread / 2 + Math.random() * spread));

/** 拟人化输入：点击聚焦后按键逐字输入（标题等短文本用；正文走富文本注入） */
export async function typeHuman(locator, text) {
  await locator.click();
  await sleep(jitter(300));
  await locator.pressSequentially(text, { delay: jitter(50, 1) });
  await sleep(jitter(300));

  // 远程 Chromium 偶尔会在逐字输入时吞掉一个中文字符（头条线上曾把
  // 「不爱喝水的…」写成「不爱喝的…」），随后按标题查作品会永远匹配不到。
  // 标题是短文本，输入后必须读回校验；不一致时用 fill 原子修正并再次确认。
  if (typeof locator.inputValue === 'function') {
    const actual = await locator.inputValue().catch(() => text);
    if (actual !== text) {
      console.warn(`[browser] 逐字输入校验不一致，已自动修正: ${actual} → ${text}`);
      await locator.fill(text);
      const repaired = await locator.inputValue().catch(() => text);
      if (repaired !== text) throw new Error(`输入框内容校验失败：期望「${text}」，实际「${repaired}」`);
    }
  }
}
