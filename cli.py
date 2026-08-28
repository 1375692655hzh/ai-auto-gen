#!/usr/bin/env python3
"""ai-auto-gen 统一 CLI 门面(P0)

用法:
  python cli.py doctor [--json]            环境体检(密钥/浏览器/队列/账本)
  python cli.py gen <args...>              生成模块(passthrough 到 generator/main.py)
      例: gen morning / gen daily / gen run morning-paper --auto / gen fetch / gen llm-status
  python cli.py publish status [--json]    发布账本+待发队列(原生)
  python cli.py publish login [plat...]    一键登录(passthrough)
  python cli.py publish run [args...]      发全部平台(passthrough, 支持 --draft/--platforms/--file)
  python cli.py publish run-video <args..> 视频发布 B站/抖音(passthrough)
  python cli.py video build <id> [args..]  Remotion 出片(passthrough)

退出码约定(agent 靠此决策):
  0 成功 | 2 需人工介入(登录/审核/验证码) | 3 业务失败 | 4 配置缺失
P0 阶段 passthrough 命令透传子进程退出码; sources/flows 原生命令在 P1/P2 交付。
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXIT_OK, EXIT_HUMAN, EXIT_FAIL, EXIT_CONFIG = 0, 2, 3, 4


def _passthrough(script: Path, args: list, cwd: Path = ROOT) -> int:
    """转发到子脚本, 透传退出码。"""
    cmd = [sys.executable, str(script)] + args
    r = subprocess.run(cmd, cwd=str(cwd))
    return r.returncode


# ---------- doctor: 环境体检 ----------

def _check(name, ok, hint="", warn=False):
    # ok 即通过; warn=True 表示"失败也只算警告不算 fail"
    return {"item": name, "status": ("ok" if ok else ("warn" if warn else "fail")),
            "hint": hint if not ok else ""}


def doctor(json_out: bool = False) -> int:
    checks = []

    # Python
    checks.append(_check("python>=3.10", sys.version_info >= (3, 10),
                         f"当前 {sys.version.split()[0]}, 请装 3.10+"))
    # Playwright
    try:
        import playwright  # noqa
        checks.append(_check("playwright", True))
    except ImportError:
        checks.append(_check("playwright", False, "pip install playwright && playwright install chromium"))
    # Node(视频/API适配器用)
    try:
        v = subprocess.run(["node", "--version"], capture_output=True, text=True,
                           timeout=10).stdout.strip()
        checks.append(_check("node" + (f"({v})" if v else ""), bool(v),
                             "装 Node 20+ (仅视频/API发布需要)"))
    except Exception:
        checks.append(_check("node", False, "装 Node 20+ (仅视频/API发布需要)", warn=True))
    # ffprobe(Remotion 时长探测)
    ff = ROOT / "video" / "node_modules"
    ffprobe_ok = any(ff.glob("@remotion/compositor-*/ffprobe*"))
    checks.append(_check("ffprobe(remotion)", ffprobe_ok,
                         "cd video && npm install", warn=True))
    # 中文字体
    fonts = [r"C:\Windows\Fonts\msyh.ttc", "/System/Library/Fonts/PingFang.ttc",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
             "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"]
    checks.append(_check("中文字体(长图渲染)", any(Path(f).exists() for f in fonts),
                         "config.yaml fonts: 段指定本机字体路径"))
    # LLM 密钥
    secret = ROOT / "autopub" / "secret.local.json"
    has_key = secret.exists() or bool(os.environ.get("AUTOPUB_API_KEY"))
    checks.append(_check("LLM 密钥", has_key,
                         "python autopub/webapp/app.py 网页里填, 或设 AUTOPUB_API_KEY"))
    # Chrome 调试口(CDP 发布模式)
    try:
        urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=2)
        checks.append(_check("Chrome 调试口(9222)", True))
    except Exception:
        checks.append(_check("Chrome 调试口(9222)", False,
                             "双击 autopub/chrome_debug.bat 启动自动化 Chrome(发布前必须)",
                             warn=True))
    # 待发队列
    queue = ROOT / "autopub" / "articles"
    n_queue = len(list(queue.glob("*.md")) + list(queue.glob("*.docx"))) if queue.exists() else 0
    checks.append(_check(f"待发队列({n_queue}篇)", True))
    # 发布账本
    state_f = ROOT / "autopub" / "state.json"
    n_pub = 0
    if state_f.exists():
        try:
            n_pub = len(json.loads(state_f.read_text(encoding="utf-8")))
        except Exception:
            pass
    checks.append(_check(f"发布账本({n_pub}篇已记录)", state_f.exists()))
    # 运行时数据根
    (ROOT / "data").mkdir(exist_ok=True)
    checks.append(_check("data/ 可写", os.access(ROOT / "data", os.W_OK)))

    if json_out:
        fails = [c for c in checks if c["status"] == "fail"]
        print(json.dumps({"overall": "fail" if fails else "ok", "checks": checks},
                         ensure_ascii=False, indent=2))
        return EXIT_FAIL if fails else EXIT_OK
    icons = {"ok": "✅", "warn": "⚠️ ", "fail": "❌"}
    print("== ai-auto-gen 环境体检 ==")
    for c in checks:
        print(f"{icons[c['status']]} {c['item']}" + (f"  → {c['hint']}" if c["hint"] else ""))
    n_fail = sum(1 for c in checks if c["status"] == "fail")
    print(f"\n{'❌' if n_fail else '✅'} {n_fail} 项失败" +
          ("(fail 必须修复; warn 按需)" if n_fail else ""))
    return EXIT_FAIL if n_fail else EXIT_OK


# ---------- publish status: 原生读账本 ----------

def publish_status(json_out: bool = False) -> int:
    state_f = ROOT / "autopub" / "state.json"
    data = {}
    if state_f.exists():
        try:
            data = json.loads(state_f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"账本读取失败: {e}", file=sys.stderr)
            return EXIT_CONFIG
    queue = ROOT / "autopub" / "articles"
    files = sorted([f.name for f in queue.glob("*") if f.suffix in (".md", ".docx")]
                   ) if queue.exists() else []
    if json_out:
        print(json.dumps({"ledger": data, "queue": files}, ensure_ascii=False, indent=2))
        return EXIT_OK
    print("== 待发队列 ==")
    print("\n".join(files) or "(空)")
    print("\n== 发布账本(最近) ==")
    rows = []
    for aid, plats in data.items():
        for p, rec in plats.items():
            rows.append((rec.get("time", ""), aid, p, rec.get("status"), rec.get("url", "")))
    for t, aid, p, st, url in sorted(rows, reverse=True)[:20]:
        print(f"{t} [{p}] {st:10s} {aid[:40]} {url[:50]}")
    if not rows:
        print("(无记录)")
    return EXIT_OK


def sources_cmd(args) -> int:
    sys.path.insert(0, str(ROOT))
    from sources import list_sources, fetch_one
    from sources import health as health_mod

    if args.sub == "list":
        srcs = list_sources()
        if args.json:
            print(json.dumps(srcs, ensure_ascii=False, indent=2))
            return EXIT_OK
        print(f"{'类型':<14}{'来源id':<22}{'启用':<6}{'健康':<10}标题")
        for m in srcs:
            print(f"{m['kind']:<14}{m['id']:<22}{('是' if m['enabled'] else '否'):<6}"
                  f"{m['health']:<10}{m['title']}")
        return EXIT_OK

    if args.sub == "check":
        srcs = [m for m in list_sources() if not args.id or m["id"] == args.id]
        if args.id and not srcs:
            print(f"未知来源: {args.id}", file=sys.stderr)
            return EXIT_CONFIG
        results = []
        for m in srcs:
            items, err = fetch_one(m["id"], fresh=True)
            n = len(items) if isinstance(items, list) else 1
            ok = not err and n > 0
            results.append({"id": m["id"], "ok": ok, "items": n,
                            "error": err or ("空结果" if n == 0 else ""),
                            "health": health_mod.get(m["id"]).get("status", "")})
            mark = "✅" if ok else "❌"
            print(f"{mark} {m['id']:<22} {n}条 {err or ('空结果' if n == 0 else '')}")
        n_fail = sum(1 for r in results if not r["ok"])
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        return EXIT_FAIL if n_fail else EXIT_OK

    if args.sub == "fetch":
        items, err = fetch_one(args.sid, fresh=args.fresh)
        if err:
            print(json.dumps({"error": err}, ensure_ascii=False)
                  if args.json else f"❌ {err}", file=sys.stderr if not args.json else sys.stdout)
            return EXIT_FAIL
        if isinstance(items, dict):
            items = [items]
        shown = items[:args.limit]
        if args.json:
            print(json.dumps(shown, ensure_ascii=False, indent=2))
        else:
            for it in shown:
                t = it.get("time", "")
                body = (it.get("title") or it.get("event") or it.get("text", ""))[:70]
                extra = it.get("country") or it.get("media") or ""
                print(f"[{t}] {extra + ' ' if extra else ''}{body}")
            print(f"(共 {len(items)} 条, 显示 {len(shown)})")
        return EXIT_OK
    return EXIT_FAIL


def flows_cmd(args) -> int:
    sys.path.insert(0, str(ROOT))
    from flows.engine import discover, lint, run_flow, YamlWorkflow, RUNS_ROOT

    if args.sub == "list":
        packs = discover()
        rows = []
        for name, d in packs.items():
            errs = lint(d)
            rows.append({"name": name, "title": (YamlWorkflow(d).title if not errs else "?"),
                         "path": str(d), "lint": "ok" if not errs else errs})
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return EXIT_OK
        for r in rows:
            mark = "✅" if r["lint"] == "ok" else "❌"
            print(f"{mark} {r['name']:<20} {r['title']}")
            if r["lint"] != "ok":
                for e in r["lint"]:
                    print(f"    - {e}")
        return EXIT_OK

    if args.sub == "lint":
        packs = discover()
        if args.name not in packs:
            print(f"未知工作流: {args.name} (可用: {sorted(packs)})", file=sys.stderr)
            return EXIT_CONFIG
        errs = lint(packs[args.name])
        print("|".join(errs) if errs else "lint 通过")
        return EXIT_FAIL if errs else EXIT_OK

    if args.sub in ("run", "resume"):
        overrides = {}
        for kv in args.set:
            k, _, v = kv.partition("=")
            if not k or not v:
                print(f"--set 格式应为 k=v: {kv}", file=sys.stderr)
                return EXIT_CONFIG
            if v.lower() in ("true", "false"):
                v = v.lower() == "true"
            else:
                try:
                    v = int(v)
                except ValueError:
                    pass
            overrides[k] = v
        try:
            run_flow(args.name, date=args.date, auto=args.auto,
                     from_step=args.from_step, fresh=args.fresh,
                     only=args.only, overrides=overrides)
        except SystemExit as e:
            return int(e.code) if isinstance(e.code, int) else EXIT_FAIL
        return EXIT_OK

    if args.sub == "export":
        from flows.engine import export_flow
        try:
            export_flow(args.name, args.out or f"{args.name}.zip")
            return EXIT_OK
        except SystemExit as e:
            print(e, file=sys.stderr)
            return EXIT_CONFIG

    if args.sub == "import":
        from flows.engine import import_flow
        try:
            import_flow(args.zip_path, rename=args.rename)
            return EXIT_OK
        except SystemExit as e:
            print(e, file=sys.stderr)
            return EXIT_FAIL

    if args.sub == "new":
        from flows.engine import new_flow
        try:
            new_flow(args.from_name, args.new_name)
            return EXIT_OK
        except SystemExit as e:
            print(e, file=sys.stderr)
            return EXIT_CONFIG

    if args.sub == "status":
        import json as _j
        date = args.date
        if not date:
            packs = discover()
            if args.name not in packs:
                print(f"未知工作流: {args.name}", file=sys.stderr)
                return EXIT_CONFIG
            droot = RUNS_ROOT / args.name
            dates = sorted([p.name for p in droot.glob("*") if p.is_dir()]) if droot.exists() else []
            date = dates[-1] if dates else None
        rj = RUNS_ROOT / args.name / str(date) / "run.json"
        if not rj.exists():
            print(f"无运行记录: {rj}", file=sys.stderr)
            return EXIT_CONFIG
        data = _j.loads(rj.read_text(encoding="utf-8"))
        if args.json:
            print(_j.dumps(data, ensure_ascii=False, indent=2))
            return EXIT_OK
        print(f"工作流 {data['flow']} @ {data['date']}  状态: {data['status']}"
              + (f"  ({data['note']})" if data.get("note") else ""))
        for k, v in data.get("steps", {}).items():
            print(f"  · {k:<12} {v}")
        for k, v in (data.get("artifacts") or {}).items():
            print(f"  📄 {k}: {v}")
        return EXIT_OK
    return EXIT_FAIL


def main() -> int:
    ap = argparse.ArgumentParser(description="ai-auto-gen 统一 CLI",
                                 prog="cli.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_d = sub.add_parser("doctor", help="环境体检")
    p_d.add_argument("--json", action="store_true")

    p_s = sub.add_parser("publish", help="发布板块")
    psub = p_s.add_subparsers(dest="sub", required=True)
    ps_st = psub.add_parser("status", help="账本+队列")
    ps_st.add_argument("--json", action="store_true")
    psub.add_parser("targets", help="平台矩阵(14平台×引擎×验证状态)")
    for name, help_ in [("login", "一键登录(可带平台名)"),
                         ("run", "发全部平台(--draft --platforms --file 等透传)"),
                         ("run-video", "视频发布(publish_video 参数透传)")]:
        p_x = psub.add_parser(name, help=help_)
        p_x.add_argument("args", nargs=argparse.REMAINDER)

    p_src = sub.add_parser("sources", help="来源库(板块一)")
    ssub = p_src.add_subparsers(dest="sub", required=True)
    ps_l = ssub.add_parser("list", help="全部来源+启用/健康状态")
    ps_l.add_argument("--json", action="store_true")
    ps_c = ssub.add_parser("check", help="实抓体检(更新健康标记, dead 自动跳过可复位)")
    ps_c.add_argument("--id", default=None, help="只查指定来源")
    ps_c.add_argument("--json", action="store_true")
    ps_f = ssub.add_parser("fetch", help="抓取指定来源(TTL 缓存)")
    ps_f.add_argument("sid", help="来源 id (list 可查)")
    ps_f.add_argument("--limit", type=int, default=5)
    ps_f.add_argument("--fresh", action="store_true", help="绕过缓存")
    ps_f.add_argument("--json", action="store_true")

    p_fl = sub.add_parser("flows", help="生成工作流(板块二)")
    fsub = p_fl.add_subparsers(dest="sub", required=True)
    pf_l = fsub.add_parser("list", help="全部工作流包")
    pf_l.add_argument("--json", action="store_true")
    pf_i = fsub.add_parser("lint", help="校验 workflow.yaml")
    pf_i.add_argument("name")
    pf_r = fsub.add_parser("run", help="运行工作流(断点续跑, 幂等)")
    for a, kw in [("--date", {"default": None}), ("--auto", {"action": "store_true"}),
                  ("--from", {"dest": "from_step", "default": None}),
                  ("--only", {"default": None}),
                  ("--fresh", {"action": "store_true"})]:
        pf_r.add_argument(a, **kw)
    pf_r.add_argument("--set", action="append", default=[], metavar="k=v", help="覆盖参数(可多次)")
    pf_r.add_argument("name", help="工作流名(flows list 可查)")
    pf_e = fsub.add_parser("export", help="导出工作流包为 zip(分享给同事)")
    pf_e.add_argument("name")
    pf_e.add_argument("-o", "--out", default=None, help="输出 zip 路径(默认 <名>.zip)")
    pf_x = fsub.add_parser("import", help="导入工作流包 zip")
    pf_x.add_argument("zip_path")
    pf_x.add_argument("--rename", default=None, help="安装为指定包名")
    pf_n = fsub.add_parser("new", help="复制现有包为自定义起点")
    pf_n.add_argument("new_name")
    pf_n.add_argument("--from", dest="from_name", default="morning-paper")
    pf_s = fsub.add_parser("status", help="运行状态(读 run.json)")
    pf_s.add_argument("name")
    pf_s.add_argument("--date", default=None)
    pf_s.add_argument("--json", action="store_true")
    fsub.add_parser("resume", help="= run(存档复用自动续跑)").add_argument("name")  # 兼容占位

    p_g = sub.add_parser("gen", help="生成模块(generator/main.py 参数透传)")
    p_g.add_argument("args", nargs=argparse.REMAINDER)

    p_k = sub.add_parser("skills", help="把 skills/ 安装到本机 agent 技能目录")
    ksub = p_k.add_subparsers(dest="sub", required=True)
    ksub.add_parser("install", help="复制到 ~/.agents/skills 与 ~/.claude/skills(存在才装)")
    ksub.add_parser("list", help="查看项目内技能")

    p_v = sub.add_parser("video", help="视频模块")
    vsub = p_v.add_subparsers(dest="sub", required=True)
    pv_b = vsub.add_parser("build", help="Remotion 出片")
    pv_b.add_argument("args", nargs=argparse.REMAINDER)
    vsub.add_parser("new", help="新建视频项目(转 generator video)")

    args = ap.parse_args()

    if args.cmd == "doctor":
        return doctor(json_out=args.json)
    if args.cmd == "sources":
        return sources_cmd(args)
    if args.cmd == "flows":
        return flows_cmd(args)
    if args.cmd == "gen":
        return _passthrough(ROOT / "generator" / "main.py", args.args)
    if args.cmd == "publish":
        if args.sub == "status":
            return publish_status(json_out=args.json)
        if args.sub == "targets":
            sys.path.insert(0, str(ROOT))
            from publish.facade import platform_status
            rows = platform_status()
            icons = {"published": "✅已真发", "draft": "🟡draft验证", "disabled-需实名": "⛔需实名",
                     "disabled-风控": "⛔风控", "placeholder": "⚪占位", "learning-only": "📘学习包"}
            for r in rows:
                en = "启用" if r["enabled"] else "停用"
                print(f"{r['engine']:<8} {r['id']:<12} {r['title']:<8} {en}  "
                      f"{icons.get(r['verified'], r['verified'])}")
            return EXIT_OK
        if args.sub == "login":
            return _passthrough(ROOT / "autopub" / "login.py", args.args)
        if args.sub == "run":
            return _passthrough(ROOT / "autopub" / "publish_all.py", args.args)
        if args.sub == "run-video":
            return _passthrough(ROOT / "autopub" / "publish_video.py", args.args)
    if args.cmd == "skills":
        import shutil
        src = ROOT / "skills"
        if args.sub == "list":
            for d in sorted(src.iterdir()):
                if (d / "SKILL.md").exists():
                    print(f"· {d.name}")
            return EXIT_OK
        if args.sub == "install":
            installed = []
            for dest in (Path.home() / ".agents" / "skills", Path.home() / ".claude" / "skills"):
                if dest.exists():
                    for d in src.iterdir():
                        if (d / "SKILL.md").exists():
                            tgt = dest / d.name
                            shutil.copytree(d, tgt, dirs_exist_ok=True)
                            installed.append(str(tgt))
            print("已安装:" if installed else "未找到 agent 技能目录(手动复制 skills/ 即可):")
            for p_ in installed or [str(src)]:
                print(f"  {p_}")
            return EXIT_OK
        return EXIT_FAIL

    if args.cmd == "video":
        if args.sub == "build":
            r = subprocess.run(["node", "scripts/build.mjs"] + args.args,
                               cwd=str(ROOT / "video"))
            return r.returncode
    ap.print_help()
    return EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
