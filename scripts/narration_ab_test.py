#!/usr/bin/env py -3.11
"""口播稿 A/B 盲评脚本(对齐 dbs_p0_test 方法论): 同一材料×多配置 → 并排产物供盲评。

用法:
  py -3.11 scripts/narration_ab_test.py --material <file.txt> [--length 120]
      [--configs compose:faithful,translate:faithful] [--out data/tmp/narration_ab.md]
      [--repeat 2]

默认 configs = compose:faithful + translate:faithful（成稿 vs 翻译, 盲评谁更像真人）。
每个 config = llm_source:fidelity。产物不写库, 纯离线对比文件。
"""
import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from workbench.server import vstudio  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--material", required=True, help="材料文件路径(txt/md)")
    ap.add_argument("--length", type=int, default=120, help="片长档(秒)")
    ap.add_argument("--configs", default="compose:faithful,translate:faithful",
                    help="逗号分隔 llm_source:fidelity")
    ap.add_argument("--out", default="data/tmp/narration_ab.md")
    ap.add_argument("--repeat", type=int, default=1, help="每个 config 生成几遍(看稳定性)")
    args = ap.parse_args()

    material = Path(args.material).read_text(encoding="utf-8")
    configs = [c.split(":") for c in args.configs.split(",") if ":" in c]
    if not configs:
        print("configs 为空")
        return 1

    out = ["# 口播稿 A/B 盲评", "",
           f"- 材料: {args.material}（{len(material)} 字）",
           f"- 片长档: {args.length}s · 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
           f"- 配置: {', '.join('/'.join(c) for c in configs)} × {args.repeat} 遍",
           "", "**盲评建议**: 不看配置标签, 先按『像不像真人念的』排序, 再回来对答案。", ""]
    answer_key = []
    label_n = 0

    for source, fidelity in configs:
        for rep in range(1, args.repeat + 1):
            label_n += 1
            label = chr(ord("A") + label_n - 1)
            answer_key.append(f"- **{label}** = {source}/{fidelity} 第{rep}遍")
            print(f"[{label}] {source}/{fidelity} #{rep} 生成中…", flush=True)
            obj, code = vstudio.run_narration({
                "style_id": "", "length_s": args.length, "fidelity": fidelity,
                "ref_text": material, "brief": "", "llm_source": source})
            out += [f"## 候选 {label}", ""]
            if code != 0 or not isinstance(obj, dict):
                out += [f"> 生成失败: {obj.get('error') if isinstance(obj, dict) else code}", ""]
                continue
            out += [f"> 模型: {obj.get('llm_model')} · 字数 {obj.get('word_count')} · "
                    f"warnings: {obj.get('warnings') or '无'}", "",
                    obj.get("text", ""), ""]
            claims = obj.get("claims") or []
            if claims:
                out.append(f"> claims: {len(claims)} 条"
                           f"（高危 {sum(1 for c in claims if c.get('level') == 'high_risk')}）")
                out.append("")

    out += ["---", "", "## 答案（盲评完再看）", ""] + answer_key + [""]
    dest = REPO / args.out
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(chr(10).join(out), encoding="utf-8")
    print(f"产物: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
