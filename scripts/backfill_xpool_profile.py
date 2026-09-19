#!/usr/bin/env py -3.11
"""X 账号池字段回填: 对 twitter_pool.yaml 全部账号补齐 followers/positioning/tags 三个字段。

- followers: FxTwitter /2/profile/<h> 的 user.followers(免登录; 与 workbench/x_track 同源)。
  端点失败时回退 /2/profile/<h>/statuses 的 author.followers; 再失败留空不炸。
- positioning/tags: bio + 近 5 条本人帖喂 LLM 生成(一句话定位 + 3~5 个概念词)。
  LLM 链 = ai-workflow/generator/config.yaml 的 sources.translate.models(空 base_url/
  api_key 继承发布仓 secret.local.json 全局配置), 经 workbench vstudio.chat_completions_ex
  通道(自带代理双路径回退); 链全挂时兜底全局 secret 的 deepseek-v4-flash。
- 断点续跑: 三字段已齐的账号跳过(--force 重跑); 每个 LLM 批次结束即原子写回池文件。
- 幂等: 重跑只补空字段, 绝不改池内已有字段语义。

文本级插入写回(逐账号块尾追加三行), 保住原文件的字段顺序与引号风格, git diff 最小。
写回后跑 `py -3.11 scripts/sync_seeds.py` 把池同步进 workbench/server/seed/。

用法: py -3.11 scripts/backfill_xpool_profile.py [--limit N] [--handles a,b] [--force] [--dry-run]
"""
import argparse
import json
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
POOL = REPO / "global-news-sources" / "config" / "twitter_pool.yaml"
GEN_CFG = REPO / "ai-workflow" / "generator" / "config.yaml"

_FX = "https://api.fxtwitter.com"
UA = {"User-Agent": "aag-xpool-backfill/0.1", "Accept": "application/json"}
FETCH_WORKERS = 3          # 与 x_track 同款纪律: 3 并发对 FxTwitter 友好
FETCH_SLEEP = 0.4
LLM_BATCH = 10
LLM_TIMEOUT = 180

_SYS = """你是财经账号简介员。输入为一批 X(Twitter) 账号的 bio(个人简介)。对每个账号输出:
- positioning: 一句话中文介绍(≤20字), 只陈述 bio 里的事实——这个账号是谁/做什么内容;
  bio 没有的信息一律不编; bio 空泛就写最简事实句(如"财经博主")。
- tags: 从下列一级概念词表中选 1~3 个, 只能用词表里的词, 一般 1 个市场 + 0~2 个领域:
  AI / 科技 / 加密 / 美股 / A股 / 港股 / 日股 / 韩股 / 台股 / 土耳其
只输出 JSON 数组 [{"handle":"...","positioning":"...","tags":["..."]}], 不要任何多余文字。"""

_TAG_VOCAB = {"AI", "科技", "加密", "美股", "A股", "港股", "日股", "韩股", "台股", "土耳其"}


# ── 池文件读写(文本级, 保格式) ────────────────────────────────────────────────

def load_pool() -> dict:
    return yaml.safe_load(POOL.read_text(encoding="utf-8")) or {}


def _blocks(lines: list) -> list:
    """账号块切分: [(start, end, handle_lower), ...] 半开区间; "- handle:"(列0)起,
    到下一个列0元素("- handle:"/"filters:")或 EOF 止。"""
    starts = []
    for i, ln in enumerate(lines):
        if ln.startswith("- handle:"):
            h = ln.split(":", 1)[1].strip().strip("'\"").lstrip("@").lower()
            starts.append((i, h))
    out = []
    for n, (i, h) in enumerate(starts):
        j = len(lines)
        for k in range(i + 1, len(lines)):
            ln = lines[k]
            if ln.startswith("- handle:") or (ln and not ln[0].isspace()):
                j = k
                break
        out.append((i, j, h))
    return out


def _scalar_lines(key: str, val) -> list:
    """单字段 → 池文件行(2空格缩进); 列表用块风格。"""
    body = yaml.safe_dump({key: val}, allow_unicode=True, default_flow_style=False,
                          sort_keys=False, width=4096)
    return [("  " + ln) if ln.strip() else ln for ln in body.rstrip("\n").split("\n")]


def apply_updates(updates: dict, dry_run: bool = False) -> int:
    """updates = {handle_lower: {followers:int, positioning:str, tags:[str]}} → 块尾插入, 原子写。
    幂等: 块内已有的字段键跳过(重复调用/断点续跑不双插)。"""
    import os
    text = POOL.read_text(encoding="utf-8")
    lines = text.split("\n")
    blocks = sorted(_blocks(lines), key=lambda b: -b[0])   # 块尾插入: 尾→头改, 前方索引不失效
    patched = 0
    for i, j, h in blocks:
        upd = updates.get(h)
        if not upd:
            continue
        end = j
        while end > i and not lines[end - 1].strip():      # 越过块尾空行再插
            end -= 1
        # 三字段: 已有行就地替换(--force 覆盖语义; 旧纯插入逻辑盖不上旧值, 2026-09-19 修复),
        # 块内没有的字段照旧块尾插入。
        desired = {}
        if upd.get("followers") is not None:
            desired["followers"] = upd["followers"]
        if upd.get("positioning"):
            desired["positioning"] = str(upd["positioning"])
        if "tags" in upd:                # 重新生成后空标签=明确清空旧自由词(2026-09-19 裁决)
            desired["tags"] = [str(t) for t in upd["tags"]][:5]
        changed = False
        body = lines[i:end]
        for k, ln in enumerate(body):
            m = re.match(r"^  ([A-Za-z_][\w-]*):", ln)
            if m and m.group(1) in desired:
                key = m.group(1)
                val = desired.pop(key)
                if key == "followers":
                    val = int(val)
                new_lines = _scalar_lines(key, val)
                # 连旧列表项(- item 行)整体替换, 否则旧 tags 残留(2026-09-19 修复)
                j = k + 1
                while j < len(body) and re.match(r"^  -\s", body[j]):
                    j += 1
                if body[k:j] != new_lines:
                    body[k:j] = new_lines
                    changed = True
        if changed:
            lines[i:end] = body
        add = []
        for key, val in desired.items():
            add += _scalar_lines(key, val)
        if not (add or changed):
            continue
        lines[end:end] = add
        patched += 1
    if dry_run or not patched:
        return patched
    new_text = "\n".join(lines)
    if not new_text.endswith("\n"):
        new_text += "\n"
    POOL.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(POOL.parent), suffix=".tmp")
    with open(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_text)
    os.replace(tmp, POOL)
    yaml.safe_load(new_text)                               # 写后自查: 必须仍是合法 yaml
    return patched


def _done(a: dict) -> bool:
    return bool(a.get("followers") is not None and str(a.get("positioning") or "").strip()
                and a.get("tags"))


# ── FxTwitter 抓取 ───────────────────────────────────────────────────────────

class RateLimited(Exception):
    pass


def _get(path: str, params: str = "") -> dict:
    import urllib.error
    import urllib.request
    url = _FX + path + (("?" + params) if params else "")
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RateLimited()
        raise RuntimeError(f"http_{e.code}")


def _own_texts(items: list, handle: str, n: int = 5) -> list:
    out = []
    for it in items:
        posts = it.get("statuses") or [] if it.get("type") == "thread" else [it]
        for s in posts:
            if not isinstance(s, dict):
                continue
            au = s.get("author") or {}
            if str(au.get("screen_name", "")).lower() != handle or s.get("reposted_by"):
                continue
            t = re.sub(r"\s+", " ", str(s.get("text") or "")).strip()
            if t:
                out.append(t[:160])
            if len(out) >= n:
                return out
    return out


def fetch_one(handle: str, need_posts: bool = True) -> dict:
    """→ {followers:int|None, bio:str, posts:[str], afollowers:int|None}; 失败字段留空。"""
    out = {"followers": None, "bio": "", "posts": [], "afollowers": None}
    try:
        d = _get(f"/2/profile/{handle}")
        u = d.get("user") or {}
        out["followers"] = int(u.get("followers")) if u.get("followers") is not None else None
        out["bio"] = str(u.get("description") or "")[:220]
    except RateLimited:
        raise
    except Exception:
        pass
    if not need_posts:
        return out
    try:
        d = _get(f"/2/profile/{handle}/statuses", "count=30&groupthreads=true&with_replies=true")
        res = d.get("results") or []
        out["posts"] = _own_texts(res, handle)
        for it in res:
            au = (it.get("author") or {}) if isinstance(it, dict) else {}
            if au.get("followers") is not None:
                out["afollowers"] = int(au.get("followers"))
                break
    except RateLimited:
        raise
    except Exception:
        pass
    return out


# ── LLM 链(项目现有通道: generator translate 链 → 全局 secret 兜底) ────────────

def _secret() -> tuple:
    """发布仓 secret.local.json → (base_url, api_key); 解析顺序同 generator.common。"""
    import os
    root = os.environ.get("AAG_AUTOPUB_ROOT")
    p = Path(root) if root else REPO.parent / "ai-auto-publisher" / "autopub"
    f = p / "secret.local.json"
    if not f.is_file():
        return "", ""
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        return str(d.get("base_url") or "https://ark.cn-beijing.volces.com/api/plan/v3"), \
            str(d.get("api_key") or "")
    except Exception:
        return "", ""


def build_chain() -> list:
    """→ [(base, key, model, tag)]; 读 generator config sources.translate.models,
    空 base/key 继承全局 secret; 追加全局 deepseek-v4-flash 兜底位(去重)。"""
    base_s, key_s = _secret()
    chain, seen = [], set()
    try:
        cfg = yaml.safe_load(GEN_CFG.read_text(encoding="utf-8")) or {}
        models = ((cfg.get("sources") or {}).get("translate") or {}).get("models") or []
    except Exception:
        models = []
    for m in models:
        if not isinstance(m, dict):
            continue
        b = str(m.get("base_url") or "").strip() or base_s
        k = str(m.get("api_key") or "").strip() or key_s
        mm = str(m.get("model") or "").strip() or "deepseek-v4-flash"
        if k and (b, mm) not in seen:
            chain.append((b, k, mm, mm))
            seen.add((b, mm))
    if key_s and (base_s, "deepseek-v4-flash") not in seen:
        chain.append((base_s, key_s, "deepseek-v4-flash", "deepseek-v4-flash(兜底)"))
    return chain


def llm_chat(chain: list, sticky: list, user: str) -> str:
    """链式调用, 成功粘性沿用; 返回 content, 全挂抛 RuntimeError。走 vstudio 通道(代理双路径)。"""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from workbench.server.vstudio import chat_completions_ex
    order = chain[sticky[0]:] + chain[:sticky[0]]
    errs = []
    for base, key, model, tag in order:
        content, err = chat_completions_ex(
            base, key, model,
            [{"role": "system", "content": _SYS}, {"role": "user", "content": user}],
            temperature=0.2, max_tokens=2400, timeout=LLM_TIMEOUT)
        if content:
            sticky[0] = chain.index((base, key, model, tag))
            return content
        errs.append(f"{tag}: {err}")
        print(f"    [链位失败] {tag}: {err}")
    raise RuntimeError("LLM 链全挂: " + " | ".join(errs)[:400])


def _parse_json_arr(text: str) -> list:
    text = re.sub(r"```(?:json)?", "", text).strip().strip("`")
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
        return arr if isinstance(arr, list) else []
    except Exception:
        return []


def norm_positioning(s) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s[:40]


def norm_tags(v) -> list:
    if isinstance(v, str):
        v = re.split(r"[/,、\s]+", v)
    out, seen = [], set()
    for t in v or []:
        t = str(t or "").strip().strip("#")
        # 一级概念词表硬过滤(2026-09-19 用户裁决): 词表外的自由词一律丢弃
        if t and t in _TAG_VOCAB and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:5]


# ── 主流程 ───────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="本次最多处理 N 个账号(0=全部)")
    ap.add_argument("--handles", default="", help="只处理这些 handle(逗号分隔)")
    ap.add_argument("--force", action="store_true", help="三字段已齐的账号也重跑")
    ap.add_argument("--dry-run", action="store_true", help="只抓与生成, 不写回池文件")
    a = ap.parse_args()

    pool = load_pool()
    accounts = [x for x in (pool.get("accounts") or []) if x.get("handle")]
    only = {h.strip().lstrip("@").lower() for h in a.handles.split(",") if h.strip()}
    todo = []
    for x in accounts:
        h = str(x["handle"]).lstrip("@").lower()
        if only and h not in only:
            continue
        if not a.force and _done(x):
            continue
        todo.append((h, x))
    if a.limit > 0:
        todo = todo[:a.limit]
    print(f"池内 {len(accounts)} 账号, 待回填 {len(todo)}" + (" (dry-run)" if a.dry_run else ""))

    # 阶段1: FxTwitter 抓档案+近帖(3并发, 429 全局熔断)
    fetched, stop = {}, False

    def work(item):
        nonlocal stop
        if stop:
            return
        h, x = item
        need_posts = a.force or not (str(x.get("positioning") or "").strip() and x.get("tags"))
        try:
            fetched[h] = fetch_one(h, need_posts=need_posts)
            time.sleep(FETCH_SLEEP)                        # 每账号节流(与池抓取同纪律)
            print(f"  [fetch] @{h} followers={fetched[h]['followers']} "
                  f"posts={len(fetched[h]['posts'])}")
        except RateLimited:
            stop = True
            print(f"  [429] @{h} 触发限流, 本轮到此为止(可重跑续传)")
        except Exception as e:
            print(f"  [fail] @{h} {type(e).__name__}: {str(e)[:60]}")

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        list(ex.map(work, todo))
    print(f"抓取完成 {len(fetched)}/{len(todo)}, 用时 {int(time.time()-t0)}s")

    # 阶段2: LLM 生成 positioning/tags(批 10, 批级写回落盘=断点续跑)
    chain = build_chain()
    if not chain:
        print("[warn] 无可用 LLM 配置(链空且全局 secret 缺失), 只回填 followers")
    print(f"LLM 链: {' → '.join(t for *_x, t in chain)}")
    updates = {}
    llm_fail = []
    for h, prof in fetched.items():
        upd = {}
        fol = prof["followers"] if prof["followers"] is not None else prof["afollowers"]
        if fol is not None:
            upd["followers"] = fol
        if prof["posts"] or prof["bio"]:
            upd["_llm"] = prof
        if upd:
            updates[h] = upd

    pending = [(h, u.pop("_llm")) for h, u in updates.items() if "_llm" in u]
    sticky = [0]
    for bi in range(0, len(pending), LLM_BATCH):
        batch = pending[bi:bi + LLM_BATCH]
        user = "\n".join(_llm_item(h, prof) for h, prof in batch)
        try:
            raw = llm_chat(chain, sticky, user) if chain else ""
        except RuntimeError as e:
            print(f"  [llm] 批{bi//LLM_BATCH+1}失败: {str(e)[:160]}")
            llm_fail.extend(h for h, _p in batch)
            raw = ""
        got = {}
        for row in _parse_json_arr(raw):
            if isinstance(row, dict) and row.get("handle"):
                got[str(row["handle"]).lstrip("@").lower()] = row
        for h, _prof in batch:
            row = got.get(h)
            if row:
                updates[h]["positioning"] = norm_positioning(row.get("positioning"))
                updates[h]["tags"] = norm_tags(row.get("tags"))
            else:
                llm_fail.append(h)
        for h, _prof in batch:
            u = updates.get(h) or {}
            if u.get("positioning") and u.get("tags"):
                print(f"  [llm] @{h}: {u['positioning']} | tags={','.join(u['tags'])}")
        n = apply_updates({k: {kk: vv for kk, vv in u.items() if kk != "_llm"}
                           for k, u in updates.items()}, dry_run=a.dry_run)
        print(f"  [write] 累计写回 {n} 个账号(批{bi//LLM_BATCH+1}/"
              f"{(len(pending)+LLM_BATCH-1)//LLM_BATCH})")

    # 空标签补枪(2026-09-19): 新标签被词表全滤空的账号, 单号强约束重试一次——
    # 该留空的(土耳其/宏观等词表外领域)保持空, 该给桶的(美股/科技)捞回来。
    empties = [h for h, u in updates.items()
               if u.get("positioning") and not u.get("tags") and h not in llm_fail]
    for h in empties:
        if not chain:
            break
        prof = dict(fetched.get(h) or {})
        user = (_llm_item(h, prof)
                + "\n注意: tags 只允许从词表选(可只选1个; 实在没有匹配就返回空数组[]): "
                + " / ".join(sorted(_TAG_VOCAB)))
        try:
            raw = llm_chat(chain, sticky, user)
        except RuntimeError:
            raw = ""
        row = None
        for r in _parse_json_arr(raw):
            if isinstance(r, dict):
                row = r
                break
        tags = norm_tags((row or {}).get("tags"))
        if tags:
            updates[h]["tags"] = tags
            print(f"  [llm-retry] @{h}: tags={','.join(tags)}")
    if empties:
        n = apply_updates({k: {kk: vv for kk, vv in u.items() if kk != "_llm"}
                           for k, u in updates.items()}, dry_run=a.dry_run)
        print(f"  [write] 补枪后累计写回 {n} 个账号")

    ok_n = sum(1 for u in updates.values() if u.get("followers") is not None)
    rep = {"todo": len(todo), "fetched": len(fetched), "followers_filled": ok_n,
           "llm_fail": sorted(set(llm_fail)), "pool": str(POOL), "dry_run": a.dry_run}
    print(json.dumps(rep, ensure_ascii=False))
    return 0 if not (llm_fail and not a.dry_run) else 3


def _llm_item(h: str, prof: dict) -> str:
    # 定位纯 bio(2026-09-19 用户裁决: 帖子当周热点会把模型带歪, 只取 bio 事实);
    # bio 为空的少数账号(semianalysis_/zerohedge 等档案接口不给简介)才用近期帖子佐证。
    if prof["bio"]:
        return f"账号 @{h}\n  bio: {prof['bio']}"
    posts = "\n".join(f"  - {t}" for t in prof["posts"]) or "  - (无)"
    return f"账号 @{h}\n  bio: (空)\n  近期帖子(bio 为空, 仅此佐证):\n{posts}"


if __name__ == "__main__":
    sys.exit(main())
