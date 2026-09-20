#!/usr/bin/env py -3.11
"""X 账号录入 intake: 用户原始清单 → 提取/校验/去重/验号/预分类 → 报告 + 提议登记卡(可选写池)。

固化 2026-09-17/19 手工录入 61 号四类事故的防复发(规范: global-news-sources/docs/X账号录入规范.md;
流程 SOP: skills/aag-x-register/SKILL.md):
- 事故1 放错层: 本工具只服务数据源池(twitter_pool.yaml); 飞书1min监控池/x_track 去向
  由 SOP 第0步向用户确认, 工具不裁决。
- 事故2 拼错号: 逐号 FxTwitter 验号, 404/私密/作者不符进失败清单, 绝不猜修正。
- 事故3 非法 handle: 正则 [A-Za-z0-9_]{1,15} 硬校验(带空格等原样退回, 不猜)。
- 事故4 重复: 清单内大小写去重 + 池 handle 查重 + 验号后 uid 查重(uid 撞车拒绝录入)。

步骤: ①提取+正则校验 ②清单内去重 ③池查重(handle 先行跳过省网络; 其余逐号验号
GET api.fxtwitter.com/2/profile/<h>/statuses?count=2 取 author.id/name/followers/description,
author 按 screen_name 匹配防转推陷阱——录入规范八节 biancoresearch 教训)
④预分类(role=kol/markets=[全球]/priority=medium/risk=medium/replies=false,
lang 按 bio×3+近帖字符检测) ⑤报告(新号/重复跳过/失败清单)+提议登记卡 YAML 块。
--apply: 文本级块尾追加写回池文件(原子写+写后 yaml 自查); 无 --apply 只打印报告不写。
池文本级读写/RateLimited 熔断/UTF-8 纪律与 scripts/backfill_xpool_profile.py 同款。

用法: py -3.11 scripts/xpool_intake.py <清单文件> [--apply] [--batch 标签] [--pool 路径]
退出码: 0=完成且无失败 | 2=失败清单非空(交用户核实, 不猜) | 3=429 熔断中断/硬失败
"""
import argparse
import datetime
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
POOL = REPO / "global-news-sources" / "config" / "twitter_pool.yaml"

_FX = "https://api.fxtwitter.com"
UA = {"User-Agent": "aag-xpool-intake/0.1", "Accept": "application/json"}
FETCH_SLEEP = 0.3                                   # 逐号节流(既有纪律)
HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")

# ── 步骤①: 清单解析(任意格式 → 候选 handle; 非法进失败清单, 绝不猜) ──────────

_STRIP_CHARS = "\"'`“”‘’*,.;:!?、。，：）)>】》]»"
_SKIP_TOKENS = {"handle", "@handle", "n/a", "na", "none", "null", "-", "—", "无", "空"}
_URL_PROFILE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})(?:[/?#].*)?$", re.I)
_URL_STATUS_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:www\.)?(?:x|twitter)\.com/([^/\s?#]+)/status/", re.I)


def extract_handles(text: str) -> tuple:
    """原始粘贴 → (candidates, failures, skipped)。
    candidates = [(handle, line_no)]; failures = [{"line","raw","cand","reason"}];
    skipped = 纯非 ASCII 词(表格名列/中文词, X handle 必含 [A-Za-z0-9_], 不可能是 handle,
    跳过不进失败清单免噪音)。
    支持: 裸 handle / @handle / 名字@handle 混排 / x.com 主页链接 / 编号·表格·逗号混排;
    空行与 # 注释跳过; 帖子链接不解析作者(确定性边界), 原样退回让用户给 handle。"""
    cands, fails, skipped = [], [], []
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip().lstrip("\ufeff").strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        cells = [c.strip() for c in line.split("|")] if "|" in line else [line]
        for cell in cells:
            tok = re.sub(r"^(?:\d{1,3}\s*[.、)）]|[-*•])\s*", "", cell).strip()  # 编号/列表前缀
            tok = tok.strip(_STRIP_CHARS + "-—–").strip()   # handle 不含连字符, 占位符 --- 归零
            if not tok or tok.lower().lstrip("@") in _SKIP_TOKENS:
                continue
            m = _URL_STATUS_RE.search(tok)
            if m:
                fails.append({"line": no, "raw": raw, "cand": m.group(1),
                              "reason": "帖子链接需先解析作者, 请提供 handle 或主页链接"})
                continue
            m = _URL_PROFILE_RE.search(tok)
            if m:
                cand = m.group(1)
            else:
                tok = tok.replace("＠", "@")               # 名字@handle 混排: 取最后一个 @ 之后
                cand = tok.rsplit("@", 1)[1].strip() if "@" in tok else tok
                cand = cand.strip(_STRIP_CHARS).strip()
            if cand and not re.search(r"[A-Za-z0-9_]", cand):
                # 纯非 ASCII 词(表格中文名列/中文词): X handle 必含 [A-Za-z0-9_],
                # 不可能是 handle → 记跳过不报失败, 免表格粘贴刷屏失败清单。
                skipped.append({"line": no, "raw": raw, "cand": cand})
                continue
            if not HANDLE_RE.match(cand or ""):
                if re.search(r"\s", cand or ""):
                    why = "非法 handle(含空格——X 不存在这种号)"
                elif cand and len(cand) > 15:
                    why = "非法 handle(超 15 位)"
                elif not cand:
                    why = "空候选(@ 后没有 handle)"
                else:
                    why = "非法 handle(X 仅允许 1-15 位字母/数字/下划线)"
                fails.append({"line": no, "raw": raw, "cand": cand, "reason": why})
            else:
                cands.append((cand, no))
    return cands, fails, skipped


def dedup_in_list(cands: list) -> tuple:
    """步骤② 清单内大小写去重: 保留首次。→ (kept, dupes);
    dupes = [(handle, line_no, first_line_no)]。"""
    seen, kept, dupes = {}, [], []
    for h, no in cands:
        k = h.lower()
        if k in seen:
            dupes.append((h, no, seen[k]))
        else:
            seen[k] = no
            kept.append((h, no))
    return kept, dupes


# ── 步骤④: 预分类(role/markets/priority/risk/replies 固定默认; lang 字符检测) ──

_KANA_RE = re.compile(r"[\u3040-\u30ff]")       # 假名 = 日语铁证
_HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
_TR_RE = re.compile(r"[ğışçıĞŞÇİ]")             # 土耳其语特征字母


def detect_lang(bio: str, posts: list) -> str:
    """bio×3 + 近帖字符检测: 假名→ja, 谚文→ko, 土耳其特征字母→tr, 汉字占比→zh, 其余 en。
    预分类草稿, 用户确认环节可圈改。"""
    text = (bio or "") * 3 + "".join(posts or [])
    if not text.strip():
        return "en"
    if _KANA_RE.search(text):
        return "ja"
    if _HANGUL_RE.search(text):
        return "ko"
    n = len(text)
    if len(_TR_RE.findall(text)) >= max(3, int(n * 0.02)):
        return "tr"
    if len(_HAN_RE.findall(text)) >= max(3, int(n * 0.05)):
        return "zh"
    return "en"


def build_card(handle: str, prof: dict, batch: str, date: str) -> dict:
    """验号档案 → 登记卡 dict(池字段顺序; 与 2026-09-17 批次同款 note 格式)。"""
    fol = prof.get("followers")
    w = f"{int(fol) // 10000}万" if fol is not None else "?"
    bio = re.sub(r"\s+", " ", str(prof.get("bio") or "")).strip()[:80]
    note = f"{batch}({date}); 粉丝{w}" + (f"; bio: {bio}" if bio else "")
    return {
        "handle": handle,
        "uid": str(prof["uid"]),
        "name": str(prof.get("name") or handle),
        "homepage": f"https://x.com/{handle}",
        "markets": ["全球"],
        "role": "kol",
        "lang": detect_lang(prof.get("bio") or "", prof.get("posts") or []),
        "priority": "medium",
        "risk": "medium",
        "replies": False,
        "note": note,
    }


def card_yaml_lines(card: dict) -> list:
    """登记卡 → 池文件行(首行 '- handle:', 2 空格缩进, 列表块风格——与池内既有格式一致)。"""
    body = yaml.safe_dump(card, allow_unicode=True, default_flow_style=False,
                          sort_keys=False, width=4096).rstrip("\n").split("\n")
    body[0] = "- " + body[0]
    return [body[0]] + ["  " + ln for ln in body[1:]]


# ── 池文件读写(文本级, 保格式; 与 backfill_xpool_profile.py 同款) ─────────────

def load_pool(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def pool_index(pool: dict) -> tuple:
    """→ (handles_lower→池内原写法, uid→池内 handle); uid 为身份锚点, 空 uid 不入索引。"""
    hs, uids = {}, {}
    for a in pool.get("accounts") or []:
        h = str(a.get("handle") or "").lstrip("@").lower()
        if h:
            hs[h] = str(a.get("handle"))
        u = str(a.get("uid") or "").strip()
        if u:
            uids[u] = str(a.get("handle"))
    return hs, uids


def insert_cards(pool_text: str, cards: list) -> str:
    """文本级块尾追加: 登记卡插到 accounts 段末尾(下一个列 0 顶级键之前), 保住原文件格式。"""
    lines = pool_text.split("\n")
    acc = next((i for i, ln in enumerate(lines) if re.match(r"^accounts:\s*(#.*)?$", ln)), None)
    if acc is None:
        raise RuntimeError("池文件缺 accounts: 段, 拒绝写入")
    cut = len(lines)
    for i in range(acc + 1, len(lines)):
        if re.match(r"^[A-Za-z_][\w-]*:", lines[i]):
            cut = i
            break
    if cut == len(lines) and lines and lines[-1] == "":
        cut -= 1                                    # 文件尾空行留给结尾换行
    add = []
    for c in cards:
        add += card_yaml_lines(c)
    lines[cut:cut] = add
    out = "\n".join(lines)
    if not out.endswith("\n"):
        out += "\n"
    return out


def atomic_write(text: str, path: Path) -> None:
    """原子写 + 写后 yaml 自查(必须仍是合法 yaml, 否则等于写坏池文件)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with open(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)
    yaml.safe_load(text)


# ── 步骤③: FxTwitter 逐号验号(带 UA + 节流; 429 全局熔断) ────────────────────

class RateLimited(Exception):
    pass


class NotFound(Exception):
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


def verify_one(handle: str) -> dict:
    """GET /2/profile/<h>/statuses?count=2 → {uid,name,followers,bio,posts}。
    author 按 screen_name 匹配(转推条目 author 是原作者, 本人可能在 reposted_by);
    首页匹配不上本人 → author_mismatch 失败, 绝不取首条凑数(不猜纪律)。
    followers/description 缺失时用 /2/profile/<h> 佐证补全(backfill 同款端点)。
    404→NotFound(注销或拼错); http_500 等原样 RuntimeError(调用方标注疑似私密)。"""
    try:
        d = _get(f"/2/profile/{handle}/statuses", "count=2")
    except RuntimeError as e:
        if str(e) == "http_404":
            raise NotFound(handle) from e
        raise
    items = d.get("results") or []
    authors, posts = [], []
    for it in items:
        if not isinstance(it, dict):
            continue
        au = it.get("author")
        if isinstance(au, dict) and au.get("id") is not None:
            authors.append(au)
        rb = it.get("reposted_by")                   # 转推: 本人身份在这里
        if isinstance(rb, dict) and rb.get("id") is not None:
            authors.append(rb)
        subs = it.get("statuses") or [it] if it.get("type") == "thread" else [it]
        for s in subs:
            if isinstance(s, dict):
                sau = s.get("author")
                if isinstance(sau, dict) and sau.get("id") is not None:
                    authors.append(sau)
            t = re.sub(r"\s+", " ", str((s or {}).get("text") or "")).strip()
            if t:
                posts.append(t[:160])
    if not authors:
        raise RuntimeError("无可见帖子(疑似私密/零推/注销边缘), 人工核实")
    target = handle.lower()
    au = next((a for a in authors if str(a.get("screen_name", "")).lower() == target), None)
    if au is None:
        raise RuntimeError("author_mismatch(首页未见本人, 疑似全转推/改名冲突), 不猜")
    out = {
        "uid": str(au.get("id")),
        "name": str(au.get("name") or handle),
        "followers": int(au["followers"]) if au.get("followers") is not None else None,
        "bio": re.sub(r"\s+", " ", str(au.get("description") or "")).strip()[:220],
        "posts": [p for p in posts if p][:5],
    }
    # 佐证补全: statuses 的 author 常缺 followers/description(2026-09-20 实测),
    # 用 /2/profile/<h> 补(backfill 同款端点; 该端点无转推歧义); 失败不致命不炸验号。
    if out["followers"] is None or not out["bio"] or out["name"] == handle:
        try:
            u = (_get(f"/2/profile/{handle}") or {}).get("user") or {}
            if u.get("followers") is not None:
                out["followers"] = int(u["followers"])
            if str(u.get("description") or "").strip():
                out["bio"] = re.sub(r"\s+", " ", str(u["description"])).strip()[:220]
            if str(u.get("name") or "").strip():
                out["name"] = str(u["name"])
        except RateLimited:
            raise
        except Exception:
            pass
    return out


# ── 主流程 ───────────────────────────────────────────────────────────────────

def _print_report(a, src: Path, date: str, stats: dict, new_cards: list,
                  in_dupes: list, dupes: list, failed: list, pending: list) -> None:
    bar = "═" * 22
    print(f"{bar} X 账号录入 intake 报告 {bar}")
    print(f"清单: {src} | 池: {a.pool} | 批次: {a.batch}({date}) | apply={a.apply}")
    print(f"解析: 候选 {stats['cands']} | 非法 {stats['parse_fails']} | 清单内重复 {len(in_dupes)}"
          f" | 池 handle 重复 {stats['pool_dups']} | 验号通过 {len(new_cards)}"
          f" | uid 撞车 {stats['uid_dups']} | 失败 {len(failed)}"
          + (f" | 非handle文本跳过 {len(stats['skipped'])}" if stats.get("skipped") else "")
          + (f" | 未验(限流) {len(pending)}" if pending else ""))
    if new_cards:
        print(f"── 新号 {len(new_cards)} 个(验号通过, 预分类草稿) ──")
        for c in new_cards:
            print(f"  @{c['handle']:<20} uid={c['uid']:<20} {c['name'][:24]:<26}"
                  f" lang={c['lang']}")
    if in_dupes:
        print(f"── 清单内重复 {len(in_dupes)} 个(保留首次) ──")
        for h, no, first in in_dupes:
            print(f"  @{h} 第{no}行 与 第{first}行 重复")
    if dupes:
        print(f"── 重复跳过 {len(dupes)} 个 ──")
        for h, why in dupes:
            print(f"  @{h} — {why}")
    if failed:
        print(f"── 失败清单 {len(failed)} 个(绝不猜修正, 交用户核实) ──")
        for f in failed:
            if f["line"] is not None:
                print(f"  第{f['line']}行 \"{f['raw']}\" → 候选 \"{f['cand']}\": {f['reason']}")
            else:
                print(f"  @{f['cand']}: {f['reason']}")
    if pending:
        print(f"── 未验 {len(pending)} 个(429 限流熔断, 重跑本命令幂等续传) ──")
        for h in pending:
            print(f"  @{h}")
    print(f"── {'已写池' if a.apply else '提议'}的登记卡 YAML 块 ({len(new_cards)}) ──")
    if new_cards:
        for c in new_cards:
            print("\n".join(card_yaml_lines(c)))
    else:
        print("  (无新号)")
    handles_csv = ",".join(c["handle"] for c in new_cards)
    print("── 下一步 ──")
    if failed:
        print("  1. 失败清单交用户核实(404=注销或拼错, 不猜; 用户给候选→改清单文件重跑实测)")
        print("  2. 新号报告给用户确认后, 重跑加 --apply 写池" if not a.apply else
              "  2. (失败项仍待用户核实; 已验号新号已写池)")
    elif not a.apply:
        print("  1. 报告给用户确认后, 重跑加 --apply 写池")
    if a.apply:
        print(f"  3. py -3.11 scripts/backfill_xpool_profile.py --handles {handles_csv or '<新号csv>'}")
        print("  4. py -3.11 scripts/sync_seeds.py")
        print("  5. 文档登记: global-news-sources/docs/X账号录入规范.md 末尾追加批次小节+总表行(含 uid)")
        print("  6. git 提交推送 + 云端: ssh ubuntu@43.135.25.178 'cd ~/ai-auto-gen && git pull --ff-only'")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="X 账号录入 intake(提取/校验/去重/验号/预分类/报告)")
    ap.add_argument("list_file", help="用户原始清单文件(任意格式粘贴, 保真不改写)")
    ap.add_argument("--apply", action="store_true", help="验号通过的新号写回池文件(缺省只打印报告)")
    ap.add_argument("--batch", default="手工录入批次", help="登记卡 note 的批次标签")
    ap.add_argument("--pool", default=str(POOL), help="池文件路径(缺省 twitter_pool.yaml)")
    a = ap.parse_args(argv)

    pool_path = Path(a.pool)
    src = Path(a.list_file)
    if not pool_path.is_file():
        print(f"[fail] 池文件不存在: {pool_path}")
        return 3
    if not src.is_file():
        print(f"[fail] 清单文件不存在: {src}")
        return 3
    date = datetime.date.today().isoformat()

    # ①提取+校验 ②清单内去重 ③池 handle 查重(先行跳过, 省网络)
    try:
        text = src.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = src.read_text(encoding="utf-8-sig")
    pool = load_pool(pool_path)
    hs, uids = pool_index(pool)
    cands, parse_fails, skipped = extract_handles(text)
    kept, in_dupes = dedup_in_list(cands)
    fresh, dupes = [], []
    for h, no in kept:
        k = h.lower()
        if k in hs:
            dupes.append((h, f"与池内已有 handle 重复(池内写作 @{hs[k]}), 跳过"))
        else:
            fresh.append((h, no))

    # 逐号验号(429 全局熔断; uid 撞车拒绝录入)
    verified, failed, stop, done = {}, list(parse_fails), False, set()
    for h, _no in fresh:
        done.add(h)
        try:
            prof = verify_one(h)
        except RateLimited:
            stop = True
            print(f"  [429] @{h} 触发限流, 本轮到此为止(重跑幂等续传)")
            break
        except NotFound:
            failed.append({"line": None, "raw": f"@{h}", "cand": h,
                           "reason": "404: 注销或拼错(事故2 同款), 交用户核实, 不猜"})
            print(f"  [404] @{h}")
        except RuntimeError as e:
            msg = str(e)
            if msg.startswith("http_500"):
                msg += "(疑似私密账号, 参见录入规范第八节)"
            failed.append({"line": None, "raw": f"@{h}", "cand": h, "reason": msg})
            print(f"  [fail] @{h}: {msg[:90]}")
        except Exception as e:
            failed.append({"line": None, "raw": f"@{h}", "cand": h,
                           "reason": f"{type(e).__name__}: {str(e)[:80]}"})
            print(f"  [fail] @{h}: {type(e).__name__}: {str(e)[:80]}")
        else:
            uid = prof["uid"]
            if uid in uids:
                dupes.append((h, f"uid 撞车: 池内 @{uids[uid]} 已是 uid={uid}, "
                                 f"疑似改名/同人, 先人工合并再录(红线)"))
                print(f"  [uid撞车] @{h} uid={uid} → 池内 @{uids[uid]}")
            else:
                verified[h] = prof
                uids[uid] = h
                print(f"  [ok] @{h} uid={uid} {prof['name'][:24]} "
                      f"粉丝{(prof['followers'] or 0) // 10000}万")
        time.sleep(FETCH_SLEEP)
    pending = [h for h, _no in fresh if h not in done]

    # ④预分类 → 登记卡
    cards = [build_card(h, verified[h], a.batch, date) for h, _no in fresh if h in verified]

    # --apply: 写前重读池再查重(防并发变更), 文本级追加 + 原子写 + yaml 自查
    if a.apply and cards:
        try:
            pool_text = pool_path.read_text(encoding="utf-8")
            hs2, uids2 = pool_index(load_pool(pool_path))
        except Exception as e:
            print(f"[fail] 写前读池失败: {type(e).__name__}: {str(e)[:120]}")
            return 3
        final = []
        for c in cards:
            k = c["handle"].lower()
            if k in hs2:
                dupes.append((c["handle"], "写池时发现与池 handle 重复(并发变更), 跳过"))
                continue
            if c["uid"] in uids2:
                dupes.append((c["handle"], f"写池时 uid 撞车(池内 @{uids2[c['uid']]}), 拒绝录入"))
                continue
            final.append(c)
        if not final:
            print("[apply] 无可写新号(全部重复跳过), 池文件未改动")
        else:
            try:
                atomic_write(insert_cards(pool_text, final), pool_path)
            except Exception as e:
                print(f"[fail] 写池失败(池文件未变更或已自查拦截): {type(e).__name__}: {str(e)[:160]}")
                return 3
            print(f"[apply] 已写池 {len(final)} 个账号 → {pool_path} (文本级追加+原子写+yaml 自查通过)")
        cards = final

    uid_clash_n = sum(1 for _h, why in dupes if "uid 撞车" in why)
    _print_report(a, src, date,
                  {"cands": len(cands), "parse_fails": len(parse_fails), "skipped": skipped,
                   "pool_dups": sum(1 for h, _ in kept if h.lower() in hs),
                   "uid_dups": uid_clash_n},
                  cards, in_dupes, dupes, failed, pending)
    if stop:
        return 3
    # uid 撞车与失败清单一样需人工(合并/核实) → 都归 exit 2
    return 2 if (failed or uid_clash_n) else 0


if __name__ == "__main__":
    sys.exit(main())
