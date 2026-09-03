/* 视频页: 项目列表(project.json 门禁) + mp4 播放; 构建/投稿按钮本期为桩。 */
window.WB = window.WB || {};
WB.pages = WB.pages || {};

WB.pages.video = {
  data() { return { videos: [], sel: null, error: null }; },
  computed: {
    selMp4() {
      return this.sel && this.sel.mp4.length
        ? "/wb-api/videos/" + this.sel.id + "/file/" + this.sel.mp4[0] : "";
    },
    selCover() {
      return this.sel && this.sel.cover ? "/wb-api/videos/" + this.sel.id + "/file/cover.png" : "";
    },
  },
  methods: {
    gateClass(s) { return s === "built" ? "green" : s === "reviewed" ? "yellow" : ""; },
    gateText(s) { return { draft: "草稿", reviewed: "已审核", built: "已出片" }[s] || s; },
  },
  async mounted() {
    try { this.videos = (await WB.api.get("/videos")).videos; }
    catch (e) { this.error = e; }
  },
  template: `
  <div class="two-col">
    <div class="card">
      <h3>视频项目({{ videos.length }})</h3>
      <div v-if="!videos.length" class="muted" style="padding:12px 0">
        暂无项目 —— <code class="mono">python cli.py video build &lt;id&gt;</code> 出片后在此可见</div>
      <div v-for="v in videos" :key="v.id" class="list-item" :class="{sel: sel === v}" @click="sel = v">
        <div class="t">{{ v.title }}
          <span class="badge" :class="gateClass(v.status)" style="float:right">{{ gateText(v.status) }}</span></div>
        <div class="s">{{ v.id }}<span v-if="v.scenes"> · {{ v.scenes }} 幕</span>
          <span v-if="v.mp4.length"> · {{ v.mp4.length }} 个 mp4</span></div>
      </div>
    </div>

    <div>
      <div class="card" v-if="!sel">
        <h3>项目详情</h3>
        <div class="muted">从左侧选择一个视频项目查看详情与预览</div>
      </div>
      <template v-else>
        <div class="card">
          <h3>{{ sel.title }}</h3>
          <p class="muted" style="margin-bottom:10px">项目 {{ sel.id }} · 门禁状态: {{ gateText(sel.status) }}</p>
          <video v-if="selMp4" :src="selMp4" controls preload="metadata" style="max-height:420px"></video>
          <img v-else-if="selCover" :src="selCover" class="cover-thumb" style="max-width:280px">
          <div v-else class="muted">尚无渲染产物(out/ 为空)</div>
          <div v-if="sel.mp4.length > 1" class="muted" style="margin-top:6px">
            产物: <span v-for="m in sel.mp4" class="mono" style="margin-right:8px">{{ m }}</span></div>
        </div>
        <div class="card">
          <h3>操作</h3>
          <div class="stub-wrap">
            <button class="btn stub" disabled>构建视频</button>
            <button class="btn stub" disabled>投稿 B站/抖音</button>
            <div class="stub-tip">
              构建: <code>python cli.py video build {{ sel.id }}</code><br>
              投稿(先草稿): <code>python cli.py publish run-video --video ai-workflow/video/videos/{{ sel.id }}/out/final.mp4 --title "标题" --draft</code>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>`,
};
