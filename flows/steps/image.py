"""长图产物步骤: 文章+解读标签 → 图条精简(JSON) → Pillow 长图(按需生成)。"""

import json
import re
import sys
from pathlib import Path

from flows.steps import step

# 分类配额(v1): 图条上限 image_top 在此配额内截断
QUOTA = {"宏观政策": 3, "公司动态": 4, "行业产业": 3, "海外市场": 2, "大宗商品": 2, "公司公告": 2}

# 头部行情速览: 前一交易日收盘指数(新浪免费接口, s_/int_/znb_ 三系列)
INDEX_FEED = [
    ("A股", [("上证指数", "s_sh000001"), ("深证成指", "s_sz399001"), ("创业板指", "s_sz399006")]),
    ("美股", [("道琼斯", "int_dji"), ("纳斯达克", "int_nasdaq"), ("标普500", "int_sp500")]),
    ("日韩", [("日经225", "int_nikkei"), ("韩国KOSPI", "znb_KOSPI")]),
]


def _fetch_indices() -> list:
    """新浪指数行情 → [{group, name, pct}]; 失败返回 [](头部行情区静默跳过)。
    组标签按抓取时刻判定盘中/昨收(标签随 payload 固化, 复跑历史不漂移):
    早报常规 08:30 跑 → A股/美股=昨收, 日韩(北京08:00开盘)=今晨盘中。"""
    import datetime
    import requests
    codes = [c for _, items in INDEX_FEED for _, c in items]
    now = datetime.datetime.now()
    h = now.hour + now.minute / 60
    wd = now.weekday()

    def _label(group: str) -> str:
        if group == "A股":
            intraday = wd < 5 and 9.5 <= h < 15
        elif group == "美股":                       # 夏令时口径(冬令时顺延1h, 仅影响凌晨窗口)
            intraday = wd < 5 and (h >= 21.5 or h < 4.5)
        else:                                       # 日韩(北京08:00开盘): 08:30跑批=今晨开盘方向
            intraday = wd < 5 and 8.0 <= h < 15
        if group == "日韩":
            return "日韩·今晨" if intraday else "日韩·昨收"
        return f"{group}·盘中" if intraday else f"{group}·昨收"

    try:
        r = requests.get("https://hq.sinajs.cn/list=" + ",".join(codes),
                         headers={"Referer": "https://finance.sina.com.cn"}, timeout=8)
        r.encoding = "gbk"
        vals = dict(re.findall(r'hq_str_(\w+)="([^"]*)"', r.text))
        out = []
        for group, items in INDEX_FEED:
            row = []
            for name, code in items:
                parts = (vals.get(code) or "").split(",")
                if len(parts) >= 4:                    # 名称,点位,涨跌额,涨跌幅
                    row.append({"name": name, "pct": parts[3].strip()})
            if row:
                out.append({"group": _label(group), "items": row})
        if not out:
            print("⚠ 指数行情接口无有效数据, 头部行情区跳过")
        return out
    except Exception as e:
        print(f"⚠ 指数行情获取失败({e}), 头部行情区跳过")
        return []


@step("render_morning_image")
def render_morning_image(ctx, wf, params):
    """文章+↳解读行 → 选条配额 → LLM 精简(title/point/hot) → 数字保真机检 → 长图 PNG。
    with: {top: 16, refine: true}。失败降级纯截断版。产出 image_path。"""
    import daily
    from common import llm_complete, load_cfg, GEN_ROOT
    date = wf.date
    article_p = ctx.get("article_path") or ctx.get("tagged_path")
    if not article_p or not Path(article_p).exists():
        sys.exit("长图依赖文章产物: 需 format=article (--set format=article)")
    article = Path(article_p).read_text(encoding="utf-8")
    items, ann_zone = _index_with_tags(article)
    if len(items) < 6:
        sys.exit(f"文章条目过少({len(items)}), 疑似格式异常")

    # ---- 选条(两轮制: 配额内优先带解读的条, 免标条补位; 文章顺序即重要性序) ----
    top = int(params.get("top", 16))
    quota_left = {k: v for k, v in QUOTA.items()}
    picked = {}
    for it in items:                                 # 第一轮: 有解读(板块)的条优先占配额
        c = it["cat"]
        if it.get("sectors") and quota_left.get(c, 0) > 0:
            picked[it["n"]] = it
            quota_left[c] -= 1
    for it in items:                                 # 第二轮: 免标条按序补足配额
        c = it["cat"]
        if not it.get("sectors") and quota_left.get(c, 0) > 0:
            picked[it["n"]] = it
            quota_left[c] -= 1
    for it in items:                                 # 余量按序补到 top
        if len(picked) >= top:
            break
        picked.setdefault(it["n"], it)
    sel = [it for it in items if it["n"] in picked]  # 保持文章顺序
    n_tagged = sum(1 for it in sel if it.get("sectors"))
    print(f"长图选条: {len(sel)}/{len(items)} 条, 带解读 {n_tagged} 条 (配额 {QUOTA})")

    # ---- LLM 精简(title/point/pill/hot) ----
    refined, degraded = {}, False
    import yaml
    sf = Path(wf.pack_dir) / "sectors.yaml"
    groups = (yaml.safe_load(sf.read_text(encoding="utf-8")) or {}).get("sectors") or []
    vocab = [w for g in groups for w in g]
    if params.get("refine", True):
        feed = chr(10).join(f"{it['n']}|{it['tag']}|{it['text']}" for it in sel)
        tpl = daily.load_prompt("morning_image_lines")
        if tpl:
            user = (tpl.replace("<<DATE>>", date).replace("<<SECTORS>>", "、".join(vocab))
                       .replace("<<ITEMS>>", feed))
            system = daily.load_prompt("morning_image_lines_system",
                                       "你是财经长图编辑,只输出严格 JSON。")
            raw = llm_complete(user, system=system, max_tokens=2500, temperature=0.2)
            refined, err = _parse_lines(raw, {it["n"]: it["text"] for it in sel}, vocab)
            if err:
                print(f"⚠ 精简校验失败({err}), 重试一次 ...")
                raw = llm_complete(user, system=system, max_tokens=2500, temperature=0.2)
                refined, err = _parse_lines(raw, {it["n"]: it["text"] for it in sel}, vocab)
            if err:
                print(f"⚠ 降级为纯截断版({err})")
                refined, degraded = {}, True
        else:
            degraded = True

    # ---- payload 组装(分类/板块/方向全代码合成) ----
    cards = []
    for it in sel:
        r = refined.get(it["n"]) or {}
        if r:
            title, point, hot = r["title"], r["point"], r.get("hot", False)
        else:                                         # 降级: 数字/标点边界截断
            title = _cut(it["text"], 14)
            point = _cut(it["text"], 30)
            hot = False
        card = {"n": it["n"], "cat": it["cat"], "tag": it["tag"], "title": title,
                "point": point, "hot": hot, "pill": r.get("pill", ""),
                "sectors": it.get("sectors") or [], "direction": it.get("direction") or ""}
        cards.append(card)
    ann_count = {}                                    # 公告热度=全部公告条目, 非仅选中
    for it in items:
        if it["n"] in ann_zone:
            for s_ in it.get("sectors") or []:
                ann_count[s_] = ann_count.get(s_, 0) + 1
    # 焦点: 头部看点取焦点区条目前 24 字
    focus = _focus_lines(article)

    ann_summary = sorted(ann_count.items(), key=lambda x: -x[1])[:8]
    payload = {"date": date, "degraded": degraded, "indices": _fetch_indices(),
               "focus": focus, "cards": cards, "ann_summary": ann_summary}

    # ---- 机检: 字数/数字保真/禁词 ----
    report = _lint_lines(payload, {it["n"]: it["text"] for it in sel})
    payload["lint"] = report
    run_dir = wf.run_dir
    payload_path = run_dir / f"image-digest-{date}.json"
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")

    # ---- 渲染 ----
    sys.path.insert(0, str(GEN_ROOT))
    from image_digest import render_digest_image
    out_cfg = (load_cfg().get("output") or {}).get("images_dir", "../autopub/images")
    out_dir = Path(out_cfg) if Path(out_cfg).is_absolute() else GEN_ROOT / out_cfg
    out = str(out_dir / f"早报长图-{date}.png")
    render_digest_image(payload, date, out)
    print(f"长图: {out} ({len(cards)}卡 {'[降级版]' if degraded else ''})")
    print(f"图条存档: {payload_path} (改版式可离线重渲染)")
    if report["fail"]:
        sys.exit(f"长图机检未过: {report['fail']} (产物已存, 修提示词后 --from image 重跑)")
    return {"image_path": out, "image_digest_path": str(payload_path),
            "image_cards": len(cards)}


def _index_with_tags(article: str):
    """终稿文章 → 条目(含 ↳ 解读行的板块/方向继承)。零错位: 解读行物理紧跟条目。"""
    lines = article.splitlines()
    items, ann = [], []
    zone = None
    i = 0
    while i < len(lines):
        m = re.match(r"^## (.+)", lines[i])
        if m:
            zone = m.group(1).strip()
            i += 1
            continue
        m = re.match(r"^- \*\*([^*]+)\*\*：(.*)", lines[i])
        if m and zone and zone != "今日焦点":
            n = len(items) + 1
            it = {"n": n, "cat": zone, "tag": m.group(1), "text": m.group(2)}
            if zone == "公司公告":
                ann.append(n)
            # 紧随的 ↳ 行(方向模式)
            j = i + 1
            while j < len(lines) and lines[j].lstrip().startswith("↳"):
                dm = re.match(r"^\s*↳ (利好|利空|中性|承压|关注)：(.+)", lines[j])
                if dm:
                    it["direction"] = dm.group(1)
                    it["sectors"] = [x for x in re.split("[、·]", dm.group(2)) if x]
                j += 1
            i = j
            items.append(it)
            continue
        i += 1
    return items, ann


def _focus_lines(article: str) -> list:
    focus, zone = [], None
    for line in article.splitlines():
        m = re.match(r"^## (.+)", line)
        if m:
            zone = m.group(1).strip()
            continue
        m = re.match(r"^- \*\*[^*]+\*\*：(.*)", line)
        if m and zone == "今日焦点":
            t = re.sub(r"[*]", "", m.group(1))
            focus.append(t[:24] + ("…" if len(t) > 24 else ""))
            if len(focus) >= 3:
                break
    return focus


def _cut(text: str, n: int) -> str:
    """数字/标点边界截断(降级用)。"""
    t = text.strip()
    if len(t) <= n:
        return t
    cut = t[:n]
    for sep in ("；", ";", "，", ",", "。", "："):
        i = cut.rfind(sep)
        if i > n // 2:
            return cut[:i]
    return cut.rstrip("，,、") + "…"


def _parse_lines(raw: str, src: dict, vocab: list):
    """解析 LLM 精简 JSON + 数字保真硬校验。返回 ({n: rec}, err)。"""
    m = re.search(r"\{.*\}", raw.strip(), re.S)
    if not m:
        return None, "无 JSON"
    try:
        data = json.loads(m.group(0))
    except Exception as e:
        return None, f"解析失败: {e}"
    out = {}
    for o in data.get("items") or []:
        n = o.get("n")
        if not isinstance(n, int) or n not in src:
            continue
        title, point = str(o.get("title") or ""), str(o.get("point") or "")
        if not title or not point:
            continue
        bad_num = _num_violation(title + point, src[n])
        if bad_num:
            return None, f"#{n} 数字失真: {bad_num}"
        raw_pill = str(o.get("pill") or "")
        if raw_pill in ("-", ""):
            pill = "-"                               # 显式无主体: 不回退影响板块
        elif raw_pill in vocab:
            pill = raw_pill
        else:                                        # 表外词: 交渲染层回退链
            pill = ""
        out[n] = {"title": title, "point": point, "pill": pill, "hot": bool(o.get("hot"))}
    if not out:
        return None, "无有效条目"
    return out, ""


def _num_violation(out_text: str, src_text: str) -> str:
    """输出里的每个数字串必须逐字出现在原文。"""
    for num in re.findall(r"\d+(?:\.\d+)?", out_text):
        if num not in src_text:
            return num
    return ""


def _lint_lines(payload: dict, src: dict) -> dict:
    fail, warn = [], []
    banned = re.compile(r"买入|卖出|建仓|抄底|目标价|上车|布局")
    for c in payload["cards"]:
        if len(c["title"]) > 16:
            fail.append(f"#{c['n']} title 超16字")
        if not payload.get("degraded") and not (12 <= len(c["point"]) <= 34):
            warn.append(f"#{c['n']} point {len(c['n'] and c['point'])}字")
        bad = _num_violation(c["title"] + c["point"], src.get(c["n"], ""))
        if bad:
            fail.append(f"#{c['n']} 数字失真: {bad}")
        if banned.search(c["title"] + c["point"]):
            fail.append(f"#{c['n']} 禁词")
    return {"fail": fail, "warn": warn}
