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
