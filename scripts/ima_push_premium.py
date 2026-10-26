# -*- coding: utf-8 -*-
"""cimi_premium 公众号文章 → ima 知识库 推送器(2026-10-26)。

数据面: 云端数据站 /v1/items?sources=cimi_premium (key 从 data/workbench/settings.json
source 段读, 不落仓); 增量以 data/ima_push_state.json 按 item id 记账。
上传面: ima-skill CLI(node ima_api.cjs), 凭证 ~/.config/ima/{client_id,api_key};
  mode=url  → import_urls 让 ima 自采微信原文(保真最高, 10 URL/批)
  mode=md   → 落 md 临时文件走六步上传(preflight→查重→create_media→COS→add_knowledge)
分组: 按 items 的 media 字段(公众号名)查 folder_map 定位 folder_id; 未命中落 fallback_folder。
配置: data/ima_push_config.json (kb_id 待钥匙到位后填)。

用法: python scripts/ima_push_premium.py [--dry] [--limit N] [--mode url|md]
"""
import argparse
import json
import os
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
SOURCE_ID = "cimi_premium"
DEFAULT_CFG = {
    "kb_id": "",
    "mode": "url",
    "folder_map": {"invest wallstreet": "", "半导体行业观察": ""},
    "fallback_folder": "",
    "skill_cli": "C:/Users/hzh/.agents/skills/ima-skill/ima_api.cjs",
    "station_base_url": "https://data.haiwai.ltd",
}


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
    url = (f"{base}/v1/items?sources={SOURCE_ID}&limit=200&since={since}&dedup=0"
           f"&cursor=")
    out = []
    for _ in range(5):                       # 翻页兜底
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key})
        d = json.load(urllib.request.urlopen(req, timeout=30))
        out += d.get("items") or []
        cur = d.get("next_cursor") or ""
        if not cur or len(out) >= 600:
            break
        url = (f"{base}/v1/items?sources={SOURCE_ID}&limit=200&since={since}"
               f"&dedup=0&cursor={urllib.parse.quote(cur)}")
    return out


def _ima_api(cli: str, path: str, body: dict) -> dict:
    """调 ima-skill CLI; 凭证走 ~/.config/ima 默认; 返回解析后的 dict。"""
    r = subprocess.run(["node", cli, path, json.dumps(body, ensure_ascii=False)],
                       capture_output=True, text=True, timeout=120)
    raw = (r.stdout or "").strip() or (r.stderr or "").strip()
    try:
        return json.loads(raw)
    except Exception:
        raise RuntimeError(f"ima CLI 非 JSON 回包: {raw[:200]}")


def push_urls(cli: str, kb_id: str, urls: list, folder_id: str) -> dict:
    body = {"urls": urls, "knowledge_base_id": kb_id}
    if folder_id:
        body["folder_id"] = folder_id
    return _ima_api(cli, "openapi/wiki/v1/import_urls", body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--mode", choices=("url", "md"), default="")
    a = ap.parse_args()

    cfg = dict(DEFAULT_CFG, **_load(CFG, {}))
    if a.mode:
        cfg["mode"] = a.mode
    state = _load(STATE, {"done": {}})
    done = state["done"]

    if not a.dry and not cfg["kb_id"]:
        print("✗ data/ima_push_config.json 的 kb_id 未配置(钥匙到位后回填)")
        return 4

    since = ((datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"))
    items = _pull_items(cfg["station_base_url"], _station_key(), since)
    fresh = [it for it in items if str(it.get("id")) not in done]
    if a.limit:
        fresh = fresh[: a.limit]
    print(f"站内 {SOURCE_ID}: 拉到 {len(items)} 条, 待推 {len(fresh)} 条 "
          f"(state 已记 {len(done)})")

    by_acc = {}
    for it in fresh:
        by_acc.setdefault(str(it.get("media") or "未知号"), []).append(it)
    ok = fail = 0
    for acc, lst in sorted(by_acc.items()):
        folder = cfg["folder_map"].get(acc) or cfg["fallback_folder"] or ""
        print(f"[{acc}] {len(lst)} 篇 -> folder: {folder or '(根目录)'}")
        if a.dry:
            for it in lst[:3]:
                print(f"   - {it.get('time')} | {(it.get('title') or '')[:40]}")
            continue
        if cfg["mode"] == "url":
            for i in range(0, len(lst), 10):          # import_urls 每批 ≤10
                batch = lst[i:i + 10]
                resp = push_urls(cfg["skill_cli"], cfg["kb_id"],
                                  [it["url"] for it in batch], folder)
                good = resp.get("code") == 0
                print(f"   批{i//10+1}: {'✓' if good else '✗ ' + str(resp.get('msg', ''))[:80]}")
                for it in (batch if good else []):
                    done[str(it["id"])] = {"t": it.get("time"), "title": it.get("title"),
                                           "ts": int(time.time()), "mode": "url"}
                    ok += 1
                if not good:
                    fail += len(batch)
        else:                                          # md 模式: 待钥匙到位后按需实现
            print("   md 模式尚未启用(url 模式优先; 需要时再接六步上传)")
            fail += len(lst)
    if not a.dry:
        _save(STATE, state)
        print(f"完成: 成功 {ok} / 失败 {fail}; state 记账 {len(done)} 条")
    return 0 if fail == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
