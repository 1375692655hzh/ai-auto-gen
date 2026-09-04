#!/usr/bin/env python3
"""ai-auto-gen 统一 CLI 门面(P0)

用法:
  python cli.py doctor [--json]            环境体检(密钥/浏览器/队列/账本)
  python cli.py gen <args...>              生成模块(passthrough 到 ai-workflow/generator/main.py)
      例: gen morning / gen daily / gen run morning-paper --auto / gen fetch / gen llm-status
  python cli.py publish status [--json]    发布账本+待发队列(原生)
  python cli.py publish login [plat...]    一键登录(passthrough)
  python cli.py publish run [args...]      发全部平台(passthrough, 支持 --draft/--platforms/--file)
  python cli.py publish run-video <args..> 视频发布 B站/抖音(passthrough)
  python cli.py video build <id> [args..]  Remotion 出片(passthrough)

三板块布局(可单独下载):
  global-news-sources/  来源采集(注册表+fetchers+缓存健康)
  ai-workflow/          生成工作流(flows 引擎+generator+video)
  auto-publisher/       自动发布(autopub 浏览器引擎+adapters-kit+publish 门面)

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
GNS = ROOT / "global-news-sources"        # 板块一: 来源
AIWF = ROOT / "ai-workflow"               # 板块二: 工作流
PUB = ROOT / "auto-publisher"             # 板块三: 发布
WB = ROOT / "workbench"                   # 板块四: 前端工作台
AUTOPUB = PUB / "autopub"
EXIT_OK, EXIT_HUMAN, EXIT_FAIL, EXIT_CONFIG = 0, 2, 3, 4

# Windows 任务计划/重定向场景: stdout 回退 GBK 会导致 ⚠ 等符号崩进程(部署实录 2026-09-02)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


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
    # FastAPI(供数服务 sources serve 才需要)
    try:
        import fastapi, uvicorn  # noqa
        checks.append(_check("fastapi+uvicorn(供数服务)", True))
    except ImportError:
        checks.append(_check("fastapi+uvicorn(供数服务)", False,
                             "pip install fastapi uvicorn (仅 sources serve 需要)", warn=True))
    # Node(视频/API适配器用)
    try:
        v = subprocess.run(["node", "--version"], capture_output=True, text=True,
                           timeout=10).stdout.strip()
        checks.append(_check("node" + (f"({v})" if v else ""), bool(v),
                             "装 Node 20+ (仅视频/API发布需要)"))
    except Exception:
        checks.append(_check("node", False, "装 Node 20+ (仅视频/API发布需要)", warn=True))
    # ffprobe(Remotion 时长探测)
    ff = AIWF / "video" / "node_modules"
    ffprobe_ok = any(ff.glob("@remotion/compositor-*/ffprobe*"))
    checks.append(_check("ffprobe(remotion)", ffprobe_ok,
                         "cd ai-workflow/video && npm install", warn=True))
    # 中文字体
    fonts = [r"C:\Windows\Fonts\msyh.ttc", "/System/Library/Fonts/PingFang.ttc",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
             "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"]
    checks.append(_check("中文字体(长图渲染)", any(Path(f).exists() for f in fonts),
                         "config.yaml fonts: 段指定本机字体路径"))
    # LLM 密钥
    secret = AUTOPUB / "secret.local.json"
    has_key = secret.exists() or bool(os.environ.get("AUTOPUB_API_KEY"))
    checks.append(_check("LLM 密钥", has_key,
                         "python auto-publisher/autopub/webapp/app.py 网页里填, 或设 AUTOPUB_API_KEY"))
    # Chrome 调试口(CDP 发布模式)
    try:
        urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=2)
        checks.append(_check("Chrome 调试口(9222)", True))
    except Exception:
        checks.append(_check("Chrome 调试口(9222)", False,
                             "双击 auto-publisher/autopub/chrome_debug.bat 启动自动化 Chrome(发布前必须)",
                             warn=True))
    # 待发队列
    queue = AUTOPUB / "articles"
    n_queue = len(list(queue.glob("*.md")) + list(queue.glob("*.docx"))) if queue.exists() else 0
    checks.append(_check(f"待发队列({n_queue}篇)", True))
    # 发布账本
    state_f = AUTOPUB / "state.json"
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
    # 板块四: 工作台静态资源
    wb_ok = (WB / "web" / "index.html").exists() and \
            (WB / "web" / "vendor" / "vue.global.prod.js").exists()
    checks.append(_check("工作台静态资源(workbench)", wb_ok,
                         "workbench/web/ 不完整, 请重新拉取仓库", warn=True))
    # 供数服务探活(工作台资讯页依赖)
    try:
        urllib.request.urlopen("http://127.0.0.1:8787/v1/health", timeout=2)
        checks.append(_check("供数服务(8787)", True))
    except Exception:
        checks.append(_check("供数服务(8787)", False,
                             "另开终端: python cli.py sources serve (工作台资讯页依赖)", warn=True))

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
    state_f = AUTOPUB / "state.json"
    data = {}
    if state_f.exists():
        try:
            data = json.loads(state_f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"账本读取失败: {e}", file=sys.stderr)
            return EXIT_CONFIG
    queue = AUTOPUB / "articles"
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


def _cfg_local_path():
    """config.local.yaml 与 sources._cfg_section 同源: generator/config.yaml 同目录。"""
    p = ROOT / "ai-workflow" / "generator" / "config.yaml"
    if not p.exists():
        p = GNS / "config.yaml"
    return p.with_name("config.local.yaml")


def _yaml_set_enabled(text: str, sid: str, on: bool) -> str:
    """行级编辑 sources.<sid>.enabled, 保留注释与其他段——config.local.yaml 是用户手维护
    的模板(key 等), 不能整文件 safe_dump 重写(会丢注释)。原子写由调用方负责。"""
    import re as _re
    val = "true" if on else "false"
    lines = text.splitlines(keepends=True) if text else []
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    src_i = next((i for i, l in enumerate(lines)
                  if _re.match(r"^sources:\s*(#.*)?$", l.rstrip("\n"))), None)
    if src_i is None:                       # 无 sources 段: 文件尾新开一段
        if not text:
            lines.append("# 本机覆盖(gitignored, 不入库) — sources 启停由 cli.py sources enable 维护\n")
        elif lines and lines[-1] != "\n":
            lines.append("\n")
        lines += ["sources:\n", f"  {sid}:\n", f"    enabled: {val}\n"]
        return "".join(lines)
    j, sid_i = src_i + 1, None
    while j < len(lines):
        l = lines[j].rstrip("\n")
        if l.strip() and not l[0].isspace():
            break                           # 下一个顶层键: sources 段结束
        if _re.match(r"^  " + _re.escape(sid) + r":\s*(#.*)?$", l):
            sid_i = j
            break
        j += 1
    if sid_i is None:                       # 段内无该源: 紧跟 sources: 后插入
        lines.insert(src_i + 1, f"  {sid}:\n    enabled: {val}\n")
        return "".join(lines)
    k, en_i = sid_i + 1, None
    while k < len(lines):
        l = lines[k].rstrip("\n")
        if l.strip() and (not l[0].isspace() or len(l) - len(l.lstrip()) <= 2):
            break                           # 顶层键或 sources 下别的子键: sid 块结束
        if _re.match(r"^ {4}enabled:", l):
            en_i = k
            break
        k += 1
    if en_i is None:
        lines.insert(sid_i + 1, f"    enabled: {val}\n")
    else:
        lines[en_i] = _re.sub(r"(enabled:)\s*(true|false)?", rf"\1 {val}", lines[en_i])
    return "".join(lines)


def sources_enable_cmd(sid: str, state, as_json: bool) -> int:
    sys.path.insert(0, str(GNS))
    from sources import list_sources
    cur = next((m["enabled"] for m in list_sources() if m["id"] == sid), None)
    if cur is None:
        msg = f"未知来源: {sid}"
        print(json.dumps({"error": msg}, ensure_ascii=False)
              if as_json else msg, file=sys.stderr)
        return EXIT_CONFIG
    on = (state == "on") if state else (not cur)
    import tempfile
    loc = _cfg_local_path()
    new_text = _yaml_set_enabled(loc.read_text(encoding="utf-8") if loc.exists() else "",
                                 sid, on)
    loc.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(loc.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(new_text)
    os.replace(tmp, loc)
    now = next((m["enabled"] for m in list_sources() if m["id"] == sid), None)
    ok = (now == on)
    if as_json:
        print(json.dumps({"id": sid, "enabled": now, "ok": ok, "file": str(loc)},
                         ensure_ascii=False))
    else:
        mark = "✅" if ok else "❌"
        print(f"{mark} {sid} → {'启用' if now else '停用'} (config.local.yaml)")
    return EXIT_OK if ok else EXIT_FAIL


def sources_cmd(args) -> int:
    sys.path.insert(0, str(GNS))
    from sources import list_sources, fetch_one
    from sources import health as health_mod

    if args.sub == "list":
        def _csv(v):
            return [s.strip() for s in v.split(",") if s.strip()] if v else None
        srcs = list_sources(markets=_csv(getattr(args, "markets", None)),
                            channels=_csv(getattr(args, "channels", None)),
                            forms=_csv(getattr(args, "forms", None)))
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

    if args.sub == "gather":
        from sources import gather_by
        def _csv(v):
            return [s.strip() for s in v.split(",") if s.strip()] if v else None
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):     # fetcher 的 print 不污染 --json 输出
            items, failed = gather_by(markets=_csv(args.markets), kinds=_csv(args.kinds),
                                      channels=_csv(args.channels), forms=_csv(args.forms),
                                      source_ids=_csv(args.ids), limit=args.limit,
                                      fresh=args.fresh)
        if args.json:
            print(json.dumps({"items": items, "failed": failed}, ensure_ascii=False, indent=2))
        else:
            for it in items[:50]:
                print(f"[{it.get('time','')}] {it.get('source','')} {it.get('text','')[:70]}")
            print(f"(共 {len(items)} 条; 失败/空 {len(failed)} 源)")
            for f in failed:
                print(f"  ⚠ {f}")
        return EXIT_OK if items else EXIT_FAIL

    if args.sub == "refresh":
        from sources import refresh as refresh_mod
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):     # fetcher 的 print 不污染 --json 输出
            rep = refresh_mod.run(dry_run=args.dry_run)
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
        else:
            print(f"本轮: 计划 {rep.get('planned',0)} 源 / 成功 {rep.get('ok',0)} / "
                  f"空 {rep.get('empty',0)} / 失败 {rep.get('failed',0)} / "
                  f"跳过 {rep.get('skipped',0)} | 入库 {rep.get('stored',0)} 条 | "
                  f"耗时 {rep.get('elapsed_s',0)}s")
            for f in rep.get("failures", [])[:20]:
                print(f"  ⚠ {f}")
        return EXIT_OK if rep.get("ok") or rep.get("empty") else EXIT_FAIL

    if args.sub == "serve":
        from sources import serve
        return serve.run(host=args.bind or args.host, port=args.port)
    if args.sub == "console":
        from sources.console import run
        return run(host=args.bind or args.host, port=args.port)
    if args.sub == "enable":
        return sources_enable_cmd(args.sid, args.state, args.json)
    return EXIT_FAIL


def workbench_cmd(args) -> int:
    if args.sub == "refresh-x-surge":
        sys.path.insert(0, str(WB))
        from server import x_surge
        hours = 48 if (args.range == "48h") else 24
        rep = x_surge.collect(range_h=hours, limit=args.limit, force=args.force)
        x_surge.fetch_rss()                         # SoPilot 热帖(蹭蹭流量页数据源)
        return 0 if not rep.get("circuit_break") else 3
    if args.sub == "refresh-yt-track":
        sys.path.insert(0, str(WB))
        from server import yt_track
        _, code = yt_track.collect(force=args.force)   # 0 正常/跳过, 3 配额熔断, 4 无 key
        return code
    if args.sub == "enrich-x-profiles":
        sys.path.insert(0, str(WB))
        from server import x_profile_enricher
        return x_profile_enricher.run_cli(args)
    if args.sub == "serve":
        sys.path.insert(0, str(WB))
        from server import app as wb_app
        return wb_app.run(host=args.bind or args.host, port=args.port,
                          open_browser=getattr(args, "open", False))
    if args.sub == "status":
        sys.path.insert(0, str(WB))
        from server import config as wb_config
        cfg = wb_config.load()
        src = cfg["source"]
        result = {"workbench_static": (WB / "web" / "index.html").exists(),
                  "source": {"mode": src["mode"], "base_url": src["base_url"],
                             "has_key": bool(src.get("api_key"))},
                  "source_reachable": False}
        try:
            req = urllib.request.Request(src["base_url"].rstrip("/") + "/v1/health",
                                         headers={"Authorization": f"Bearer {src['api_key']}"}
                                         if src.get("api_key") else {})
            urllib.request.urlopen(req, timeout=3)
            result["source_reachable"] = True
        except Exception:
            pass
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"工作台静态资源: {'✅' if result['workbench_static'] else '❌'}")
            print(f"数据源({src['mode']}): {src['base_url']} "
                  f"{'🔑' if result['source']['has_key'] else '(免密/未配 Key)'} "
                  f"{'✅ 可达' if result['source_reachable'] else '❌ 不可达'}")
            if not result["source_reachable"]:
                print("  → 本机场景请另开终端: python cli.py sources serve")
        return EXIT_OK if result["source_reachable"] else EXIT_FAIL
    return EXIT_FAIL


def flows_cmd(args) -> int:
    sys.path.insert(0, str(AIWF))
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
    ps_l = ssub.add_parser("list", help="全部来源+启用/健康状态(可按标签过滤)")
    ps_l.add_argument("--markets", default=None, help="市场过滤, 逗号分隔(如 美股,台湾)")
    ps_l.add_argument("--channels", default=None, help="渠道过滤, 逗号分隔")
    ps_l.add_argument("--forms", default=None, help="形态过滤, 逗号分隔")
    ps_l.add_argument("--json", action="store_true")
    ps_c = ssub.add_parser("check", help="实抓体检(更新健康标记, dead 自动跳过可复位)")
    ps_c.add_argument("--id", default=None, help="只查指定来源")
    ps_c.add_argument("--json", action="store_true")
    ps_f = ssub.add_parser("fetch", help="抓取指定来源(TTL 缓存)")
    ps_f.add_argument("sid", help="来源 id (list 可查)")
    ps_f.add_argument("--limit", type=int, default=5)
    ps_f.add_argument("--fresh", action="store_true", help="绕过缓存")
    ps_f.add_argument("--json", action="store_true")
    ps_g = ssub.add_parser("gather", help="按标签聚合抓取(通用版, TTL 缓存)")
    ps_g.add_argument("--markets", default=None, help="市场过滤, 逗号分隔")
    ps_g.add_argument("--kinds", default=None, help="kind 过滤(flash/peer_article/...)")
    ps_g.add_argument("--channels", default=None, help="渠道过滤")
    ps_g.add_argument("--forms", default=None, help="形态过滤")
    ps_g.add_argument("--ids", default=None, help="只要这些源, 逗号分隔")
    ps_g.add_argument("--limit", type=int, default=0, help="条目上限(0=不限)")
    ps_g.add_argument("--fresh", action="store_true", help="绕过缓存")
    ps_g.add_argument("--json", action="store_true")
    ps_rf = ssub.add_parser("refresh", help="到期源调度刷新并写入服务库(对外供数的写侧)")
    ps_rf.add_argument("--interval", type=int, default=30, help="调度周期分钟(仅标记, 由任务计划触发)")
    ps_rf.add_argument("--dry-run", action="store_true", help="只输出本轮计划, 不真抓")
    ps_rf.add_argument("--json", action="store_true")
    ps_sv = ssub.add_parser("serve", help="只读 HTTP 供数服务(默认 127.0.0.1)")
    ps_sv.add_argument("--host", default="127.0.0.1")
    ps_sv.add_argument("--port", type=int, default=8787)
    ps_sv.add_argument("--bind", default=None, help="显式绑定地址(如 0.0.0.0, 覆盖 --host)")
    ps_co = ssub.add_parser("console", help="数据站运维控制台(默认 127.0.0.1:8786)")
    ps_co.add_argument("--host", default="127.0.0.1")
    ps_co.add_argument("--port", type=int, default=8786)
    ps_co.add_argument("--bind", default=None, help="显式绑定地址(如 0.0.0.0, 覆盖 --host)")
    ps_en = ssub.add_parser("enable", help="启用/停用来源(行级写 config.local.yaml 覆盖, 不动库文件)")
    ps_en.add_argument("sid", help="来源 id(list 可查)")
    ps_en.add_argument("state", nargs="?", choices=["on", "off"], default=None,
                       help="on/off, 缺省=翻转当前状态")
    ps_en.add_argument("--json", action="store_true")

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

    p_wb = sub.add_parser("workbench", help="前端工作台(板块四)")
    wsub = p_wb.add_subparsers(dest="sub", required=True)
    pw_s = wsub.add_parser("serve", help="启动工作台(默认 127.0.0.1:8788)")
    pw_s.add_argument("--host", default="127.0.0.1")
    pw_s.add_argument("--port", type=int, default=8788)
    pw_s.add_argument("--bind", default=None, help="显式绑定地址(如 0.0.0.0, 覆盖 --host)")
    pw_s.add_argument("--open", action="store_true", help="启动后自动开浏览器")
    pw_t = wsub.add_parser("status", help="工作台/数据源双探活+设置有效性")
    pw_t.add_argument("--json", action="store_true")
    pw_e = wsub.add_parser("enrich-x-profiles",
                           help="X账号公开档案增强(grok x-search → data/workbench/x_profiles.json)")
    pw_e.add_argument("--limit", type=int, default=0, help="只补前 N 个缺档账号(0=全部缺档)")
    pw_e.add_argument("--force", action="store_true", help="忽略已有缓存全部重抓")
    pw_e.add_argument("--handles", default="", help="只抓指定账号(逗号分隔, 可带@)")
    pw_e.add_argument("--provider", default="grok-cli", help="档案来源(暂仅 grok-cli)")
    pw_e.add_argument("--json", action="store_true")
    pw_s = wsub.add_parser("refresh-x-surge",
                           help="X起爆帖互动采集(FxTwitter四件套 → data/workbench/x_engagement.json 时序快照)")
    pw_s.add_argument("--range", default="24h", choices=["24h", "48h"], help="回看窗口")
    pw_s.add_argument("--limit", type=int, default=300, help="单轮最多采集帖数")
    pw_s.add_argument("--force", action="store_true", help="忽略20分钟采集冷却全部重抓")
    pw_y = wsub.add_parser("refresh-yt-track",
                           help="YouTube热点追踪采集(Data API v3 → data/workbench/yt_channels.json + yt_videos.json 快照)")
    pw_y.add_argument("--force", action="store_true",
                      help="忽略5分钟采集冷却与重入锁全部重抓")
    pw_y.add_argument("--json", action="store_true", help="报告本就是单行 JSON, 此参数仅为习惯兼容")

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
    if args.cmd == "workbench":
        return workbench_cmd(args)
    if args.cmd == "flows":
        return flows_cmd(args)
    if args.cmd == "gen":
        return _passthrough(AIWF / "generator" / "main.py", args.args)
    if args.cmd == "publish":
        if args.sub == "status":
            return publish_status(json_out=args.json)
        if args.sub == "targets":
            sys.path.insert(0, str(PUB))
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
            return _passthrough(AUTOPUB / "login.py", args.args)
        if args.sub == "run":
            return _passthrough(AUTOPUB / "publish_all.py", args.args)
        if args.sub == "run-video":
            return _passthrough(AUTOPUB / "publish_video.py", args.args)
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
                               cwd=str(AIWF / "video"))
            return r.returncode
    ap.print_help()
    return EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
