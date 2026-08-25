"""文章生成模块 CLI 入口。

用法(在仓库根目录):
  python generator/main.py morning                  # A股+港美股两篇早报(各带口播稿)
  python generator/main.py morning --market a       # 只生成 A股早报
  python generator/main.py analysis                 # 交互式四步流程(自动选题)
  python generator/main.py analysis --topic "AI芯片"  # 指定主题,其余步骤仍交互确认
  python generator/main.py analysis --topic "..." --yes   # 全自动(选题用第一个候选,大纲不再确认)
  python generator/main.py fetch [--limit 10]       # 看看信息源能抓到什么(不需要模型)
  python generator/main.py llm-status               # 查看模型配置状态
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="AI 文章生成:早报 / 分析文章")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_m = sub.add_parser("morning", help="生成早报(A股/港美股,含口播稿)")
    p_m.add_argument("--market", choices=["a", "us", "both"], default="both")

    p_a = sub.add_parser("analysis", help="分析文章四步流程")
    p_a.add_argument("--topic", default=None, help="直接指定主题(跳过自动选题)")
    p_a.add_argument("--yes", action="store_true", help="全自动,不逐步确认")

    p_f = sub.add_parser("fetch", help="抓取信息源并展示(不调用模型)")
    p_f.add_argument("--limit", type=int, default=10)

    sub.add_parser("llm-status", help="查看模型配置状态")

    args = ap.parse_args()

    if args.cmd == "morning":
        import morning
        morning.run(args.market)
    elif args.cmd == "analysis":
        import analysis
        analysis.run(topic=args.topic, auto=args.yes)
    elif args.cmd == "fetch":
        import sources
        items, failed = sources.gather()
        if failed:
            print(f"⚠ 不可用的来源: {', '.join(failed)}")
        print(f"共抓到 {len(items)} 条,展示最新 {args.limit} 条:\n")
        for it in items[: args.limit]:
            print(f"[{it['time']}]({it['source']}) {it['text'][:100]}")
    elif args.cmd == "llm-status":
        st = common.llm_status()
        print(f"已配置: {'是' if st['configured'] else '否'}")
        print(f"provider: {st['provider'] or '(未设置)'}")
        print(f"model:    {st['model'] or '(未设置)'}")
        print(f"base_url: {st['base_url'] or '(默认)'}")
        print(f"api_key:  {st['api_key_masked'] or '(空)'}")
        if not st["configured"]:
            print("\n配置方法见 generator/README.md")


if __name__ == "__main__":
    main()
