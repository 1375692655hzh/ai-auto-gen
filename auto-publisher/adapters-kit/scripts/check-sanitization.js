import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ignored = new Set(['node_modules', '.git']);
const findings = [];
const checks = [
  ['带用户名密码的 URL', /\b[a-z][a-z0-9+.-]*:\/\/[^\s/:@]+:[^\s/@]+@/gi],
  ['疑似真实手机号', /(?<!\d)1[3-9]\d{9}(?!\d)/g],
  ['疑似真实邮箱', /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi],
  ['固定敏感配置', /HARD_CODED_(?:TOKEN|SECRET|PASSWORD|APPKEY|API_KEY)/g],
  ['Cookie 赋值样例', /(?:Cookie|Authorization)\s*[:=]\s*['"][^'"]{12,}['"]/gi],
];

async function walk(directory) {
  for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
    if (ignored.has(entry.name)) continue;
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) await walk(target);
    else if (!/\.(?:js|json|md|example|txt)$/.test(entry.name)) continue;
    else {
      const content = await fs.readFile(target, 'utf8');
      for (const [label, pattern] of checks) {
        pattern.lastIndex = 0;
        if (pattern.test(content)) findings.push(`${path.relative(ROOT, target)}: ${label}`);
      }
    }
  }
}

await walk(ROOT);
if (findings.length) {
  console.error(findings.join('\n'));
  process.exitCode = 1;
} else {
  console.log('脱敏检查通过：未发现凭证 URL、手机号、邮箱、固定敏感配置或 Cookie 样例。');
}
