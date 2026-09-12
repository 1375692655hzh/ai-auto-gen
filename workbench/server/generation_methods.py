"""Visible generation capabilities. Shared by presets and the CLI converter."""
ALL_ASPECTS = ["16:9", "9:16", "1:1", "4:5"]
GENERATION_METHODS = [
    {"id": "inherit", "desc": "不指定方式，按全片主题/编排自动解析（vox-collage 主题或 fast-cut 编排下会解析为 vox-fast-cut）", "name": "继承全片默认", "aspects": ALL_ASPECTS, "cost": "按全片默认"},
    {"id": "template", "desc": "本地模板动效，标题/数据卡/对比等版式按拍角色确定性映射，无生图调用", "name": "模板动效", "aspects": ALL_ASPECTS, "cost": "本地渲染，无生图调用"},
    {"id": "vox-fast-cut", "desc": "VOX 拼贴快切：构图轮换 + 独立文字卡，每父拍最多一张新图，缓存命中不生图", "name": "VOX 拼贴快切（构图轮换 + 独立文字卡）", "aspects": ["16:9"], "cost": "每父拍最多一张，缓存命中不生图"},
    {"id": "vox-collage", "desc": "VOX 纸拼贴：档案海报风 + 3–6 秒构图切换，仅 16:9", "name": "VOX 纸拼贴（档案海报 + 3–6 秒构图切换）", "aspects": ["16:9"], "cost": "每父拍最多一张，缓存命中不生图"},
    {"id": "hand-drawn", "desc": "内置 SVG 手绘跟随描线，本地规则渲染，无外部 API", "name": "手绘跟随（内置 SVG）", "aspects": ["16:9"], "cost": "本地规则描线，无外部 API"},
    {"id": "upload_image", "desc": "直接使用素材仓库图片，无生图调用", "name": "已有 / 上传图片", "aspects": ["16:9"], "cost": "本地素材，无生图调用"},
    {"id": "upload_video", "desc": "直接使用素材仓库视频", "name": "已有 / 上传视频", "aspects": ["16:9"], "cost": "本地素材，无生图调用"},
    {"id": "ai_image", "desc": "按拍提示词生成一张纸拼贴单图，按供应商计费", "name": "AI 图片（纸拼贴单图）", "aspects": ["16:9"], "cost": "每父拍最多一张，按供应商计费"},
]


# ── 视觉风格预设(2026-09-12 用户拍板"一个选择框", MoA 六岗方案合成) ─────────
# 预设 = 主题×编排×产线的命名套餐, 只是前端"一次写三字段"的快捷视图:
# 预设 id 永不落库, make JSON 三字段与渲染链(vmake inherit 解析)零改动。
# generation_method 以 inherit 为主(与用户手选三下拉渲染行为零差异, 旧档命中率高),
# 仅 hand-drawn / vox-collage 无法由 inherit 解析出, 显式钉死。
STYLE_PRESETS = [
    {"id": "midnight", "name": "午夜科技", "default": True,
     "desc": "深空底色+荧光绿高亮，AI 自动编排，全场景通用",
     "theme": "terminal-dark", "layout": "auto", "generation_method": "inherit"},
    {"id": "midnight-quote", "name": "午夜金句",
     "desc": "午夜色系放大金句与对比，观点型内容首选",
     "theme": "terminal-dark", "layout": "quote-big", "generation_method": "inherit"},
    {"id": "paper-brief", "name": "素白简报",
     "desc": "素白纸面简报，柔和高对比，适合日间快讯",
     "theme": "paper-light", "layout": "auto", "generation_method": "inherit"},
    {"id": "ocean-data", "name": "深海数据",
     "desc": "深海蓝调渐变，数据密集版式，多数字段落首选",
     "theme": "ocean-blue", "layout": "data-dense", "generation_method": "inherit"},
    {"id": "vox-cut", "name": "VOX 拼贴快切",
     "desc": "纸拼贴皮肤+快节奏构图轮换+独立文字卡",
     "theme": "vox-collage", "layout": "fast-cut", "generation_method": "inherit"},
    {"id": "vox-archive", "name": "VOX 档案拼贴",
     "desc": "档案海报风，3–6 秒切换构图",
     "theme": "vox-collage", "layout": "auto", "generation_method": "vox-collage"},
    {"id": "midnight-cut", "name": "速报快切",
     "desc": "午夜色系+短镜头高频切换，快节奏资讯",
     "theme": "terminal-dark", "layout": "fast-cut", "generation_method": "inherit"},
    {"id": "hand-sketch", "name": "手绘白板",
     "desc": "内置 SVG 描线跟随，本地规则渲染零外部调用",
     "theme": "paper-light", "layout": "auto", "generation_method": "hand-drawn"},
]


def style_presets_view(theme_rows: list, layout_rows: list) -> list:
    """预设下发视图: 在 build_presets 的 themes/layouts 行之上派生 method_resolved /
    cost / aspects(三元组约束交集), 供前端下拉渲染与旧档两层匹配(行为等价即命中)。
    inherit 解析规则源 = vmake inherit 分支(vox-collage 主题或 fast-cut 编排 →
    vox-fast-cut, 否则 template); 此处仅做展示推导, 改渲染链须同步, 勿双写漂移。"""
    method_by_id = {m["id"]: m for m in GENERATION_METHODS}
    theme_limit = {t["id"]: t.get("aspect_limit") for t in theme_rows}
    _ = layout_rows                                    # 预留: 编排约束目前只有 fast-cut
    out = []
    for p in STYLE_PRESETS:
        gm = p["generation_method"]
        resolved = gm
        if gm == "inherit":
            resolved = "vox-fast-cut" if (p["theme"] == "vox-collage" or p["layout"] == "fast-cut") else "template"
        aspects = list(ALL_ASPECTS)
        if theme_limit.get(p["theme"]):
            aspects = [a for a in aspects if a == theme_limit[p["theme"]]]
        if p["layout"] == "fast-cut":
            aspects = [a for a in aspects if a == "16:9"]
        mrow = method_by_id.get(gm) or {}
        if mrow.get("aspects"):
            aspects = [a for a in aspects if a in mrow["aspects"]]
        zero = resolved in ("template", "hand-drawn")
        out.append({**p, "method_resolved": resolved, "aspects": aspects,
                    "cost_type": "zero" if zero else "billed",
                    "cost_label": "零生图 · 本地渲染" if zero else "生图计费 · 每父拍≤1张"})
    return out
