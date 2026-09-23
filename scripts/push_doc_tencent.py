#!/usr/bin/env python3
"""账号成分推送 → 腾讯文档落地(飞书 drive:drive 审批期的过渡通道, 2026-09-23)。

复用 feishu.py 的数据管道(窗口收集/九类投影/兜底翻译/排序/行生成), 只把落地层
从飞书电子表格换成腾讯文档 MCP(mcporter 子进程): 每账号一个表格, 每次推送新增
子表"年-月-日-时:分", 全量命中候选逐行写入(9列), 表格开"所有人可编辑",
飞书群里只发一条短@通知+表格链接(通知通道仍走飞书, 与 doc 模式同格式)。

用法:
    py -3.11 scripts/push_doc_tencent.py [--window 3] [--dry-run] [--account Owenwin888]

依赖: mcporter + tencent-docs/sheet-mcp 已授权(setup.sh tdoc_check_and_start_auth=READY)。
状态: 复用 data/health/feishu-account-push.json, 新增 tencent_docs:{账号名:{file_id,url}} 段。
不做节流(手动按需跑); 飞书版审批通过后由 run_account_push 原生 doc 模式接管。
"""
import argparse
import csv
import io
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "global-news-sources"))

from sources import feishu  # noqa: E402

_MC_TIMEOUT = 90           # mcporter 单次调用超时(建表/写入走外网)
_CSV_BUDGET = 12000        # 单批预算按 JSON 转义后长度计(实测 14.7K 原始 CSV 因引号/换行
                           #  转义膨胀被拒, 纯 ASCII 12K 稳过 → 按 json.dumps 后 12K 截批)
_CELL_MAX = 20000          # 单格内容上限(防极端长文撑爆命令行)


def _mcporter_cmd() -> list:
    """直调链 [node, cli.js]。.CMD shim 经 cmd.exe(行上限 8191 字符)会截断长参数,
    解析出 npm 全局 js 入口绕开(CreateProcessW 上限 32767)。"""
    exe = shutil.which("mcporter")
    if not exe:
        return []
    if exe.lower().endswith((".cmd", ".bat")):
        js = Path(exe).parent / "node_modules" / "mcporter" / "dist" / "cli.js"
        if js.is_file():
            return ["node", str(js)]
    return [exe]


def _mc(service: str, tool: str, args: dict) -> dict:
    """mcporter call → dict。error 非空即抛(含 trace_id 便于排障)。"""
    cmd = _mcporter_cmd()
    if not cmd:
        raise RuntimeError("mcporter 未安装/不在 PATH")
    r = subprocess.run(cmd + ["call", service, tool,
                              "--args", json.dumps(args, ensure_ascii=False)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=_MC_TIMEOUT)
    out = (r.stdout or "").strip()
    try:
        d = json.loads(out[out.index("{"):])
    except Exception:
        raise RuntimeError(f"{tool} 输出解析失败 rc={r.returncode}: "
                           f"{out[:150]} | {str(r.stderr)[:150]}")
    if d.get("error"):
        raise RuntimeError(f"{tool}: {str(d['error'])[:150]}")
    return d


def _cell(v) -> str:
    s = str(v if v is not None else "").replace("\r", " ").replace("\x00", "")
    return s[:_CELL_MAX]


def _csv_batches(rows: list) -> list:
    """行数组 → [批, ...], 批=CSV逻辑行文本列表(格内换行保留在行内)。
    切批预算按 JSON 转义后字符数(命令行真实开销)。"""
    batches, buf, cur = [], [], 0
    for row in rows:
        sio = io.StringIO()
        csv.writer(sio, lineterminator="").writerow([_cell(c) for c in row])
        line = sio.getvalue()
        cost = len(json.dumps(line, ensure_ascii=False)) + 1
        if buf and cur + cost > _CSV_BUDGET:
            batches.append(buf)
            buf, cur = [], 0
        buf.append(line)
        cur += cost
    if buf:
        batches.append(buf)
    return batches


_DEFAULT_SHEET_NAMES = {"sheet1", "工作表1", "工作表 1"}
# 腾讯文档子表名禁 : \ / ? * [ ] (Excel 系规范, 全角冒号同样拒, 2026-09-23 实测);
# 飞书格式"年-月-日-时:分"落到腾讯侧冒号→句点。
_SHEET_NAME_XLAT = str.maketrans({":": ".", "：": ".", "/": "", "\\": "",
                                  "?": "", "*": "", "[": "", "]": ""})


def _safe_sheet_title(t: str) -> str:
    return t.translate(_SHEET_NAME_XLAT)[:31]


def _ensure_sheet(file_id: str, title: str) -> str:
    """子表就绪 → sheet_id。首推=重命名默认子表; 同名已存在=幂等直用; 否则尾部新建。"""
    info = _mc("sheet-mcp", "get_sheet_info", {"file_id": file_id})
    sheets = info.get("sheets") or []
    if not sheets:
        raise RuntimeError("表格无子表(异常)")
    for sh in sheets:
        if str(sh.get("sheet_name") or "") == title:
            return str(sh["sheet_id"])
    first = sheets[0]
    if str(first.get("sheet_name") or "").strip().lower() in _DEFAULT_SHEET_NAMES:
        _mc("sheet-mcp", "rename_sheet",
            {"file_id": file_id, "sheet_id": first["sheet_id"], "name": title})
        return str(first["sheet_id"])
    for t in (title, f"{title}-2"):
        d = _mc("sheet-mcp", "add_sheet",
                {"file_id": file_id, "name": t, "append_index": True})
        sid = str(d.get("sheet_id") or "")
        if sid:
            return sid
    raise RuntimeError("子表创建失败")


def _write_rows(file_id: str, sheet_id: str, rows: list) -> tuple:
    """分批写入 → (写入行数, [被跳过的行CSV前缀])。批失败自动对半拆分重试,
    单行失败跳过记录(6086106 随特定内容触发, 单行隔离不废全批)。"""
    written, dropped = 0, []

    def emit(lines: list) -> bool:
        nonlocal written
        try:
            _mc("sheet-mcp", "set_range_value_by_csv",
                {"file_id": file_id, "sheet_id": sheet_id, "start_row": written,
                 "start_col": 0, "csv_data": "\n".join(lines)})
            written += len(lines)
            return True
        except RuntimeError:
            if len(lines) == 1:
                dropped.append(lines[0][:200])
                return True
            m = max(1, len(lines) // 2)
            return emit(lines[:m]) and emit(lines[m:])

    for batch in _csv_batches(rows):
        emit(batch)
    return written, dropped


def _ensure_doc_tencent(st: dict, acc: dict) -> tuple:
    """账号 → (file_id, url, is_new)。首次建「选题推送-{账号名}」(≤36字)并开所有人可编辑。"""
    docs = st.setdefault("tencent_docs", {})
    key = str(acc.get("name") or "")
    hit = docs.get(key) or {}
    if hit.get("file_id") and hit.get("url"):
        return hit["file_id"], hit["url"], False
    title = f"选题推送-{key}"[:36]
    d = _mc("tencent-docs", "manage.create_file", {"title": title, "file_type": "sheet"})
    file_id, url = str(d.get("file_id") or ""), str(d.get("url") or "")
    if not file_id:
        raise RuntimeError(f"建表返回缺 file_id: {json.dumps(d, ensure_ascii=False)[:150]}")
    _mc("tencent-docs", "manage.set_privilege", {"file_id": file_id, "policy": 3})
    docs[key] = {"file_id": file_id, "url": url}
    return file_id, url, True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=float, default=None, help="收集窗口小时数(缺省取配置)")
    ap.add_argument("--dry-run", action="store_true", help="只组行打印, 不建表不发通知")
    ap.add_argument("--account", default="", help="只推该账号名(缺省=配置全部)")
    args = ap.parse_args()

    conf = feishu._conf()
    pc = feishu._push_conf(conf)
    accounts = [a for a in pc["accounts"]
                if not args.account or str(a.get("name") or "") == args.account]
    rep = {"dry_run": args.dry_run, "accounts": [a.get("name") for a in accounts],
           "docs": 0, "errors": []}
    if not accounts:
        rep["skipped"] = "无匹配账号"
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 3

    import datetime as _dt
    import re
    win_h = float(args.window if args.window is not None else pc["window_h"])
    since = (_dt.datetime.now() - _dt.timedelta(hours=win_h)
             ).strftime("%Y-%m-%d %H:%M:%S")
    conn = feishu._store._connect()
    try:
        rows = conn.execute(
            "SELECT source_id, time, text, text_zh, url, author_handle, sectors, markets, "
            "item_type, author_role FROM items "
            "WHERE fetched_at>=? AND source_id LIKE '%twitter%' "
            "ORDER BY time DESC LIMIT 400", (since,)).fetchall()
    finally:
        conn.close()
    seen, items = set(), []
    for r in rows:
        u = str(r[4] or "")
        if u and u in seen:
            continue
        if u:
            seen.add(u)
        items.append({"text": re.sub(r"^@\w+:\s*", "", str(r[2] or "")),
                      "text_zh": r[3], "url": u, "time": r[1],
                      "author_handle": r[5], "sectors": r[6], "markets": r[7],
                      "item_type": r[8], "author_role": r[9],
                      "views": None, "likes": None})
    rep["items"] = len(items)
    if not items:
        rep["skipped"] = f"窗口 {win_h}h 内无 X 新帖"
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0
    a_topics = feishu._author_topics()
    for it in items:
        it["topics"] = feishu._item_topics(it["sectors"], it["markets"],
                                           it["author_handle"], a_topics, it["text"])
    cand = [it for it in items if it["topics"]]
    rep["classified"] = len(cand)
    feishu._enrich_stats(cand, max_handles=40)
    bj = time.strftime("%m-%d %H:%M", time.localtime(time.time() - win_h * 3600)) \
        + "~" + time.strftime("%H:%M")
    send_conf = dict(conf)
    send_conf["chat_id"] = pc["chat_id"]
    rep["translated"] = 0
    st = feishu._load_state(feishu._PUSH_STATE)
    st_dirty = False
    for acc in accounts:
        name = str(acc.get("name") or "?")
        mix = {str(k): float(v) for k, v in (acc.get("mix") or {}).items()
               if str(k) in feishu.TOPICS and float(v) > 0}
        if not mix:
            rep["errors"].append(f"{name}: mix 无效")
            continue
        ordered = feishu._doc_order_all(cand, mix)
        rows_items = [it for _, its in ordered for it in its]
        if not rows_items:
            rep["errors"].append(f"{name}: 窗口内无命中素材")
            continue
        title = _safe_sheet_title(feishu._doc_sheet_title())
        rep["translated"] += feishu._translate_missing(conf, rows_items, cap=24)
        drows = feishu._doc_rows(acc, mix, ordered, bj, len(cand))
        if args.dry_run:
            print(f"[dry] {name} 子表 {title}: {len(drows)} 行, 首行: {drows[0]}")
            continue
        try:
            file_id, url, is_new = _ensure_doc_tencent(st, acc)
            st_dirty = True
            sid = _ensure_sheet(file_id, title)
            nw, dropped = _write_rows(file_id, sid, drows)
            if dropped:
                rep.setdefault("dropped_rows", {})[name] = dropped
            try:                                  # 冻结前两行+首列(体验项, 失败不阻断)
                _mc("sheet-mcp", "set_freeze",
                    {"file_id": file_id, "sheet_id": sid, "row_count": 2, "col_count": 1})
            except RuntimeError:
                pass
            if not is_new:                        # 已有表格幂等再确认开放权限
                _mc("tencent-docs", "manage.set_privilege",
                    {"file_id": file_id, "policy": 3})
            rep["docs"] += 1
            oid = str(acc.get("owner_open_id") or "").strip()
            owner = str(acc.get("owner") or "").strip() or "账号所有人"
            head = f'<at user_id="{oid}"></at>' if oid else f"@{owner}"
            ok, err = feishu.send_text(send_conf,
                                       f"{head} 账号「{name}」{title} 选题已更新"
                                       f"（命中{len(cand)}条·{len(rows_items)}行）→ {url}")
            if not ok:
                rep["errors"].append(f"{name}: 表格已更新但群通知失败 {err}")
            rep.setdefault("urls", {})[name] = url
            print(f"OK {name}: {title} 写入{nw}/{len(drows)}行"
                  + (f"(跳过{len(dropped)}行)" if dropped else "")
                  + f" → {url}")
            time.sleep(0.5)
        except Exception as e:
            rep["errors"].append(f"{name}: {type(e).__name__} {str(e)[:150]}")
    if st_dirty and not args.dry_run:
        feishu._save_state(feishu._PUSH_STATE, st)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0 if not rep["errors"] else 3


if __name__ == "__main__":
    sys.exit(main())
