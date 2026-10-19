# -*- coding: utf-8 -*-
"""Gangtise OpenAPI 投研日报(2026-10-19 接入)。

通道: gangtise CLI 子进程(官方 OpenAPI, 积分计费)——列表探查 0.1/条, 正文下载 10/篇。
帐号: gh_988340e1c018「Gangtise投研」, 工作日 ~06:30 发布《Gangtise投研日报》,
列表层自带行业(中信/申万)/题材/关联个股标签, 直接进条目的 sectors/tickers 字段。

防重复下载: seen 文件按 articleId 记账 14 天(下载 10 积分/篇, 必须在抓取层拦,
不能等 store 入库去重——那是花钱之后)。AK/SK 走 config.local.yaml
sources.gangtise_daily 段(access_key/secret_key), 缺省回退环境变量 GANGTISE_*。
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_BJ = ZoneInfo("Asia/Shanghai")
ACCOUNT_ID = "gh_988340e1c018"
_SEEN_PATH = Path(__file__).resolve().parents[2] / "data" / "cache" / "gangtise_daily_seen.json"


def _seen() -> dict:
    try:
        d = json.load(open(_SEEN_PATH, encoding="utf-8"))
        return {k: v for k, v in d.items() if v > time.time() - 14 * 86400}
    except Exception:
        return {}


def _mark(article_id: str) -> None:
    try:
        d = _seen()
        d[article_id] = int(time.time())
        _SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(_SEEN_PATH) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, _SEEN_PATH)
    except OSError:
        pass


def _cli(args: list, env: dict, timeout: int = 120) -> str:
    # Windows 下 npm 全局装的是 gangtise.cmd, subprocess 不经 shell 解析不到——which 显式定位
    bin_path = shutil.which("gangtise") or shutil.which("gangtise.cmd") or "gangtise"
    r = subprocess.run([bin_path, *args], capture_output=True, text=True,
                       timeout=timeout, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"gangtise CLI 失败(rc={r.returncode}): {(r.stderr or r.stdout)[:180]}")
    return r.stdout


def fetch_gangtise_daily(access_key: str = "", secret_key: str = "", size: int = 3) -> list:
    env = dict(os.environ)
    if access_key:
        env["GANGTISE_ACCESS_KEY"] = access_key
    if secret_key:
        env["GANGTISE_SECRET_KEY"] = secret_key
    if not env.get("GANGTISE_ACCESS_KEY") or not env.get("GANGTISE_SECRET_KEY"):
        raise RuntimeError("gangtise_daily 需要 AK/SK: config.local.yaml sources.gangtise_daily 段 "
                           "(access_key/secret_key) 或环境变量 GANGTISE_*")
    out = _cli(["insight", "official-account", "list", "--account-id", ACCOUNT_ID,
                "--size", str(size), "--rank-type", "2", "--format", "json"], env)
    seen = _seen()
    items = []
    for a in json.loads(out).get("list") or []:
        aid = str(a.get("articleId") or "")
        title = (a.get("title") or "").strip()
        if not aid or "投研日报" not in title or aid in seen:
            continue
        text = ""
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, f"{aid}.txt")
            try:
                _cli(["insight", "official-account", "download", "--article-id", aid,
                      "--output", p], env, timeout=180)
                text = open(p, encoding="utf-8").read().strip()
            except Exception:
                pass                     # 下载失败不标 seen, 窗口内下轮重试
        if not text:
            continue
        _mark(aid)
        pt = (a.get("publishTime") or "")[:16]
        items.append({
            "time": pt if re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", pt)
                    else datetime.now(_BJ).strftime("%Y-%m-%d %H:%M"),
            "title": title, "text": text,
            "media": "Gangtise投研", "source": "Gangtise投研",
            "url": a.get("url") or f"gangtise://article/{aid}",
            "sectors": sorted({(x.get("industryName") or "").strip()
                               for x in (a.get("industryList") or [])
                               if x.get("industryName")}),
            "tickers": sorted({(x.get("securityCode") or "").strip()
                               for x in (a.get("securityList") or [])
                               if x.get("securityCode")}),
        })
    return items
