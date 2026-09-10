"""Deterministic finance review text. No network, model calls or HTTP writes."""
import re
from pathlib import Path


DISCLAIMERS = {
    "regulatory": "本内容依据公开司法、监管资料整理，仅供方法讨论，不构成投资建议；案件事实与进展以官方通报及判决文书为准。",
    "ipo": "本内容仅整理新股发行与基本面公开资料，不构成投资建议或申购推荐；融资及发行数据以券商、交易所最新披露为准，参与规模须结合自身风险承受能力判断。",
    "industry": "本内容为公开信息梳理与观点讨论，不构成投资建议或个股推荐；提及公司仅说明产业链位置，不代表经营或股价判断。市场有风险，决策须自行判断。",
}


def content_kind(text: str, style_id: str = "") -> str:
    content = style_id + " " + text
    if re.search(r"司法|监管|法院|判决|证监会|诉讼|regulat", content, re.I):
        return "regulatory"
    if re.search(r"新股|打新|申购|孖展|\bIPO\b", content, re.I):
        return "ipo"
    return "industry"


def disclaimer_for(text: str, style_id: str = "") -> str:
    return DISCLAIMERS[content_kind(text, style_id)]


FINANCE_DISCIPLINE = """
财经合规纪律：
1. 将重仓、满仓、梭哈、抄底等操作与仓位指令改为条件和倾向，参与比例由观众依风险承受能力判断。
2. 将必涨、稳赚、肯定反弹等收益承诺改为“若条件成立，逻辑可能加强”，写出条件，不保证结果。
3. 事实断言要带材料已有的出处主语，例如监管机构认定、公司公告披露；无出处则删除断言或明确“材料声称，尚待核实”，不得编造公告或“网传”出处。
4. 删除涉及在世自然人的未证实转述，包括“据前员工描述”类传闻；可改讲机制，不保留影射细节。
5. 点名公司先说明产业链环节；供应关系缺公开披露依据时仅用“有望受益于”“市场预期”，不得写已进入供应体系。
6. 不用核心标的、首选个股等荐股措辞；有公开依据的事实和有条件的判断可以保留。
7. 保留原稿已有的不构成投资建议声明；口播生成须在正文结尾加入适用的简短免责声明。
8. 输出 JSON 顶层 disclaimer 字符串，按司法监管、新股打新、财报产业链选用下面一种声明，不混淆题材。
9. 核查百分比、金额、基点、日期的主语、单位与时点，不补造数字；无法核实的事项放入 warnings。
10. 分镜阶段已定稿 narration 逐字保留：上述改写仅用于未锁定文本及画面文案；原句违规须写 warnings 提示回第一段修改，不绕过完整性闸门。
11. 不补写材料未提供的行业位置、订单或市场反应；虚构测试材料须保留虚构背景，不能包装成真实财经事实。
12. 正文只给改写后的内容，不复述违规原话、不讲述改稿过程、不解释删掉了什么传闻；禁词、原句与修改说明仅可放 warnings，不能进入口播。
声明模板：
""" + "\n".join(f"{k}: {v}" for k, v in zip(
    ("司法/监管", "新股/打新", "财报/产业链"), DISCLAIMERS.values()))

# Candidate extraction, not entity recognition or fact verification. Include Chinese
# spoken numbers because the narration prompt deliberately spells numbers out.
_N = r"[+-]?(?:\d[\d,]*(?:\.\d+)?|[零〇一二两三四五六七八九十百千万亿点]+)"
NUMBER_FACT = re.compile(
    rf"\d{{4}}[-/]\d{{1,2}}[-/]\d{{1,2}}|(?:{_N}年)?{_N}月(?:{_N}[日号])?"
    rf"|{_N}年|百分之{_N}|{_N}\s*(?:[%％]|万点|亿美元|亿元|万元|万美元|亿|万|个?基点)"
)
TICKER = re.compile(r"(?<![A-Za-z])\$?([A-Z]{1,5}(?:[.-][A-Z]{1,2})?)(?![A-Za-z])")
COMPANY = re.compile(r"[\u4e00-\u9fffA-Za-z]{2,20}(?:股份有限公司|有限公司|集团|公司)")


def publication_window(text: str, style_id: str = "") -> str:
    content = style_id + " " + text
    if re.search(r"截止|倒计时|申购|打新|新股|\bIPO\b", content, re.I):
        return "截止倒计时：先核官方截止时间与时区，截止前发布，过期勿发；可先准备对照图。"
    if re.search(r"财报|业绩|季报|年报|earnings", content, re.I):
        return "财报：披露后约 3 天内，优先当天；发布前复核最新公告与行情。"
    if re.search(r"产业链|供应链|供应体系|industry", content, re.I):
        return "产业链：约 1–2 周，发布前检查点名公司披露是否更新。"
    return "复盘/认知：适合长期复用；再次发布仍需检查事实、案件与数据更新。"


CLAIM_LEVEL_LABELS = {"verified": "已核验（带源）", "opinion": "观点",
                      "pending": "待确认", "high_risk": "高危删改"}
# 渲染顺序：先处理高危与待确认，再看过审的
CLAIM_RENDER_ORDER = ("high_risk", "pending", "verified", "opinion")


def _load_claims(project: Path, script: dict) -> list:
    """事实账本来源：脚本存档里的 claims 字段优先，其次项目目录 claims.json。"""
    claims = script.get("claims") if isinstance(script, dict) else None
    if not isinstance(claims, list) or not claims:
        claims_file = project / "claims.json"
        if claims_file.is_file():
            import json
            try:
                payload = json.loads(claims_file.read_text(encoding="utf-8"))
                claims = (payload or {}).get("claims") if isinstance(payload, dict) else payload
            except Exception:
                claims = None
    if not isinstance(claims, list):
        return []
    out = []
    for item in claims:
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            continue
        level = str(item.get("level") or "").strip().lower()
        if level not in CLAIM_LEVEL_LABELS:
            level = "pending"
        out.append({"text": str(item["text"]).strip(), "level": level,
                    "status": str(item.get("status") or "").strip(),
                    "source": str(item.get("source") or "").strip(),
                    "suggestion": str(item.get("suggestion") or "").strip()})
    return out


def claims_section(claims: list) -> list:
    """分级槽位表：四级分组 + 来源 + 建议核实方式；空账本返回空列表。"""
    if not claims:
        return []

    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")

    lines = ["### claims 事实账本（写稿期 LLM 四级分级，请人工集中裁决）", "",
             "逐字引句来自生成期事实账本，未经独立核实；请先处理高危与待确认，再通读口播。", ""]
    for level in CLAIM_RENDER_ORDER:
        group = [c for c in claims if c["level"] == level]
        lines.append(f"#### {CLAIM_LEVEL_LABELS[level]}（{len(group)} 条）")
        lines.append("")
        if not group:
            lines.append("")
            continue
        lines += ["| 原文引句 | 来源 | 建议核实方式 |", "| --- | --- | --- |"]
        for c in group:
            status = f"[{cell(c['status'])}] " if c["status"] else ""
            lines.append(f"| {status}{cell(c['text'])} | {cell(c['source'] or '—')} "
                         f"| {cell(c['suggestion'] or '—')} |")
        lines.append("")
    return lines


def review_markdown(story: dict, project: Path, script: dict | None = None) -> str:
    script = script or {}
    scenes = story.get("scenes") or []
    text = "\n".join(str(s.get("narration") or "") for s in scenes)
    style = str(script.get("style_id") or "")
    title = str(script.get("title") or story.get("meta", {}).get("title") or project.name)
    lines = [f"# {title} · 发布前核对", "", f"视频工程：{project.resolve()}",
             "成片及字幕：out/final.mp4 / out/subtitles.srt；时间轴与质量报告见同目录。", "",
             "## 一、我改了你原稿的地方", "",
             "本期由确定性模板生成，合规改写已在 prompt 层完成；请在下方逐项核对数字与点名", "",
             "## 二、要你核的数字/事实", "",
             "以下仅从各场 narration 正则提取，未经独立核实；可能漏检或误检。请连同画面数字、口播与字幕核对。", ""]
    claims_lines = claims_section(_load_claims(project, script))
    if claims_lines:
        lines += claims_lines
    lines += ["| 场景 | 数字事实候选 | 原句 |", "| --- | --- | --- |"]
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    found = False
    for scene in scenes:
        narration = str(scene.get("narration") or "")
        for sentence in re.split(r"(?<=[。！？!?])", narration):
            for match in NUMBER_FACT.finditer(sentence):
                found = True
                lines.append(f"| {cell(scene.get('id', ''))} | {cell(match.group())} | {cell(sentence)} |")
    if not found:
        lines.append("| — | 未匹配到数字 | 请人工复核，未匹配不代表没有数字事实 |")
    lines += ["", "### 点名公司 / ticker 候选", "",
              "大写缩写可能并非股票代码，中文名称按公司后缀提取，简称可能漏检；须人工补齐。", "",
              "| 场景 | 名称候选 | 待核 |", "| --- | --- | --- |"]
    named = False
    for scene in scenes:
        narration = str(scene.get("narration") or "")
        names = list(dict.fromkeys(COMPANY.findall(narration) + TICKER.findall(narration)))
        for name in names:
            named = True
            lines.append(f"| {cell(scene.get('id', ''))} | {cell(name)} | 公司身份、披露出处、供应关系及预期措辞 |")
    if not named:
        lines.append("| — | 未匹配到公司名 | 请人工补齐简称及中文品牌名 |")
    lines += ["", "## 三、合规处理", "",
              "生成提示词已要求仓位倾向化、收益条件化、事实加出处、删未证实个人传闻、公司关系区分披露与预期；此文档不证明模型已逐条执行。", "",
              "适用声明：" + disclaimer_for(text, style), ""]
    if script.get("disclaimer"):
        lines += ["脚本声明（需核对适用性）：" + str(script["disclaimer"]), ""]
    lines += ["## 四、传播逻辑", "", publication_window(text, style),
              "定位为公开信息解释与方法讨论；优先复用带出处的对照/检查清单画面。平台与具体顺序由主会话确认。", "",
              "## 五、待确认", "", "| 事项 | 状态 |", "| --- | --- |",
              "| 数字、单位、统计区间、来源与发布日期 | 待人工核对 |",
              "| 所有公司点名、个人信息及预期措辞 | 待人工核对 |",
              "| 免责声明、首帧静帧、字幕与成片试听 | 待人工核对 |",
              "| 发布截止时间、平台与顺序 | 待确认；未自动发布 |", ""]
    return "\n".join(lines)


def write_review(project: Path, script: dict | None = None) -> Path:
    """Called only by CLI after a successful build; use the actual final story."""
    import json
    story = json.loads((project / "story.json").read_text(encoding="utf-8"))
    target = project / "out" / "发布前核对.md"
    target.write_text(review_markdown(story, project, script), encoding="utf-8")
    return target
