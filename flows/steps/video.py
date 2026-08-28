"""视频步骤:调 generator 的 video 管线出片(TTS+渲染+封面)。"""

from flows.steps import step


@step("render_video")
def render_video(ctx, wf, params):
    """依赖 assemble 的 daily JSON。with: {estimate: bool}(无声预览)。"""
    import video as video_mod
    out = video_mod.run(date=wf.date, force=True, estimate=bool(params.get("estimate")))
    return {"video_path": str(out)}
