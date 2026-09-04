/* 视频页: 七个子页 —— 热点追踪/视频分析/脚本生成/视频制作/模板仓库/素材仓库/追踪账号。
   本期实装【热点追踪】(YouTube 启用频道的视频播放增量榜, 快照差分)与【追踪账号】
   (YouTube 账号库增删启停, yt_channels.json); 【视频制作】= 原项目列表整体迁入;
   其余四子页占位。子页走壳层 WB.shell.setSubs(火山控制台式左侧菜单) + 页内 tab + v-show。 */
window.WB = window.WB || {};
WB.pages = WB.pages || {};

WB.pages.video = {
  data() {
    return {
      tab: "hot",
      /* ── 热点追踪 ── */
      hotItems: [], hotTotal: 0, hotMeta: null, hotInsights: [],
      f: { range: "24h", sort: "views", kind: "all", channel: "", q: "" },
      hotLoading: false, hotErr: null,
      collecting: false, collectPoll: null,
      /* ── 追踪账号 ── */
      chs: [], chMeta: null,
      chForm: { input: "", note: "" }, showChForm: false, adding: false, chBusyId: "",
      /* ── 视频制作(原视频页内容) ── */
      videos: [], sel: null, error: null,
      phTitles: { analysis: "视频分析", script: "脚本生成",
                  templates: "模板仓库", materials: "素材仓库" },
    };
  },
  computed: {
    selMp4() {
      return this.sel && this.sel.mp4.length
        ? "/wb-api/videos/" + this.sel.id + "/file/" + this.sel.mp4[0] : "";
    },
    selCover() {
      return this.sel && this.sel.cover ? "/wb-api/videos/" + this.sel.id + "/file/cover.png" : "";
    },
    enabledChannels() {
      return (this.chs || []).filter((c) => c.resolve_status === "resolved" && c.enabled !== false);
    },
    enabledChs() {
      return (this.chs || []).filter((c) => c.enabled !== false);
    },
    pendingChs() {
      return this.enabledChs.filter((c) => c.resolve_status === "pending");
    },
  },
  methods: {
    gateClass(s) { return s === "built" ? "green" : s === "reviewed" ? "yellow" : ""; },
    gateText(s) { return { draft: "草稿", reviewed: "已审核", built: "已出片" }[s] || s; },
    /* ── 壳层子页注册(迟到的异步回调不得覆盖别的页面) ── */
    registerSubs() {
      if (!WB.shell) return;
      if (!location.hash.replace(/^#/, "").startsWith("/video")) return;
      const I = (p) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + p + "</svg>";
      WB.shell.setSubs([
        { id: "hot", title: "热点追踪", cnt: this.hotTotal || "",
          icon: I('<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>'),
          onPick: () => { this.tab = "hot"; } },
        { id: "analysis", title: "视频分析",
          icon: I('<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/>'),
          onPick: () => { this.tab = "analysis"; } },
        { id: "script", title: "脚本生成",
          icon: I('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>'),
          onPick: () => { this.tab = "script"; } },
        { id: "make", title: "视频制作", cnt: this.videos.length || "",
          icon: I('<rect x="2" y="2" width="20" height="20" rx="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="17" x2="22" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/>'),
          onPick: () => { this.tab = "make"; } },
        { id: "templates", title: "模板仓库",
          icon: I('<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/>'),
          onPick: () => { this.tab = "templates"; } },
        { id: "materials", title: "素材仓库",
          icon: I('<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>'),
          onPick: () => { this.tab = "materials"; } },
        { id: "tracked", title: "追踪账号", cnt: this.chs.length || "",
          icon: I('<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'),
          onPick: () => { this.tab = "tracked"; } },
      ], this.tab);
    },
    /* ── 展示格式化 ── */
    cut(s, n) {                       // 按字符截断([...展开]防 emoji 代理对截半)
      const a = [...String(s || "")];
      return a.length > n ? a.slice(0, n).join("") + "…" : a.join("");
    },
    fmtNum(n) {
      if (n == null) return "—";
      if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2).replace(/\.?0+$/, "") + " 亿";
      if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(1).replace(/\.0$/, "") + " 万";
      return String(n);
    },
    fmtDur(s) {
      if (s == null) return "—";
      const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
      return h ? h + ":" + String(m).padStart(2, "0") + ":" + String(sec).padStart(2, "0")
               : m + ":" + String(sec).padStart(2, "0");
    },
    deltaText(r, key, basisKey) {
      const v = r[key];
      if (v == null) return "—";
      const sign = v < 0 ? "-" : "+";
      const b = basisKey ? r[basisKey] : undefined;
      const star = (b === "first_seen" || b === false) ? "*" : "";
      return sign + this.fmtNum(Math.abs(v)) + star + (v < 0 ? "↓" : "");
    },
    chStatusClass(c) {
      if (c.resolve_status === "failed") return "dead";
      if (c.resolve_status === "resolved") return c.enabled !== false ? "ok" : "off";
      return "off";
    },
    chStatusText(c) {
      if (c.resolve_status === "failed") return "解析失败";
      if (c.resolve_status === "resolved") return "已解析";
      return "待解析";
    },
    /* ── 热点追踪 ── */
    hotQuery() {
      const p = new URLSearchParams();
      p.set("range", this.f.range); p.set("sort", this.f.sort); p.set("kind", this.f.kind);
      if (this.f.channel) p.set("channel", this.f.channel);
      if (this.f.q.trim()) p.set("q", this.f.q.trim());
      return p.toString();
    },
    async loadHot() {
      this.hotLoading = true; this.hotErr = null;
      try {
        const d = await WB.api.get("/yt/hot?" + this.hotQuery());
        this.hotItems = d.items; this.hotTotal = d.total; this.hotMeta = d.meta;
        this.hotInsights = d.insights || [];
      } catch (e) { this.hotErr = e; }
      this.hotLoading = false;
      this.registerSubs();
    },
    async doCollect() {
      if (this.collecting) return;
      this.collecting = true;
      try {
        await WB.api.post("/yt/collect", {});
        this.pollCollect();
      } catch (e) {
        WB.toast(e.error + (e.hint ? " — " + e.hint : ""));
        this.collecting = false;
      }
    },
    pollCollect() {                       // 采集为异步 spawn, 每 3s 轮询状态直到收尾
      clearTimeout(this.collectPoll);
      const tick = async () => {
        let st = null;
        try { st = await WB.api.get("/yt/status"); } catch (e) {}
        if (st && !st.running) {
          this.collecting = false;
          const rep = (st.last_report) || {};
          if (st.last_exit === 4) WB.toast("未配置 YouTube API Key — 到设置页填写");
          else if (st.last_exit === 3) WB.toast("YouTube 配额熔断, 已保留旧数据");
          else WB.toast("采集完成: 频道 " + (rep.channels_ok != null ? rep.channels_ok : "-")
            + " · 新视频 " + (rep.new_videos != null ? rep.new_videos : "-")
            + " · 快照 " + (rep.snapshotted != null ? rep.snapshotted : "-"));
          this.loadHot(); this.loadChannels();
          return;
        }
        this.collectPoll = setTimeout(tick, 3000);
      };
      this.collectPoll = setTimeout(tick, 3000);
    },
    /* ── 追踪账号 ── */
    async loadChannels() {
      try {
        const d = await WB.api.get("/yt/channels");
        this.chs = d.channels; this.chMeta = d.meta;
      } catch (e) {}
      this.registerSubs();
    },
    async addChannel() {
      if (!this.chForm.input.trim()) { WB.toast("请粘贴频道链接 / @handle / UC 频道 ID"); return; }
      this.adding = true;
      try {
        const d = await WB.api.post("/yt/channels",
          { input: this.chForm.input, note: this.chForm.note });
        this.chs = d.channels;
        WB.toast("已添加" + (d.added.title ? ": " + d.added.title : "(下一轮采集时解析)"));
        this.chForm.input = ""; this.chForm.note = ""; this.showChForm = false;
        if (this.hotMeta && this.hotMeta.configured) this.doCollect();  // 让新账号尽快出数据
      } catch (e) {
        WB.toast(e.error + (e.hint ? " — " + e.hint : ""));
      }
      this.adding = false;
      this.registerSubs();
    },
    async toggleCh(c) {
      this.chBusyId = c.id;
      try {
        const d = await WB.api.post("/yt/channels/" + c.id + "/enabled", { on: c.enabled === false });
        c.enabled = d.enabled;
      } catch (e) { WB.toast(e.error); }
      this.chBusyId = "";
    },
    async delCh(c) {
      if (!confirm("删除追踪 " + (c.title || c.input) + " ?\n已采集的历史数据保留在本地, 但不再更新")) return;
      try {
        const d = await WB.api.del("/yt/channels/" + c.id);
        this.chs = d.channels;
        WB.toast("已删除");
      } catch (e) { WB.toast(e.error); }
      this.registerSubs();
    },
    async importLegacy() {
      try {
        const d = await WB.api.post("/yt/channels/import", {});
        this.chs = d.channels;
        WB.toast("导入 " + d.imported.length + " 个 · 跳过 " + d.skipped.length + " 个(重复/格式无法识别)");
      } catch (e) { WB.toast(e.error); }
      this.registerSubs();
    },
  },
  async mounted() {
    this.registerSubs();
    try { this.videos = (await WB.api.get("/videos")).videos; }
    catch (e) { this.error = e; }
    this.loadChannels();
    this.loadHot();
    try {                            // 已有采集在跑(如计划任务刚触发)则同步按钮态
      const st = await WB.api.get("/yt/status");
      if (st.running) { this.collecting = true; this.pollCollect(); }
    } catch (e) {}
  },
  unmounted() {
    clearTimeout(this.collectPoll);
    if (WB.shell) WB.shell.setSubs([]);   // 离开视频页清空左菜单
  },
  template: `
  <div>
    <!-- ═══ 子页1: 热点追踪 ═══ -->
    <div v-show="tab==='hot'">
      <div class="notice" v-if="hotMeta && !hotMeta.configured">
        未配置 YouTube Data API Key —— 到 <a href="#/settings">设置 → YouTube 热点追踪</a> 填写后才能采集;
        在【追踪账号】添加的频道会在配置后的下一轮采集自动解析</div>
      <div class="notice" v-else-if="hotMeta && hotMeta.configured && !enabledChs.length">
        还没有启用中的频道 —— 先到左侧【追踪账号】添加并启用 YouTube 频道</div>
      <div class="notice" v-else-if="hotMeta && hotMeta.configured && !enabledChannels.length && pendingChs.length">
        {{ pendingChs.length }} 个频道已启用、等待解析 —— 点「立即采集」或等下一轮计划任务(每天一次)</div>
      <div class="notice" v-else-if="hotMeta && hotMeta.cold_start">
        快照冷启动中: 增量需第 2 轮采集后才有(计划任务每天一轮, 或点「立即采集」),
        当前先按累计播放排序参考</div>

      <!-- 热门视频解读: 近7天播放 Top20 取前10, 简介/标签由 AI 生成 -->
      <div class="card" v-if="hotInsights.length">
        <h3>热门视频解读
          <span class="muted" style="margin-left:10px;font-weight:400">近 7 天播放 Top20 · 前 10
            · 简介/标签由 AI 生成, 随采集增量补齐</span></h3>
        <div class="muted" style="margin-bottom:8px" v-if="hotMeta && !hotMeta.insight_configured">
          未配置解读模型(设置 → 翻译模型), 暂无 AI 简介/标签</div>
        <table class="tbl">
          <thead><tr>
            <th>标题</th><th>类型</th><th>发布</th><th>播放</th><th>赞</th><th>评</th>
            <th>内容简介</th><th>内容标签</th><th>Δ24h</th><th>Δ7d</th><th>日速</th>
          </tr></thead>
          <tbody>
            <tr v-for="r in hotInsights" :key="r.video_id">
              <td style="max-width:200px"><a :href="r.url" target="_blank" rel="noopener"
                   :title="r.channel_title + ' · ' + r.title">{{ cut(r.title, 20) }}</a></td>
              <td><span class="badge" :class="r.is_short ? 'yellow' : ''">{{ r.is_short ? 'Shorts' : '长视频' }}</span></td>
              <td class="mono">{{ r.published_at }}</td>
              <td class="mono">{{ fmtNum(r.views) }}</td>
              <td class="mono muted">{{ fmtNum(r.likes) }}</td>
              <td class="mono muted">{{ fmtNum(r.comments) }}</td>
              <td style="max-width:280px" :title="r.summary || ''">
                <span v-if="r.summary">{{ cut(r.summary, 40) }}</span>
                <span v-else class="muted">生成中(下轮采集补齐)</span></td>
              <td style="max-width:160px">
                <span v-for="t in r.tags" :key="t" class="badge blue" style="margin-right:4px">{{ t }}</span>
                <span v-if="!r.tags || !r.tags.length" class="muted">—</span></td>
              <td class="mono">{{ deltaText(r, 'delta_24h', 'delta_24h_credible') }}</td>
              <td class="mono">{{ deltaText(r, 'delta_7d') }}</td>
              <td class="mono">{{ r.rate_per_day != null ? '+' + fmtNum(r.rate_per_day) : '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <h3>热点追踪
          <span v-if="hotMeta && hotMeta.last_collect_at" class="muted" style="margin-left:10px;font-weight:400">
            采集于 {{ hotMeta.last_collect_at }}
            <span v-if="hotMeta.data_age_min != null && hotMeta.data_age_min > 1500"
                  style="color:var(--yellow)">· 已 {{ Math.round(hotMeta.data_age_min / 60) }} 小时未更新, 检查计划任务 aag-yttrack-refresh</span>
          </span>
          <span style="float:right">
            <button class="btn" :disabled="hotLoading" @click="loadHot">{{ hotLoading ? '刷新中…' : '刷新' }}</button>
            <button class="btn primary" :disabled="collecting" @click="doCollect"
                    :title="collecting ? '采集进行中' : '拉取全部启用频道的最新统计'">{{ collecting ? '采集中…' : '立即采集' }}</button>
          </span></h3>
        <div class="form-row" style="gap:8px;flex-wrap:wrap">
          <select v-model="f.range" @change="loadHot" style="width:auto">
            <option value="24h">近 24h</option><option value="48h">近 48h</option>
            <option value="7d">近 7 天</option><option value="28d">近 28 天</option>
            <option value="all">全部</option></select>
          <select v-model="f.kind" @change="loadHot" style="width:auto">
            <option value="all">全部类型</option><option value="long">长视频</option>
            <option value="short">Shorts</option></select>
          <select v-model="f.channel" @change="loadHot" style="width:auto">
            <option value="">全部频道</option>
            <option v-for="c in enabledChannels" :key="c.channel_id" :value="c.channel_id">{{ c.title }}</option></select>
          <select v-model="f.sort" @change="loadHot" style="width:auto">
            <option value="views">按播放量</option><option value="delta24h">按 Δ24h 增量</option>
            <option value="delta7d">按 Δ7d 增量</option><option value="rate">按折合日速</option>
            <option value="newest">按最新发布</option></select>
          <input type="text" v-model="f.q" placeholder="标题搜索…" style="width:160px"
                 @keyup.enter="loadHot">
          <button class="btn" @click="loadHot">筛选</button>
          <span class="muted" v-if="hotTotal">{{ hotTotal }} 条</span>
        </div>

        <div v-if="hotErr" class="err-box">{{ hotErr.error || hotErr }}</div>
        <div v-else-if="!hotLoading && !hotItems.length" class="empty">
          {{ hotMeta && hotMeta.configured && enabledChannels.length
            ? '窗口内暂无启用频道的视频 —— 点「立即采集」或等下一轮计划任务' : '添加并启用频道后, 这里是它们的热播榜' }}</div>
        <table v-else class="tbl">
          <thead><tr>
            <th>视频</th><th>频道</th><th>类型</th><th>发布</th>
            <th>播放</th><th>Δ24h</th><th>Δ7d</th><th>日速</th><th>赞</th><th>评</th>
          </tr></thead>
          <tbody>
            <tr v-for="r in hotItems" :key="r.video_id" :class="{stale: r.cold}">
              <td style="max-width:220px">
                <a :href="r.url" target="_blank" rel="noopener"
                   :title="r.channel_title + ' · ' + r.title">{{ cut(r.title, 20) }}</a></td>
              <td class="muted">{{ r.channel_title }}</td>
              <td><span class="badge" :class="r.is_short ? 'yellow' : ''">{{ r.is_short ? 'Shorts' : '长视频' }}</span></td>
              <td class="mono" :title="'发布已 ' + r.age_h + 'h'">{{ r.published_at }}</td>
              <td class="mono">{{ fmtNum(r.views) }}</td>
              <td class="mono">{{ deltaText(r, 'delta_24h', 'delta_24h_basis') }}</td>
              <td class="mono">{{ deltaText(r, 'delta_7d') }}</td>
              <td class="mono">{{ r.rate_per_day != null ? '+' + fmtNum(r.rate_per_day) : '—' }}</td>
              <td class="mono muted">{{ fmtNum(r.likes) }}</td>
              <td class="mono muted">{{ fmtNum(r.comments) }}</td>
            </tr>
          </tbody>
        </table>
        <p class="muted" style="margin-top:8px" v-if="hotMeta">{{ hotMeta.rule }}</p>
      </div>
    </div>

    <!-- ═══ 子页2/3/5/6: 占位 ═══ -->
    <div v-show="tab==='analysis' || tab==='script' || tab==='templates' || tab==='materials'">
      <div class="card">
        <h3>{{ phTitles[tab] }}</h3>
        <div class="stub-wrap">
          <button class="btn stub" disabled>后续版本开放</button>
          <div class="stub-tip">该子页在本期只保留占位 —— 热点追踪与追踪账号已可用。</div>
        </div>
      </div>
    </div>

    <!-- ═══ 子页4: 视频制作(原视频项目列表整体迁入) ═══ -->
    <div v-show="tab==='make'">
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
      </div>
    </div>

    <!-- ═══ 子页7: 追踪账号 ═══ -->
    <div v-show="tab==='tracked'">
      <div class="card">
        <h3>YouTube 追踪账号({{ chs.length }})
          <span v-if="chMeta && !chMeta.configured" class="muted" style="font-weight:400">
            · 未配 Key, 添加后待解析</span>
          <span style="float:right">
            <button class="btn" @click="importLegacy" title="从「追踪」主页面的清单导入 platform=YouTube 的行">从追踪页导入</button>
            <button class="btn primary" @click="showChForm = !showChForm">＋ 添加频道</button>
          </span></h3>
        <div v-if="showChForm" style="margin-bottom:12px;padding:10px;border:1px dashed var(--border);border-radius:8px">
          <div class="form-row"><label>频道</label>
            <input type="text" v-model="chForm.input" style="width:360px"
                   placeholder="@handle / youtube.com 链接 / 频道名(中文自动搜索解析, 每个耗 100 配额)" @keyup.enter="addChannel"></div>
          <div class="form-row"><label>备注</label>
            <input type="text" v-model="chForm.note" placeholder="可选: 券商 / 宏观 / 芯片…"></div>
          <button class="btn primary" :disabled="adding" @click="addChannel">{{ adding ? '保存中…' : '保存' }}</button>
        </div>
        <div v-if="!chs.length" class="muted" style="padding:8px 0">
          尚未添加频道 —— 粘贴 YouTube 频道主页链接或 @handle; 添加后由采集器自动解析出频道名与订阅数。
          此清单与「追踪」主页面的账号通讯录相互独立。</div>
        <div class="acct-grid">
          <div v-for="c in chs" :key="c.id" class="acct-card">
            <div class="plat">YouTube</div>
            <div class="name">{{ c.title || c.input }}</div>
            <div class="muted" style="font-size:11px">
              <span v-if="c.handle">{{ c.handle }} · </span>{{ c.channel_id || '待解析' }}</div>
            <div class="muted" style="margin-top:4px">
              <span class="pill" :class="chStatusClass(c)">{{ chStatusText(c) }}</span>
              <span v-if="c.resolve_status === 'failed'" :title="c.resolve_error" style="color:var(--red);font-size:11px"> {{ c.resolve_error }}</span>
              <span v-if="c.subs != null" class="muted" style="font-size:11px"> 订阅≈{{ fmtNum(c.subs) }}(取整)</span></div>
            <div class="muted" style="font-size:11px;margin-top:4px">{{ c.note || '—' }} · 添加于 {{ c.added_at }}</div>
            <div style="margin-top:8px;display:flex;align-items:center;justify-content:space-between">
              <span class="switch" :class="{on: c.enabled !== false, busy: chBusyId === c.id}"
                    role="switch" tabindex="0" :aria-checked="c.enabled === false ? 'false' : 'true'"
                    :title="(c.enabled === false ? '启用' : '停用') + '追踪'"
                    @click="toggleCh(c)" @keydown.enter="toggleCh(c)"></span>
              <a style="font-size:12px" @click="delCh(c)">删除</a></div>
          </div>
        </div>
        <p class="muted" style="margin-top:10px">
          启停只影响采集范围(停用频道不外呼); 解析与首轮数据在下一轮采集完成
          (计划任务每小时, 或到【热点追踪】点「立即采集」)。删除不停用历史快照。</p>
      </div>
    </div>
  </div>`,
};
