# -*- coding: utf-8 -*-
"""cimi_premium 公众号文章 → ima 知识库「投资大全」推送器(2026-10-26 v2)。

数据面: 云端数据站 /v1/items?sources=cimi_premium (key 从 data/workbench/settings.json
source 段读, 不落仓); 增量以 data/ima_push_state.json 按 item id 记账。
上传面: 该 KB 已无文件夹体系, 行业分类=文件名前缀约定(260921-[半导体]xxx.pdf)——
  故主模式 mode=md: 渲染 md(标题/公众号/时间/原文链接头 + 全文) 走六步上传
  (scripts/ima_upload_file.cjs), 文件名 {YYMMDD}-[{行业}]-{公众号}-{标题}.md;
  分类沿用 workbuddy 老项目的关键词优先级表(跑标题+正文前3000字), 未中→[暂用]。
  mode=url(import_urls 让 ima 自采原文)保留为备选但不进命名约定。
配置: data/ima_push_config.json。用法: python scripts/ima_push_premium.py [--dry] [--limit N]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "data" / "ima_push_config.json"
STATE = ROOT / "data" / "ima_push_state.json"
WB_SETTINGS = ROOT / "data" / "workbench" / "settings.json"
MD_TMP = ROOT / "data" / "tmp" / "ima_md"
UPLOADER = ROOT / "scripts" / "ima_upload_file.cjs"
SOURCE_ID = "cimi_premium"
DEFAULT_CFG = {
    "kb_id": "ima_kb_SLpUUsDZ",
    "mode": "md",
    "fallback_category": "暂用",
    "station_base_url": "https://data.haiwai.ltd",
    "classification_priority": ["半导体", "AI硬件", "AI软件", "AI基础设施", "宏观",
                                "金融", "房地产", "电力", "医疗", "食品饮料",
                                "汽车", "机器人", "媒体", "资源", "航空航天", "加密"],
}

_BAD = re.compile(r'[\\/:*?"<>|\r\n\t]')


def _load(p: Path, default):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def _save(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _station_key() -> str:
    d = _load(WB_SETTINGS, {})
    key = ((d.get("source") or {}).get("api_key") or "").strip()
    if not key:
        raise SystemExit("没有数据站 key: data/workbench/settings.json source.api_key 为空")
    return key


def _pull_items(base: str, key: str, since: str) -> list:
    url = f"{base}/v1/items?sources={SOURCE_ID}&limit=200&since={since}&dedup=0"
    out = []
    for _ in range(5):
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key})
        d = json.load(urllib.request.urlopen(req, timeout=30))
        out += d.get("items") or []
        cur = d.get("next_cursor") or ""
        if not cur or len(out) >= 600:
            break
        url = (f"{base}/v1/items?sources={SOURCE_ID}&limit=200&since={since}"
               f"&dedup=0&cursor={urllib.parse.quote(cur)}")
    return out


def classify(it: dict, cfg: dict) -> str:
    kws = cfg.get("classification_keywords") or {}
    hay = (it.get("title") or "") + "\n" + (it.get("text") or "")[:3000]
    for cat in cfg.get("classification_priority") or []:
        for kw in kws.get(cat) or []:
            if kw.lower() in hay.lower():
                return cat
    return cfg.get("fallback_category") or "暂用"


def _fname(it: dict, cat: str) -> str:
    d = (it.get("time") or "")[:10].replace("-", "")[2:] or datetime.now().strftime("%y%m%d")
    title = _BAD.sub(" ", (it.get("title") or "无题")).strip()[:42]
    media = _BAD.sub(" ", str(it.get("media") or "公众号")).strip()[:20]
    return f"{d}-[{cat}]-{media}-{title}.md"


def render_md(it: dict, cat: str, path: Path) -> str:
    fname = _fname(it, cat)
    head = (f"# {it.get('title') or ''}\n\n"
            f"> 来源公众号: {it.get('media')} ｜ 发布: {it.get('time')} ｜ "
            f"分类: [{cat}] ｜ [原文链接]({it.get('url')})\n\n---\n\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_name(fname).write_text(head + (it.get("text") or ""), encoding="utf-8")
    return fname


def _ima_api_raw(path: str, body: dict) -> dict:
    """直调 ima-skill CLI(凭证默认位); 仅查询用。"""
    cli = Path.home() / ".agents" / "skills" / "ima-skill" / "ima_api.cjs"
    r = subprocess.run(["node", str(cli), path, json.dumps(body, ensure_ascii=False)],
                       capture_output=True, text=True, timeout=120)
    raw = (r.stdout or "").strip() or (r.stderr or "").strip()
    try:
        return json.loads(raw)
    except Exception:
        return {"code": -1, "msg": raw[:120]}


def _already_in_kb(fname: str, kb_id: str) -> bool:
    """同名防重: search 即时生效(check_repeated_names 有索引延迟, 1026 重复上传实证)。"""
    d = _ima_api_raw("openapi/wiki/v1/search_knowledge",
                     {"query": fname[:40], "knowledge_base_id": kb_id, "cursor": ""})
    for i in ((d.get("data") or {}).get("info_list") or []):
        if (i.get("title") or "") == fname:
            return True
    return False


def upload_md(cli_abs: Path, fpath: Path, kb_id: str) -> dict:
    r = subprocess.run(["node", str(cli_abs), str(fpath), kb_id],
                       capture_output=True, text=True, timeout=420,
                       cwd=str(cli_abs.parent))
    raw = (r.stdout or "").strip()
    try:
        return json.loads(raw)
    except Exception:
        return {"success": False, "error": f"rc={r.returncode}: "
                + ((r.stderr or raw or "")[:160])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    file_cfg = {k: v for k, v in _load(CFG, {}).items() if v != "" or k == "fallback_category"}
    cfg = dict(DEFAULT_CFG, **file_cfg)
    if not cfg.get("kb_id"):
        print("✗ config 缺 kb_id")
        return 4
    if not cfg.get("classification_keywords"):
        print("✗ config 缺 classification_keywords(运行 scripts/ima_push_premium.py 前需灌入)")
        return 4
    state = _load(STATE, {"done": {}})
    done = state["done"]

    since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    items = _pull_items(cfg["station_base_url"], _station_key(), since)
    fresh = [it for it in items if str(it.get("id")) not in done]
    if a.limit:
        fresh = fresh[: a.limit]
    print(f"站内 {SOURCE_ID}: 拉到 {len(items)}, 待推 {len(fresh)} (state 已记 {len(done)})")

    ok = fail = skip = 0
    cats = {}
    for it in fresh:
        cat = classify(it, cfg)
        cats[cat] = cats.get(cat, 0) + 1
        fname = _fname(it, cat)
        if a.dry:
            print(f"  [{cat}] {fname[:70]}")
            continue
        if _already_in_kb(fname, cfg["kb_id"]):
            done[str(it["id"])] = {"f": fname, "ts": int(time.time()), "rep": 1}
            skip += 1
            continue
        fname2 = render_md(it, cat, MD_TMP / fname)
        r = upload_md(UPLOADER, MD_TMP / fname, cfg["kb_id"])
        if r.get("success"):
            done[str(it["id"])] = {"f": fname, "ts": int(time.time())}
            ok += 1
            try:
                (MD_TMP / fname).unlink()
            except OSError:
                pass
        elif r.get("repeated"):                  # 同名已存在=已传过, 记账防再撞
            done[str(it["id"])] = {"f": fname, "ts": int(time.time()), "rep": 1}
            skip += 1
        else:
            fail += 1
            print(f"  ✗ {fname[:50]} | {r.get('error', '')[:100]}")
        time.sleep(0.6)                          # 上传间隔, 温柔对待
    print("分类分布:", json.dumps(cats, ensure_ascii=False))
    if not a.dry:
        _save(STATE, state)
        print(f"完成: 成功 {ok} / 跳过(重名) {skip} / 失败 {fail}")
    return 0 if fail == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
