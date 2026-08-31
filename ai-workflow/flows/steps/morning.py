"""早报汇总步骤:抓四源早报(当日校验) → LLM 汇总分类(素材) → 按产出形式渲染(文章等)。"""

import json
import re
import sys
from pathlib import Path

from flows.steps import step


@step("fetch_morning_reports")
def fetch_morning_reports(ctx, wf, params):
    """十四份早报源走 peers 聚合 + 华尔街见闻单独。
    只保留「今天」发布的早报(防昨日早报被当今日素材误发), 非当日源计入 failed。
    with: {wscn_count: 2, allow_stale: false, peer_sources: "空=全部; 逗号分隔源名=只抓指定"}
    产出 reports(list)/failed。"""
    import extra as extra_sources
    import basic as gs          # fetchers/basic.py(fetch_wscn_breakfast 在这)
    only = _split_names(params.get("peer_sources"))     # --set peer_sources=鉅亨台股,AA英文晨报 只抓指定源
    refs, failed = extra_sources.fetch_peer_mornings(only=only)
    if only and "华尔街见闻早餐" not in only:
        wscn = []               # 选取模式未点名见闻 → 跳过
    else:
        try:
            wscn = gs.fetch_wscn_breakfast(int(params.get("wscn_count", 2)))
            refs.extend(wscn)
            if not wscn:
                failed.append("华尔街见闻早餐(空结果)")
        except Exception as e:
            failed.append(f"华尔街见闻早餐({type(e).__name__}: {str(e)[:60]})")
    if not refs:
        sys.exit("四份早报源全部失败, 无素材可合成")

    if not params.get("allow_stale"):
        fresh, stale = [], []
        for r in refs:
            t = (r.get("time") or "").strip()[:10]
            (fresh if t == wf.date else stale).append(r)
        for r in stale:
            rt = (r.get("time") or "").strip()[:10]
            failed.append(f"{r.get('source')}({rt and '非当日' or '无时间'}: {rt or '?'}, "
                          f"预计发布时间未到或源异常)")
        if not fresh:
            sys.exit(f"没有当日({wf.date})早报, 拒绝用旧素材合成(强跑加 --set allow_stale=true)。"
                     f"缺: {', '.join(failed)}")
        refs = fresh

    ok_names = "、".join(r.get("source", "?") for r in refs)
    print(f"当日早报源就绪 {len(refs)} 份: {ok_names}"
          + (f" | 缺: {', '.join(failed)}" if failed else ""))
    return {"reports": refs, "failed": failed}


@step("synthesize_morning")
def synthesize_morning(ctx, wf, params):
    """LLM 汇总分类, 产出「知识素材」(带来源标注的完整底稿, 存 run_dir 不进发布队列)。
    提示词: 包内 prompts/morning_synth.md(必须存在, 缺失即报错——防格式静默降级)。"""
    import daily
    from common import llm_complete
    date, reports = wf.date, ctx.get("reports", [])
    per = int(params.get("per_report_chars", 6000))

    feed = "\n\n".join(
        f"【{r.get('source') or r.get('media', '?')}】《{r.get('title', '')}》"
        f"({r.get('time', '')})\n{(r.get('text') or '')[:per]}"
        for r in reports)

    tpl = daily.load_prompt("morning_synth")
    if not tpl:
        sys.exit("缺少提示词 morning_synth(包内 prompts/ 或全局 flows/prompts/ 必须提供)")
    user = tpl.replace("<<DATE>>", date).replace("<<REPORTS>>", feed)
    system = daily.load_prompt(
        "morning_synth_system", "你是资深财经早报编辑,只输出 Markdown 正文,不加解释。")

    print(f"汇总素材: {len(reports)} 份早报 / 送模型 {len(user)} 字 ...")
    material = _llm_call(user, system, params, max_tokens=8000, temperature=0.2)
    _check_complete(material, "素材")
    path = wf.run_dir / f"material-{date}.md"
    path.write_text(material.rstrip() + "\n", encoding="utf-8")
    print(f"知识素材: {path} ({len(material)}字)")
    return {"material_path": str(path), "material_chars": len(material)}


@step("render_morning_article")
def render_morning_article(ctx, wf, params):
    """素材 → 早报文章(面向读者的成品): 每条「标签:详情」精炼格式、去来源标注, 进待发队列。
    提示词: 包内 prompts/morning_article.md(必须存在)。产出 article_path。"""
    import daily
    from common import llm_complete, out_dir, save_text
    date = wf.date
    material = ctx.get("material_path")
    if not material or not Path(material).exists():
        sys.exit("缺少素材(先跑 synth 步骤)")
    content = Path(material).read_text(encoding="utf-8")

    tpl = daily.load_prompt("morning_article")
    if not tpl:
        sys.exit("缺少提示词 morning_article(包内 prompts/ 必须提供)")
    user = tpl.replace("<<DATE>>", date).replace("<<MATERIAL>>", content)
    system = daily.load_prompt(
        "morning_article_system", "你是资深财经早报编辑,只输出 Markdown 正文,不加解释。")

    print(f"渲染文章: 素材 {len(content)} 字 → 精炼改写 ...")
    md = _llm_call(user, system, params, max_tokens=6500, temperature=0.3)
    # 半角冒号 → 全角(kimi-k3 等模型会漂格式; 下游索引/机检只认全角)
    # 替换串必须 raw string: 普通串里 "\1" 是 \x01 控制符, 会把标签段整个吞掉(2026-08-30 实测踩中)
    md = re.sub(r"^(- \*\*[^*]+\*\*):(?=[^:])", r"\1：", md, flags=re.M)
    _check_complete(md, "文章")
    md = _inject_indices(md)                       # 开头行情速览(接口数据, 块引用行)
    report = _lint_article(md)
    path = save_text(out_dir("articles_dir") / f"早报文章-{date}.md", md)
    print(f"早报文章: {path} ({len(md)}字)")
    if report["fail"]:
        sys.exit(f"文章机检未过: {report['fail']} (产物已存 {path}, 修提示词后 --from article 重跑)")
    return {"article_path": str(path), "article_chars": len(md),
            "lint": {"items": report["items"], "short": report["short"],
                     "bad_tags": report["bad_tags"]}}


# ---------- 解读标签(tag 步): LLM 出 JSON, 代码渲染插行 ----------

DIRECTIONS = ["利好", "利空", "中性", "承压", "关注"]


def _split_names(v) -> list:
    """逗号/空白分隔的源名参数 → 列表; 空= None(不选取, 全部)。"""
    s = str(v or "").strip()
    return ([x for x in re.split(r"[,，\s]+", s) if x] or None) if s else None


def _load_sectors(pack_dir: Path) -> list:
    """板块词表: 包内 sectors.yaml(单一来源, 用户可直接改)。"""
    import yaml
    f = Path(pack_dir) / "sectors.yaml"
    if not f.exists():
        sys.exit(f"缺少板块词表: {f}")
    groups = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("sectors") or []
    return [w for g in groups for w in g]


def _llm_call(user: str, system: str, params: dict, max_tokens: int, temperature: float) -> str:
    """模型分发(common.gen_llm): ark:<模型名>=方舟订阅, 失败降 kimi 官方API(配key才启用)再降默认通道;
    空=生成链默认 kimi-k3(data/config.local.yaml 的 gen_model 可覆盖)。"""
    from common import gen_llm
    return gen_llm(str(params.get("model", "")), user, system, max_tokens, temperature)


def _ark_complete(user: str, system: str, model: str, max_tokens: int = 16384) -> str:
    """ark 系模型走 arkcli CLI(火山订阅额度, 模型可用 ark: 前缀切换)。
    11 模型横评(2026-08-29)推荐序: kimi-k3 > doubao-seed-2-1-turbo > glm-5-3-flash。
    失败抛异常, 由调用方降级回默认 llm_complete。"""
    import json as _json
    import shutil
    import subprocess
    from pathlib import Path as _P
    # 绕开 npm .cmd 垫片(cmd.exe 命令行 8191 上限装不下 13k 字任务文本):
    # 垫片本质 = node <npm>/node_modules/@volcengine/ark-cli/scripts/run.js <args>,
    # node.exe 是真 exe, CreateProcess 32k 字符上限足够
    exe = shutil.which("arkcli")
    if not exe:
        raise RuntimeError("arkcli 不在 PATH, 无法走 ark 通道")
    js = _P(exe).parent / "node_modules" / "@volcengine" / "ark-cli" / "scripts" / "run.js"
    if not js.exists():
        raise RuntimeError(f"arkcli 入口未找到: {js}")
    node = shutil.which("node") or "node"

    def _call(extra: list) -> dict:
        cmd = [node, str(js), "+chat", "--no-progress", "--model", model,
               "--instructions", system, *extra,
               "--max-output-tokens", str(max_tokens), user]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=900)
        except FileNotFoundError:
            raise RuntimeError("arkcli 不在 PATH, 无法走 ark 通道")
        out = r.stdout.decode("utf-8", "replace").strip()
        if not out:
            raise RuntimeError(f"arkcli 无输出: {r.stderr.decode('utf-8', 'replace')[:200]}")
        try:
            d = _json.JSONDecoder().raw_decode(out)[0]      # 截掉尾部版本提示
        except Exception:
            raise RuntimeError(f"arkcli 输出异常: {out[:150]}")
        if d.get("ok") is False:
            raise RuntimeError(f"arkcli 错误: {str((d.get('error') or {}).get('message'))[:200]}")
        return d

    d = _call(["--reasoning-effort", "low"])
    if not d.get("content"):
        # 思考模型的推理链会吃光输出预算(k3 长 JSON 任务实测踩中): 关思考重试一次
        print(f"  [ark] {model} content 为空, 关思考重试")
        d = _call(["--thinking", "disabled"])
    if not d.get("content"):
        raise RuntimeError(f"ark {model} content 为空(关思考重试仍空)")
    print(f"  [ark] {d.get('model')} tokens={(d.get('usage') or {}).get('total_tokens')}")
    return d["content"]


def _restore_raw(wf, ctx) -> None:
    """把待发队列的文章还原为无解读干净稿(raw_backup 优先, 否则剥离 ↳ 行)。"""
    article_p = ctx.get("article_path")
    if not article_p or not Path(article_p).exists():
        return
    raw_backup = wf.run_dir / f"article-raw-{wf.date}.md"
    if raw_backup.exists():
        Path(article_p).write_text(raw_backup.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        txt = Path(article_p).read_text(encoding="utf-8")
        if chr(0x21B3) in txt:
            txt = chr(10).join(l for l in txt.splitlines()
                               if not l.lstrip().startswith(chr(0x21B3)))
            Path(article_p).write_text(txt, encoding="utf-8")


@step("tag_morning_items")
def tag_morning_items(ctx, wf, params):
    """成品文章 → 逐条「板块×方向」解读标签。
    LLM 只出结构化 JSON, 解析/校验/插行全部由代码完成(排版是构造性保证)。
    with: {enabled: true}。产出 tagged_path/tags_path。"""
    import daily
    from common import llm_complete
    if not params.get("enabled", True):
        print("解读标签未启用(--set tag_lines=false)")
        _restore_raw(wf, ctx)                     # 回退干净稿(上轮解读不再滞留队列)
        return {}
    article_p = ctx.get("article_path")
    if not article_p or not Path(article_p).exists():
        sys.exit("缺少文章产物(先跑 article 步骤)")
    # 永远从「无解读原文」出发: 队列文件可能已带上一轮解读(换模式重跑会叠加)
    raw_backup = wf.run_dir / f"article-raw-{wf.date}.md"
    if raw_backup.exists():
        article = raw_backup.read_text(encoding="utf-8")
    else:
        article = Path(article_p).read_text(encoding="utf-8")
    # 幂等防御: 输入若已被历史轮次污染(带 ↳ 解读行), 先剥离还原为无解读原文
    if chr(0x21B3) in article:
        article = chr(10).join(l for l in article.splitlines() if not l.lstrip().startswith(chr(0x21b3)))
        m = re.search(r"^(本文[^{}]*投资建议[^{}]*)$".format(chr(92)+chr(110), chr(92)+chr(110)), article, re.M)
        if m:
            article = article.replace(m.group(1),
                "本文基于公开信息整理,不构成投资建议。市场有风险,投资需谨慎。")
        print("⚠ 输入含历史解读行, 已剥离还原为无解读原文(幂等)")
    material = ""
    mp = ctx.get("material_path")
    if mp and Path(mp).exists():
        material = Path(mp).read_text(encoding="utf-8")

    sectors = _load_sectors(wf.pack_dir)
    mode = "sectors" if str(params.get("mode", "direction")) == "sectors" else "direction"
    items, ann_zone = _index_items(article)          # 编号条目 + 公告区定位
    if not items:
        sys.exit("文章里没找到可打标的条目(格式异常?)")

    tpl = daily.load_prompt("morning_tags_sectors" if mode == "sectors" else "morning_tags")
    if not tpl:
        sys.exit(f"缺少提示词 (mode={mode})")
    user = (tpl.replace("<<DATE>>", wf.date)
               .replace("<<ARTICLE>>", article)
               .replace("<<MATERIAL>>", material[:12000])
               .replace("<<SECTORS>>", "、".join(sectors)))
    system = daily.load_prompt("morning_tags_system",
                               "你是量化资讯编辑,只输出严格 JSON。")
    print(f"解读标签[{mode}]: {len(items)} 条正文条目 / 送模型 {len(user)} 字 ...")
    m_model = str(params.get("model", "")).strip()

    def _call() -> str:
        from common import gen_llm
        return gen_llm(m_model, user, system, 4000, 0.2)

    raw = _call()
    parsed, err = _parse_tags(raw, sectors, items, mode)
    if err and not err.startswith("表外词"):
        print(f"⚠ JSON 校验失败({err}), 重试一次 ...")
        raw = _call()
        parsed, err = _parse_tags(raw, sectors, items, mode)
    if err:
        print(f"⚠ 解读标签失败({err}), 降级发布无解读版")
        _restore_raw(wf, ctx)                     # 真正还原无解读原稿
        return {"tagged_path": article_p, "tag_error": err}

    if err and err.startswith("表外词"):
        cand = wf.run_dir / f"tag-candidates-{wf.date}.txt"
        cand.write_text(err.replace("表外词(已回退丢弃): ", "") + "\n", encoding="utf-8")
        print(f"⚠ {err} → 已记入 {cand.name} (周审入表)")
    tagged, report = _render_tags(article, items, ann_zone, parsed, sectors, mode)
    # 备份无解读原稿 + 覆盖待发版
    raw_backup = wf.run_dir / f"article-raw-{wf.date}.md"
    raw_backup.write_text(article, encoding="utf-8")
    Path(article_p).write_text(tagged, encoding="utf-8")
    (wf.run_dir / f"tag-{wf.date}.json").write_text(
        json.dumps({"items": parsed, "lint": report}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"解读标签: {report['tagged']}/{len(items)} 条已标注 | 公告汇总: {report['ann_summary'] or '无'}")
    if report["fail"]:
        sys.exit(f"解读标签机检未过: {report['fail']}")
    return {"tagged_path": article_p, "tags_path": str(wf.run_dir / f"tag-{wf.date}.json"),
            "tag_report": report}


def _index_items(article: str):
    """给正文六分类条目编号。返回 ([{n,line,tag,text}], 公告区条目n列表)。"""
    items, ann = [], []
    zone = None
    for i, line in enumerate(article.splitlines()):
        m = re.match(r"^## (.+)", line)
        if m:
            zone = m.group(1).strip()
            continue
        m = re.match(r"^- \*\*([^*]+)\*\*[：:](.*)", line)
        if m and zone and zone != "今日焦点":
            n = len(items) + 1
            items.append({"n": n, "line": i, "tag": m.group(1), "text": m.group(2)})
            if zone == "公司公告":
                ann.append(n)
    return items, ann


def _parse_tags(raw: str, sectors: list, items: list, mode: str = "direction"):
    """解析+硬校验 LLM JSON。返回 (清理后的 items 映射, 错误)。"""
    import json as _j
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.S)            # 容错: 剥多余文本
    if not m:
        return None, "输出里没有 JSON"
    try:
        data = _j.loads(m.group(0))
    except Exception as e:
        return None, f"JSON 解析失败: {e}"
    valid_n = {it["n"] for it in items}
    secset, out, outside = set(sectors), {}, set()
    for o in data.get("items") or []:
        n = o.get("n")
        if not isinstance(n, int) or n not in valid_n:
            continue                                  # 越界编号直接丢弃
        if mode == "sectors":                         # 纯板块: {"n":1,"s":["芯片","AI"]}
            ss = [x for x in dict.fromkeys(o.get("s") or []) if x in secset]
            outside.update(x for x in (o.get("s") or []) if x not in secset)
            if ss:
                dirs = [{"d": "", "s": ss[:3]}]       # 条目级总量截断
                out.setdefault(n, []).extend(
                    x for x in dirs if x not in out.get(n, []))
            continue
        for d in o.get("dirs") or []:                 # 重复 n 合并而非覆盖
            key = d.get("d")
            ss = [x for x in dict.fromkeys(d.get("s") or []) if x in secset]
            outside.update(x for x in (d.get("s") or []) if x not in secset)
            if key in DIRECTIONS and ss:
                out.setdefault(n, []).append({"d": key, "s": ss})
    # 每条板块总量截断到 3
    for n, dirs in out.items():
        flat, keep = [], []
        for d in dirs:
            take = [x for x in d["s"] if x not in flat][:3 - len(flat)]
            if take:
                keep.append({"d": d["d"], "s": take})
                flat.extend(take)
        out[n] = keep
    if not out or not any(out.values()):
        return None, "无有效条目"
    return out, (f"表外词(已回退丢弃): {chr(59).join(sorted(outside))}" if outside else "")


def _render_tags(article: str, items: list, ann_zone: list,
                 parsed: dict, sectors: list, mode: str = "direction"):
    """渲染插行(构造性保证格式)。免标规则在此代码侧兜底过滤。"""
    lines = article.splitlines()
    by_tag = {it["n"]: it for it in items}
    fail, warn = [], []
    # 跨方向板块冲突: 整条丢弃(提示词已禁, 此为代码兜底)
    seen_by_n, conflicts = {}, []
    for n, dirs in parsed.items():
        for d in dirs:
            for x in d["s"]:
                if seen_by_n.setdefault((n, x), d["d"]) != d["d"]:
                    conflicts.append(f"#{n} {x}")
    if conflicts:
        warn.append(f"跨方向冲突条目被丢弃: {', '.join(conflicts[:5])}")
        for n in {int(c.split()[0][1:]) for c in conflicts}:
            parsed.pop(n, None)
    inserts = {}          # line_idx -> [解读行...]
    used_dirs = []
    ann_sector_count = {}
    for n, dirs in sorted(parsed.items()):
        it = by_tag[n]
        # 免标兜底: 传闻条不给标签; 行情条免标范围交给提示词纪律(纯指数速览不标,
        # 个股/板块行情正常打板块)——代码无法可靠区分两者, 一刀切会误伤个股行情
        if re.search(r"据报|被曝|据报道|消息人士", it["text"]):
            warn.append(f"#{n} 传闻条被过滤"); continue
        if mode == "direction" and it["tag"] == "地缘":
            dirs = [d for d in dirs if d["d"] in ("中性", "承压", "关注")] or None
            if dirs is None:
                continue                              # 纯板块模式地缘条可标板块
        if it["n"] in ann_zone:
            for d in dirs:                            # 公告条: 收热度
                for s_ in d["s"]:
                    ann_sector_count[s_] = ann_sector_count.get(s_, 0) + 1
            if mode == "direction":                   # 方向模式: 中性公告只进汇总不逐条渲染
                keep = [x for x in dirs if x["d"] != "中性"]
                if not keep:
                    continue
                dirs = keep
        if mode == "sectors":
            rows = [f"  ↳ {'、'.join(s_ for d in dirs for s_ in d['s'])}"]
        else:
            rows = [f"  ↳ {d['d']}：{'、'.join(d['s'])}" for d in dirs
                    if d["d"] in DIRECTIONS]
        if rows:
            inserts.setdefault(it["line"], []).extend(rows)
            used_dirs.extend(d["d"] for d in dirs)
    # 公告区汇总行: 插在公告区最后一条(含其解读行)之后
    if ann_sector_count:
        top = sorted(ann_sector_count.items(), key=lambda x: -x[1])[:6]
        summary = "、".join(f"{s}×{c}" for s, c in top)
        last_ann = max(by_tag[n]["line"] for n in ann_zone if n in by_tag)
        inserts.setdefault(last_ann, []).append(f"  ↳ 今日公告热度：{summary}")
    # 免责升级: 覆盖板块方向归类(合规配套)
    disc = ("本文基于公开信息整理,板块标注仅为信息归类,不构成投资建议。"
            "市场有风险,投资需谨慎。" if mode == "sectors" else
            "本文基于公开信息整理,板块影响标注仅为对消息面的客观归类,"
            "不代表对任何证券或板块走势的预测,不构成投资建议。"
            "市场有风险,投资需谨慎。")
    for i in range(len(lines) - 1, -1, -1):
        if "投资建议" in lines[i]:
            lines[i] = disc
            break
    # 倒序插行
    for idx in sorted(inserts, reverse=True):
        lines[idx + 1:idx + 1] = inserts[idx]
    # 比例监控
    n_dir = 0 if mode == "sectors" else len([d for d in used_dirs if d in ("利好", "利空")])
    if n_dir:
        bull = used_dirs.count("利好") / n_dir
        if bull > 0.8 or bull < 0.3:
            warn.append(f"方向比例失衡: 利好占 {bull:.0%}, 请人工复核")
    # 构造性断言: 每行 ↳ 必须紧跟条目行或 ↳ 行(违反=插行定位 bug, 阻断)
    out_lines = lines
    for i, l in enumerate(out_lines):
        if l.lstrip().startswith(chr(0x21B3)):
            prev = out_lines[i - 1] if i else ""
            if not (prev.startswith("- ") or prev.lstrip().startswith(chr(0x21B3))):
                fail.append(f"解读行悬空于第{i + 1}行")
    n_summary = 1 if ann_sector_count else 0
    if conflicts:
        warn.append(f"跨方向冲突条目被丢弃: {', '.join(conflicts[:5])}")
    report = {"tagged": max(0, len(inserts) - n_summary), "fail": fail, "warn": warn,
              "ann_summary": "、".join(f"{s}×{c}" for s, c in
                                       sorted(ann_sector_count.items(), key=lambda x: -x[1])[:4])}
    return chr(10).join(lines) + chr(10), report


def _inject_indices(md: str) -> str:
    """文章标题下插行情速览(前收数据; 接口失败不阻断, 行情区不出现)。
    块引用行格式, 避开 lint 的条目正则。"""
    from flows.steps.image import _fetch_indices
    import time
    groups = _fetch_indices()
    if not groups:                                   # 接口抖动: 间隔3s重试一次
        time.sleep(3)
        groups = _fetch_indices()
        if not groups:
            print("⚠ 行情接口两次均失败, 文章不含行情速览区")
            return md
    rows = ["## 行情速览", ""]
    for g in groups:
        seg = "｜".join(f"{i['name']} {i.get('price','')}点({i['pct']}%)" for i in g["items"])
        rows.append(f"> {g['group']}：{seg}")
    block = chr(10).join(rows) + chr(10) * 2
    m = re.match("^# [^" + chr(10) + "]+", md)         # 首个一级标题后插入(不带$)
    if m:
        return md[:m.end()] + chr(10) * 2 + block + md[m.end():].lstrip(chr(10))
    return block + md


# ---------- 校验与机检 ----------

def _check_complete(text: str, what: str) -> None:
    """完整性: 长度下限 + 必须以免责声明收尾(截断会让结尾消失)。"""
    if len(text) < 300:
        sys.exit(f"{what}输出过短({len(text)}字), 疑似异常:\n{text[:300]}")
    if "投资建议" not in text[-120:]:
        sys.exit(f"{what}结尾缺少免责声明——疑似 LLM 输出被截断, "
                 "检查 max_tokens 或素材长度后重跑")


TAGS = ["注意", "地缘", "政策", "数据", "公司", "概念", "行情", "事件"]


def _lint_article(md: str) -> dict:
    """成品机检: 标签白名单/全角冒号/来源残留/字数分布。fail 列表非空=阻断。"""
    items = re.findall(r"^- \*\*([^*]+)\*\*([：:])(.*)$", md, re.M)
    bare = len(re.findall(r"^\*\*[^*]+\*\*[：:]", md, re.M))   # 丢了「- 」前缀的条目
    bad_tags = [t for t, _, _ in items if t not in TAGS]
    half_colon = [t for t, c, _ in items if c != "："]
    src_leak = len(re.findall(r"\[(?:财联社|富途|见闻|Gangtise)", md))
    lens = [len(t) + 1 + len(b.strip()) for t, _, b in items]
    short = sum(1 for n in lens if n < 40)          # 下限放宽到 40(公告一行题可短)
    over = sum(1 for n in lens if n > 110)
    fail = []
    if not items:
        fail.append("零可索引条目(格式异常: 条目须为「- **标签**：正文」)")
    if bare:
        pass                       # bare 已在上面收集, 统一在此入 fail
    if bare:
        fail.append(f"条目缺少「- 」列表前缀: {bare} 条")
    if bad_tags:
        fail.append(f"标签白名单外: {bad_tags[:5]}")
    if half_colon:
        fail.append(f"半角冒号条目: {len(half_colon)}")
    if src_leak:
        fail.append(f"来源标注残留: {src_leak} 处")
    print(f"机检: {len(items)} 条 | 标签分布 " +
          " ".join(f"{t}:{sum(1 for x,_,_ in items if x==t)}" for t in TAGS
                   if any(x == t for x, _, _ in items)) +
          f" | <40字 {short} 条, >110字 {over} 条")
    return {"items": len(items), "short": short, "over": over,
            "bad_tags": bad_tags, "fail": fail}