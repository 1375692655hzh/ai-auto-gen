/* 视频页: 热点追踪 + 视频工坊(分析/脚本生成/脚本仓库) + 制作/仓库/追踪账号。 */
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
      /* ── 视频工坊 ── */
      pool: [], poolMeta: null, poolIds: {}, poolSel: null,
      anUrl: '', anRec: null, anBusy: false, anErr: null, anProgress: null,
      jobPolls: { analyze: null, generate: null, build: null },
      styles: [], drafts: [],
      sg: { brief: '', articleMode: 'none', pasted: '', draftId: '',
            styleId: 'recap-ask-conclude', analysisKey: '' },
      sgPreview: null, sgBusy: false, sgProgress: null, sgHookSel: 0,
      scripts: [], scriptSel: null, scriptFilter: '', reusableOnly: false,
      /* ── 追踪账号 ── */
      chs: [], chMeta: null,
      chForm: { input: "", note: "" }, showChForm: false, adding: false, chBusyId: "",
      /* ── 视频制作(原视频页内容) ── */
      videos: [], sel: null, error: null,
      /* ── 创建视频向导(三步状态机) ── */
      mk: {
        open: false, step: 1,
        source: 'repo', repoId: '', pasted: '', fileName: '',
        styleId: 'recap-ask-conclude', hookSel: 0, script: null,
        title: '', format: 'horizontal', voice: '', ttsProvider: 'edge',
        enrich: 'plain', mode: 'build', stylePack: 'auto', presets: null,
        busy: false, progress: null, err: null, jobPid: '', warn: [],
        logOpen: false, logLines: [], logTruncated: false,
      },
      phTitles: { templates: "模板仓库", materials: "素材仓库" },
    };
  },
  computed: {
    selMp4() {
      if (!this.sel || !this.sel.mp4.length) return "";
      const pick = this.sel.mp4.includes("final.mp4") ? "final.mp4"
        : this.sel.mp4.includes("preview-silent.mp4") ? "preview-silent.mp4"
        : this.sel.mp4[0];
      return "/wb-api/videos/" + this.sel.id + "/file/" + pick;
    },
    pubCmd() {
      if (!this.sel) return '';
      const mp4 = this.sel.mp4.includes('final.mp4') ? 'final.mp4' : (this.sel.mp4[0] || 'final.mp4');
      return 'python cli.py publish run-video --video ai-workflow/video/videos/' + this.sel.id
        + '/out/' + mp4 + ' --title "' + this.sel.title + '" --draft';
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
    filteredScripts() {
      return (this.scripts || []).filter((r) =>
        (!this.scriptFilter || r.kind === this.scriptFilter) && (!this.reusableOnly || r.reusable));
    },
    selectedStyle() {
      return (this.styles || []).find((s) => s.id === this.sg.styleId) || null;
    },
    analyzedPool() {
      return (this.pool || []).filter((r) => r.analysis_status === 'ok' || r.analysis_status === 'partial');
    },
    /* ── 创建视频向导 ── */
    mkRepoScripts() {
      return (this.scripts || []).filter((r) => r.kind === 'generated' && r.script
        && Array.isArray(r.script.beats) && r.script.beats.length);
    },
    mkRepoScript() {
      const r = (this.scripts || []).find((x) => x.id === this.mk.repoId);
      return r && r.script ? r.script : null;
    },
    mkBeats() {
      return this.mk.script && Array.isArray(this.mk.script.beats) ? this.mk.script.beats : [];
    },
    mkWords() {
      return this.mkBeats.reduce((n, b) => n + String(b.narration || '').replace(/\s+/g, '').length, 0);
    },
    mkEmptyNarrs() {
      return this.mkBeats.reduce((ns, b, i) => {
        if (!String(b.narration || '').trim()) ns.push(i + 1);
        return ns;
      }, []);
    },
    mkEstSeconds() {
      return Math.round(this.mkWords / 4.2 + this.mkBeats.length * 1.5);
    },
    mkVoiceGroups() {
      const vs = (this.mk.presets && this.mk.presets.voices) || [];
      return {
        edge: vs.filter((v) => v.provider === 'edge'),
        dashscope: vs.filter((v) => v.provider === 'dashscope'),
      };
    },
    mkDashOk() {
      return !!(this.mk.presets && this.mk.presets.dashscope_key_ok);
    },
    mkLlmReady() {
      return !!(this.mk.presets && this.mk.presets.llm_ready);
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
        { id: "analysis", title: "视频分析", cnt: this.pool.length || "",
          icon: I('<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/>'),
          onPick: () => { this.tab = "analysis"; } },
        { id: "script", title: "脚本生成",
          icon: I('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>'),
          onPick: () => { this.tab = "script"; } },
        { id: 'scripts', title: '脚本仓库', cnt: this.scripts.length || '',
          icon: I('<path d="M4 4h16v16H4z"/><path d="M8 8h8M8 12h8M8 16h5"/>'),
          onPick: () => { this.tab = 'scripts'; } },
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
    fmtNA(v) { return typeof v === 'string' && v.trim().startsWith('N/A'); },
    isObj(v) { return !!v && typeof v === 'object' && !Array.isArray(v); },
    isArr(v) { return Array.isArray(v); },
    fmtList(v) {                       // 数组拼接; 对象元素(evidence/touchpoint)拍成人话
      if (!Array.isArray(v)) return v || '';
      return v.map((x) => {
        if (x == null || typeof x !== 'object') return String(x);
        const head = x.timestamp && !String(x.timestamp).startsWith('N/A') ? x.timestamp + ' ' : '';
        return head + (x.quote || x.text || x.evidence || x.action || JSON.stringify(x));
      }).join('；');
    },
    /* 时间码 → YouTube 跳转链接(验证闭环: 点时间码直达原片位置) */
    tcUrl(ts) {
      const vid = (this.anRec && this.anRec.video_id) || "";
      const m = String(ts || "").match(/(\d{1,2}:\d{2}(?::\d{2})?)/);
      if (!vid || !m) return "";
      const p = m[1].split(":").map(Number);
      const sec = p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1];
      return "https://www.youtube.com/watch?v=" + vid + "&t=" + sec + "s";
    },
    /* 极简 Markdown 渲染(先转义再白名单替换, 零依赖防 XSS): 标题/列表/表格/粗体/时间码链接 */
    mdHtml(s) {
      const esc = (t) => String(t || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const vid = (this.anRec && this.anRec.video_id) || "";
      const tc = (t) => String(t).replace(/\[(\d{1,2}:\d{2}(?::\d{2})?)(-[^\]]*)?\]/g, (m0, start) => {
        const p = start.split(":").map(Number);
        const sec = p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1];
        return vid ? '[<a href="https://www.youtube.com/watch?v=' + vid + '&t=' + sec
          + 's" target="_blank" rel="noopener">' + start + '</a>]' : m0;
      });
      const out = [];
      let inList = false, inTable = false;
      const closeList = () => { if (inList) { out.push("</ul>"); inList = false; } };
      const closeTable = () => { if (inTable) { out.push("</tbody></table>"); inTable = false; } };
      for (const ln of esc(s).split(/\r?\n/)) {
        const t = ln.trim();
        if (t.startsWith("|")) {
          closeList();
          if (/^\|[\s:\-|]+\|$/.test(t)) continue;
          const cells = t.split("|").slice(1, -1).map((c) => c.trim());
          if (!inTable) {
            out.push('<table class="tbl"><thead><tr>' + cells.map((c) => "<th>" + tc(c) + "</th>").join("")
              + "</tr></thead><tbody>");
            inTable = true;
          } else out.push("<tr>" + cells.map((c) => "<td>" + tc(c) + "</td>").join("") + "</tr>");
          continue;
        }
        closeTable();
        if (!t) { closeList(); continue; }
        const h = t.match(/^(#{1,4})\s+(.*)$/);
        if (h) {
          closeList();
          out.push("<h" + (h[1].length + 2) + ">" + tc(h[2]) + "</h" + (h[1].length + 2) + ">");
        } else if (/^[-*·]\s+/.test(t)) {
          if (!inList) { out.push("<ul>"); inList = true; }
          out.push("<li>" + tc(t.replace(/^[-*·]\s+/, "")) + "</li>");
        } else {
          closeList();
          out.push("<p>" + tc(t) + "</p>");
        }
      }
      closeList(); closeTable();
      return out.join("\n").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
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
    /* ── 视频分析 / 素材池 ── */
    async addToPool(r) {
      try {
        const d = await WB.api.post('/video-pool', {
          video_id: r.video_id, url: r.url, title: r.title,
          channel_title: r.channel_title, thumb: r.thumb, source: 'hot',
        });
        if (d.added === false) { WB.toast('已在素材池'); return; }
        WB.toast('已加入素材池');
        await this.loadPool();
      } catch (e) { WB.toast(e.error + (e.hint ? ' — ' + e.hint : '')); }
    },
    async loadPool() {
      try {
        const d = await WB.api.get('/video-pool');
        this.pool = d.items || []; this.poolMeta = d.meta || null;
        const ids = {};
        this.pool.forEach((r) => { if (r.video_id) ids[r.video_id] = true; });
        this.poolIds = ids;
      } catch (e) { this.anErr = e; }
      this.registerSubs();
    },
    async delPool(item) {
      try {
        await WB.api.del('/video-pool/' + item.id);
        if (this.poolSel && this.poolSel.id === item.id) {
          this.poolSel = null; this.anRec = null; this.anUrl = '';
        }
        await this.loadPool();
        WB.toast('已从素材池移除');
      } catch (e) { WB.toast(e.error); }
    },
    async selectPool(item) {
      this.poolSel = item; this.anRec = null; this.anErr = null; this.anUrl = item.url || '';
      if (item.analysis_status === 'ok' || item.analysis_status === 'partial') {
        try {
          this.anRec = await WB.api.get('/video-analyses?key=' + encodeURIComponent(item.video_id));
        } catch (e) { if (e.status !== 404) this.anErr = e; }
      }
    },
    async startAnalyze(force) {
      const url = (this.anUrl || '').trim();
      if (!url && !this.poolSel) { WB.toast('请选择素材或粘贴 YouTube 链接'); return; }
      this.anErr = null;
      try {
        await WB.api.post('/video-analyze', {
          pool_id: this.poolSel ? this.poolSel.id : undefined,
          url: url || undefined, force: !!force,
        });
        this.anBusy = true; this.pollJob('analyze');
      } catch (e) {
        if (e.status === 409) {
          WB.toast('分析进行中'); this.anBusy = true; this.pollJob('analyze');
        } else WB.toast(e.error + (e.hint ? ' — ' + e.hint : ''));
      }
    },
    pollJob(kind) {
      clearTimeout(this.jobPolls[kind]);
      const tick = async () => {
        let jobs;
        try { jobs = await WB.api.get('/video-jobs'); }
        catch (e) {
          if (kind === 'analyze') this.anBusy = false;
          else if (kind === 'build') this.mk.busy = false;
          else this.sgBusy = false;
          WB.toast(e.error); return;
        }
        const job = jobs[kind] || {};
        if (kind === 'analyze') this.anProgress = job.progress || null;
        else if (kind === 'build') this.mk.progress = job.progress || null;
        else this.sgProgress = job.progress || null;
        if (job.running) { this.jobPolls[kind] = setTimeout(tick, 3000); return; }
        if (kind === 'analyze') this.anBusy = false;
        else if (kind === 'build') this.mk.busy = false;
        else this.sgBusy = false;
        if (job.exit === 0) {
          if (kind === 'analyze') {
            try {
              this.anRec = await WB.api.get('/video-analyses?key=' + encodeURIComponent(job.result_key));
              await this.loadPool(); WB.toast('分析完成');
            } catch (e) { WB.toast(e.error); }
          } else if (kind === 'build') {
            const pid = (job.request && job.request.project_id) || '';
            await this.loadVideos();
            const hit = this.videos.find((v) => pid && v.id.indexOf(pid) === 0);
            if (hit) this.sel = hit;
            this.mk.warn = (job.result && job.result.warnings) || [];
            this.mk.open = false; this.mk.err = null;
            WB.toast('视频已生成' + (hit ? ': ' + this.cut(hit.title, 18) : ''));
          } else {
            this.sgPreview = job.result; this.sgHookSel = 0;
            if (this.mk.open && this.mk.step === 1 && this.mk.source !== 'repo') {
              this.mk.script = job.result; this.mk.hookSel = 0;   // 向导内生成 → 回填快照
            }
            WB.toast('脚本已生成，请检查后保存');
          }
        } else if (kind === 'build') {
          this.mk.err = (job.error || '制作失败') + (job.hint ? ' — ' + job.hint : '');
        } else WB.toast((job.error || '任务失败') + (job.hint ? ' — ' + job.hint : ''));
      };
      this.jobPolls[kind] = setTimeout(tick, 3000);
    },
    async saveSeed() {
      if (!this.anRec || (this.anRec.status !== 'ok' && this.anRec.status !== 'partial')) return;
      try {
        await WB.api.post('/video-scripts', {
          kind: 'analysis_seed', title: this.anRec.title, analysis_key: this.anRec.key,
        });
        WB.toast('已存入脚本仓库'); await this.loadScripts();
      } catch (e) { WB.toast(e.error + (e.hint ? ' — ' + e.hint : '')); }
    },
    /* ── 脚本生成 / 仓库 ── */
    async loadStyles() {
      try { this.styles = (await WB.api.get('/video-script/styles')).styles || []; }
      catch (e) { WB.toast(e.error); }
    },
    async loadDrafts() {
      try { this.drafts = (await WB.api.get('/drafts')).drafts || []; }
      catch (e) { this.drafts = []; }
    },
    async loadScripts() {
      try { this.scripts = (await WB.api.get('/video-scripts')).scripts || []; }
      catch (e) { this.scripts = []; }
      this.registerSubs();
    },
    async startGenerate() {
      if (!(this.styles || []).some((s) => s.id === this.sg.styleId)) {
        WB.toast('请选择有效的脚本风格'); return;
      }
      if (this.sg.articleMode === 'paste' && !this.sg.pasted.trim()) {
        WB.toast('请粘贴文章稿'); return;
      }
      if (this.sg.articleMode === 'draft' && !this.sg.draftId) {
        WB.toast('请选择图文草稿'); return;
      }
      if (this.sg.articleMode === 'none' && !this.sg.brief.trim()) {
        WB.toast('请填写视频主题'); return;
      }
      try {
        await WB.api.post('/video-script/generate', {
          brief: this.sg.brief,
          draft_id: this.sg.articleMode === 'draft' ? this.sg.draftId : undefined,
          pasted: this.sg.articleMode === 'paste' ? this.sg.pasted : undefined,
          style_id: this.sg.styleId, analysis_key: this.sg.analysisKey || undefined,
        });
        this.sgBusy = true; this.pollJob('generate');
      } catch (e) {
        if (e.status === 409) {
          WB.toast('脚本生成进行中'); this.sgBusy = true; this.pollJob('generate');
        } else WB.toast(e.error + (e.hint ? ' — ' + e.hint : ''));
      }
    },
    async saveGenerated() {
      if (!this.sgPreview) return;
      try {
        await WB.api.post('/video-scripts', {
          kind: 'generated', title: this.sgPreview.title, style_id: this.sgPreview.style_id,
          analysis_key: this.sg.analysisKey || undefined, script: this.sgPreview,
        });
        WB.toast('已存入脚本仓库'); await this.loadScripts();
      } catch (e) { WB.toast(e.error); }
    },
    async selectScript(r) {
      this.scriptSel = r;
      if (!r.script) {
        try { this.scriptSel = await WB.api.get('/video-scripts/' + r.id); }
        catch (e) { WB.toast(e.error); }
      }
    },
    async delScript(r) {
      if (!confirm('删除脚本「' + (r.title || r.id) + '」？')) return;
      try {
        await WB.api.del('/video-scripts/' + r.id);
        this.scriptSel = null; await this.loadScripts();
      } catch (e) { WB.toast(e.error); }
    },
    async toggleReusable(r) {
      try {
        const d = await WB.api.post('/video-scripts/' + r.id, { reusable: !r.reusable });
        Object.assign(r, d.script);
        const row = this.scripts.find((s) => s.id === r.id);
        if (row && row !== r) Object.assign(row, d.script);
        if (this.scriptSel && this.scriptSel.id === r.id) Object.assign(this.scriptSel, d.script);
      } catch (e) { WB.toast(e.error); }
    },
    /* ── 创建视频向导 ── */
    async loadVideos() {
      try { this.videos = (await WB.api.get('/videos')).videos; }
      catch (e) { this.error = e; }
      this.registerSubs();
    },
    async delVideo(v) {
      if (!confirm('删除项目「' + (v.title || v.id) + '」？\n删除后不可恢复')) return;
      try {
        await WB.api.del('/videos/' + v.id); WB.toast('已删除');
        if (this.sel && this.sel.id === v.id) this.sel = null;
        await this.loadVideos();
      } catch (e) { WB.toast(e.error); }
    },
    copyPubCmd() { WB.copyText(this.pubCmd); WB.toast('投稿命令已复制'); },
    /* 分镜轻编辑：只修改向导快照 */
    setOnScreen(b, ev) {
      if (this.mk.busy) return;
      b.on_screen = ev.target.value.split(/[、,，]/).map((s) => s.trim()).filter(Boolean);
    },
    delBeat(i) {
      if (this.mk.busy) return;
      const b = this.mkBeats[i];
      let msg = '删除场景 ' + (i + 1) + '？删除后不可恢复';
      if (b.role === 'cta') msg += '\n删除后 CTA 唯一性失守，确认？';
      if (!confirm(msg)) return;
      this.mk.script.beats.splice(i, 1);
    },
    openWizard() {
      this.mk.open = true; this.mk.step = 1; this.mk.err = null; this.mk.script = null;
      this.mk.source = 'repo'; this.mk.repoId = ''; this.mk.pasted = '';
      this.mk.fileName = ''; this.mk.hookSel = 0;
      this.mk.warn = []; this.mk.stylePack = 'auto';
      this.mk.logOpen = false; this.mk.logLines = [];
      this.loadPresets();
    },
    closeWizard() { this.mk.open = false; },
    async loadPresets() {
      try { this.mk.presets = await WB.api.get('/video-presets'); } catch (e) {}
    },
    wizardFilePicked(ev) {
      const file = ev.target.files && ev.target.files[0];
      if (!file) return;
      if (file.size > 200 * 1024) { WB.toast('文件超过 200KB 上限'); ev.target.value = ''; return; }
      const reader = new FileReader();
      reader.onload = () => {
        this.mk.pasted = String(reader.result || '');
        this.mk.fileName = file.name;
      };
      reader.readAsText(file);
    },
    wizardGenerate() {
      // 复用脚本生成链: 借 sg 状态走 startGenerate → pollJob('generate'), 完成分支回填 mk.script
      if (!this.mk.pasted.trim()) { WB.toast('请先粘贴或上传文稿'); return; }
      this.sg.articleMode = 'paste';
      this.sg.pasted = this.mk.pasted;
      this.sg.styleId = this.mk.styleId;
      this.sg.brief = ''; this.sg.draftId = '';
      this.startGenerate();
    },
    wizardToStep2() {
      const script = this.mk.source === 'repo' ? this.mkRepoScript : this.mk.script;
      if (!script) { WB.toast('请先选择或生成脚本'); return; }
      this.mk.script = JSON.parse(JSON.stringify(script));   // 快照隔离仓库，保留已选 hook 变体
      this.mk.title = String(script.title || '').slice(0, 30);
      const style = (this.styles || []).find((s) => s.id === script.style_id);
      this.mk.format = (script.format === 'vertical' || (style && style.format === 'vertical'))
        ? 'vertical' : 'horizontal';
      this.mk.enrich = this.mkLlmReady ? 'llm' : 'plain';
      this.mk.voice = 'zh-CN-XiaoxiaoNeural';   // 默认 Edge 晓晓(dashscope 音色由用户显式选择)
      this.mk.mode = 'build';
      this.mk.step = 2;
    },
    isDashscopeVoice(v) {
      return String(v || '').indexOf('longan') === 0;
    },
    async startBuild() {
      if (!this.mk.script) { WB.toast('脚本快照丢失，请回到第一步'); this.mk.step = 1; return; }
      this.mk.err = null; this.mk.logOpen = false; this.mk.logLines = [];
      const body = {
        script: this.mk.script,
        title: this.mk.title || undefined,
        format: this.mk.format,
        voice: this.mk.voice || undefined,
        tts_provider: (this.mkDashOk && this.isDashscopeVoice(this.mk.voice)) ? 'dashscope' : 'edge',
        enrich: this.mk.enrich,
        style_pack: this.mk.stylePack || 'auto',
        mode: this.mk.mode,
        hook_index: this.mk.hookSel || 0,
      };
      this.mk.step = 3;
      try {
        const d = await WB.api.post('/video-build', body);
        this.mk.jobPid = d.project_id;
        this.mk.busy = true;
        this.pollJob('build');
      } catch (e) {
        if (e.status === 409) {
          WB.toast('制作任务进行中，已接入进度');
          this.mk.busy = true;
          this.pollJob('build');
        } else {
          this.mk.err = e.error + (e.hint ? ' — ' + e.hint : '');
        }
      }
    },
    retryBuild() {
      this.mk.err = null;
      this.startBuild();
    },
    async loadBuildLog() {
      this.mk.logOpen = !this.mk.logOpen;
      if (!this.mk.logOpen) return;
      const pid = this.mk.jobPid;
      if (!pid) { this.mk.logLines = ['(尚无日志：任务未启动)']; return; }
      try {
        const d = await WB.api.get('/video-builds/' + encodeURIComponent(pid) + '/log?n=200');
        this.mk.logLines = d.tail || [];
        this.mk.logTruncated = !!d.truncated;
      } catch (e) {
        this.mk.logLines = ['(日志读取失败: ' + (e.error || e) + ')'];
      }
    },
  },
  async mounted() {
    this.registerSubs();
    await Promise.all([
      this.loadPool(), this.loadScripts(), this.loadStyles(), this.loadDrafts(),
      this.loadVideos(),
    ]);
    this.loadChannels();
    this.loadHot();
    try {                            // 已有采集在跑(如计划任务刚触发)则同步按钮态
      const st = await WB.api.get("/yt/status");
      if (st.running) { this.collecting = true; this.pollCollect(); }
    } catch (e) {}
    try {
      const jobs = await WB.api.get('/video-jobs');
      if (jobs.analyze && jobs.analyze.running) { this.anBusy = true; this.pollJob('analyze'); }
      if (jobs.generate && jobs.generate.running) { this.sgBusy = true; this.pollJob('generate'); }
      if (jobs.build && jobs.build.running) {       // 刷新/重进页面恢复制作进度
        this.mk.open = true; this.mk.step = 3; this.mk.busy = true;
        this.mk.jobPid = (jobs.build.request && jobs.build.request.project_id) || '';
        this.loadPresets();
        this.pollJob('build');
      }
    } catch (e) {}
  },
  unmounted() {
    clearTimeout(this.collectPoll);
    Object.values(this.jobPolls).forEach(clearTimeout);
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
        <h3>近期热点
          <span class="muted" style="margin-left:10px;font-weight:400">近 7 天播放 Top20 · 前 10
            · 简介/标签由 AI 生成, 随采集增量补齐</span></h3>
        <div class="muted" style="margin-bottom:8px" v-if="hotMeta && !hotMeta.insight_configured">
          未配置解读模型(设置 → 翻译模型), 暂无 AI 简介/标签</div>
        <table class="tbl">
          <thead><tr>
            <th>标题</th><th>类型</th><th>发布</th><th>播放</th><th>赞</th><th>评</th>
            <th>内容简介</th><th>内容标签</th>
          </tr></thead>
          <tbody>
            <tr v-for="r in hotInsights" :key="r.video_id">
              <td style="max-width:200px"><a :href="r.url" target="_blank" rel="noopener"
                   :title="r.channel_title + ' · ' + r.title">{{ cut(r.title, 20) }}</a>
                <div><span v-if="poolIds[r.video_id]" class="act-done">已加入 ✓</span>
                  <a v-else style="font-size:12px" @click.stop.prevent="addToPool(r)">＋加入素材池</a></div></td>
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
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <h3>近期视频
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
                   :title="r.channel_title + ' · ' + r.title">{{ cut(r.title, 20) }}</a>
                <div><span v-if="poolIds[r.video_id]" class="act-done">已加入 ✓</span>
                  <a v-else style="font-size:12px" @click.stop.prevent="addToPool(r)">＋加入素材池</a></div></td>
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

    <!-- ═══ 子页2: 视频分析 ═══ -->
    <div v-show="tab==='analysis'" class="two-col pool-right">
      <div>
        <div class="card">
          <h3>分析对象</h3>
          <div v-if="poolSel" style="margin-bottom:10px">
            <strong>{{ poolSel.title }}</strong>
            <div class="muted">{{ poolSel.channel_title || '未知频道' }} · {{ fmtDur(poolSel.duration_s) }} · {{ fmtNum(poolSel.views) }} 播放</div>
          </div>
          <div v-else class="muted" style="margin-bottom:10px">从左侧素材池选择一个视频，或直接粘贴链接</div>
          <div class="form-row">
            <input type="text" v-model="anUrl" style="min-width:420px;flex:1"
                   placeholder="粘贴任意 watch / youtu.be / shorts 链接或 11 位视频 ID"
                   @keyup.enter="startAnalyze(false)">
            <button class="btn primary" :disabled="anBusy" @click="startAnalyze(false)">
              {{ anBusy ? '分析中…' + (anProgress && anProgress.message ? ' ' + anProgress.message : '') : '开始分析' }}</button>
            <button v-if="poolSel && (poolSel.analysis_status==='ok' || poolSel.analysis_status==='partial')"
                    class="btn" :disabled="anBusy" @click="startAnalyze(true)">重新分析</button>
          </div>
          <div v-if="anErr" class="err-box">{{ anErr.error || anErr }}</div>
        </div>

        <div class="card">
          <h3>分析结果</h3>
          <div v-if="!anRec" class="empty">未分析。选择素材并点击「开始分析」后，结构化报告会显示在这里。</div>
          <template v-else>
            <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
              <span class="badge" :class="anRec.status==='ok' ? 'green' : anRec.status==='partial' ? 'yellow' : 'red'">{{ anRec.status }}</span>
              <span class="badge blue">{{ anRec.tier_used }}</span>
              <span class="badge" v-if="anRec.text_model || anRec.model">{{ anRec.text_model || anRec.model }}</span>
            </div>
            <div v-if="anRec.semantic && anRec.semantic.raw_saved" class="notice">
              模型输出未按 JSON 返回，完整原文在报告中</div>
            <template v-else-if="anRec.semantic">
              <section v-if="anRec.semantic.theme" style="margin-bottom:16px">
                <h3>主题</h3>
                <template v-if="isObj(anRec.semantic.theme)">
                  <div :class="{muted:fmtNA(anRec.semantic.theme.one_liner)}"><strong>{{ anRec.semantic.theme.one_liner }}</strong></div>
                  <div v-if="isArr(anRec.semantic.theme.topics)" style="margin:7px 0"><span v-for="t in anRec.semantic.theme.topics" :key="t" class="badge blue" style="margin-right:5px">{{ t }}</span></div>
                  <div v-else class="muted">{{ anRec.semantic.theme.topics }}</div>
                  <div class="muted">受众：{{ anRec.semantic.theme.audience }} · 形式：{{ anRec.semantic.theme.format }}</div>
                  <div v-if="anRec.semantic.theme.title_formula && !fmtNA(anRec.semantic.theme.title_formula)" class="muted">标题公式：<span style="color:var(--accent)">{{ anRec.semantic.theme.title_formula }}</span></div>
                </template>
                <span v-else :class="{muted:fmtNA(anRec.semantic.theme)}">{{ anRec.semantic.theme }}</span>
              </section>
              <section v-if="anRec.semantic.hook" style="margin-bottom:16px">
                <h3>开场钩子</h3>
                <template v-if="isObj(anRec.semantic.hook)">
                  <div v-if="isArr(anRec.semantic.hook.categories)"><span v-for="t in anRec.semantic.hook.categories" :key="t" class="badge yellow" style="margin-right:5px">{{ t }}</span></div>
                  <div v-else class="muted">{{ anRec.semantic.hook.categories }}</div>
                  <p :class="{muted:fmtNA(anRec.semantic.hook.sequence)}">{{ anRec.semantic.hook.sequence }}</p>
                  <p :class="{muted:fmtNA(anRec.semantic.hook.opening_line)}"><strong>开场：</strong>{{ anRec.semantic.hook.opening_line }}</p>
                  <div v-for="(e,i) in (isArr(anRec.semantic.hook.evidence) ? anRec.semantic.hook.evidence : [])" :key="i" class="list-item">
                    <a v-if="tcUrl(e.timestamp)" class="mono" :href="tcUrl(e.timestamp)" target="_blank" rel="noopener" :title="'跳转原片 ' + e.timestamp">{{ e.timestamp }}</a><span v-else class="mono muted">{{ e.timestamp }}</span> {{ e.quote }}</div>
                  <div v-if="!isArr(anRec.semantic.hook.evidence)" class="muted">{{ anRec.semantic.hook.evidence }}</div>
                </template>
                <span v-else :class="{muted:fmtNA(anRec.semantic.hook)}">{{ anRec.semantic.hook }}</span>
              </section>
              <section v-if="anRec.semantic.structure" style="margin-bottom:16px">
                <h3>结构与节奏</h3>
                <template v-if="isObj(anRec.semantic.structure)">
                  <p :class="{muted:fmtNA(anRec.semantic.structure.arc)}">{{ anRec.semantic.structure.arc }}</p>
                  <table v-if="isArr(anRec.semantic.structure.chapters) && anRec.semantic.structure.chapters.length" class="tbl">
                    <thead><tr><th>时间</th><th>章节</th><th>作用</th></tr></thead>
                    <tbody><tr v-for="(c,i) in anRec.semantic.structure.chapters" :key="i">
                      <td class="mono">{{ c.t }}</td><td>{{ c.label }}</td><td>{{ c.role }}</td></tr></tbody>
                  </table>
                  <div v-else-if="anRec.semantic.structure.chapters" class="muted">{{ anRec.semantic.structure.chapters }}</div>
                  <p class="muted">{{ anRec.semantic.structure.pacing_note }}</p>
                </template>
                <span v-else :class="{muted:fmtNA(anRec.semantic.structure)}">{{ anRec.semantic.structure }}</span>
              </section>
              <section v-if="anRec.semantic.devices" style="margin-bottom:16px">
                <h3>表达装置</h3>
                <div v-if="isArr(anRec.semantic.devices)">
                  <div v-for="(d,i) in anRec.semantic.devices" :key="i" class="list-item">
                    <strong>{{ d.device }}</strong><div class="muted">{{ fmtList(d.evidence) }}</div></div>
                </div>
                <span v-else :class="{muted:fmtNA(anRec.semantic.devices)}">{{ anRec.semantic.devices }}</span>
              </section>
              <section v-if="anRec.semantic.voice" style="margin-bottom:16px">
                <h3>声音与人设</h3>
                <div v-if="isObj(anRec.semantic.voice)" :class="{muted:fmtNA(anRec.semantic.voice.persona)||fmtNA(anRec.semantic.voice.address)||fmtNA(anRec.semantic.voice.tone)}">{{ anRec.semantic.voice.persona }} · {{ anRec.semantic.voice.address }} · {{ anRec.semantic.voice.tone }}</div>
                <span v-else :class="{muted:fmtNA(anRec.semantic.voice)}">{{ anRec.semantic.voice }}</span>
              </section>
              <section v-if="anRec.semantic.cta" style="margin-bottom:16px">
                <h3>行动引导</h3>
                <template v-if="isObj(anRec.semantic.cta)">
                  <div :class="{muted:fmtNA(anRec.semantic.cta.mode)||fmtNA(anRec.semantic.cta.action)}">{{ anRec.semantic.cta.mode }} · {{ anRec.semantic.cta.action }}</div>
                  <div class="muted">{{ fmtList(anRec.semantic.cta.touchpoints) }}</div>
                </template>
                <span v-else :class="{muted:fmtNA(anRec.semantic.cta)}">{{ anRec.semantic.cta }}</span>
              </section>
              <section v-if="anRec.semantic.reusable" style="margin-bottom:16px">
                <h3>可复用骨架</h3>
                <template v-if="isObj(anRec.semantic.reusable)">
                  <div style="margin-bottom:8px"><strong>保留：</strong><span :class="{muted:fmtNA(anRec.semantic.reusable.keep)}">{{ fmtList(anRec.semantic.reusable.keep) }}</span></div>
                  <div class="notice"><strong>复刻时必须替换：</strong>{{ fmtList(anRec.semantic.reusable.change) }}</div>
                  <div v-for="(seed,i) in (isArr(anRec.semantic.reusable.script_seeds) ? anRec.semantic.reusable.script_seeds : [])" :key="i" class="list-item">{{ seed }}</div>
                  <div v-if="!isArr(anRec.semantic.reusable.script_seeds)" class="muted">{{ anRec.semantic.reusable.script_seeds }}</div>
                </template>
                <span v-else :class="{muted:fmtNA(anRec.semantic.reusable)}">{{ anRec.semantic.reusable }}</span>
              </section>
              <section v-if="anRec.semantic.visuals" style="margin-bottom:16px">
                <h3>视觉手法</h3>
                <div v-if="isArr(anRec.semantic.visuals)">
                  <div v-for="(v,i) in anRec.semantic.visuals" :key="i" class="list-item">
                    <strong>{{ v.category }}</strong> <span class="mono muted" v-if="v.timestamp">{{ v.timestamp }}</span>
                    <div class="muted">{{ v.function }}</div>
                    <div class="muted" style="font-size:12px">包装：{{ fmtList(v.packaging_elements) }} · 字幕：{{ v.subtitle_style || '—' }} · 屏幕字：{{ v.on_screen_text || '—' }}</div></div>
                </div>
                <span v-else :class="{muted:fmtNA(anRec.semantic.visuals)}">{{ anRec.semantic.visuals }}</span>
              </section>
              <p v-if="anRec.semantic.tier_note" class="muted">{{ anRec.semantic.tier_note }}</p>
            </template>
            <details v-if="anRec.report_md" style="margin-top:12px">
              <summary>查看完整分析报告(时间码可点击跳原片)</summary>
              <div class="md-preview" v-html="mdHtml(anRec.report_md)"></div>
            </details>
          </template>
        </div>
        <div class="card" style="position:sticky;bottom:10px;z-index:2">
          <button class="btn primary" :disabled="!anRec || (anRec.status!=='ok' && anRec.status!=='partial')" @click="saveSeed">保存到脚本仓库</button>
        </div>
      </div>
      <div class="card" style="align-self:start">
        <h3>素材池({{ pool.length }})</h3>
        <div v-if="!pool.length" class="empty">到【热点追踪】点「＋加入素材池」</div>
        <div v-for="item in pool" :key="item.id" class="list-item" :class="{sel:poolSel && poolSel.id===item.id}" @click="selectPool(item)">
          <div class="t"><span>{{ cut(item.title, 25) }}</span><span v-if="item.analysis_status==='ok' || item.analysis_status==='partial'" style="color:var(--green)">●</span><span v-if="(item.analysis_status==='ok'||item.analysis_status==='partial') && item.analysis_tier_used && item.analysis_tier_used!=='gemini'" class="badge yellow" style="font-size:10px;margin-left:4px" title="文本通道分析, 可「重新分析」升级为 Gemini 看片">文本版</span></div>
          <div class="s">{{ item.channel_title || '未知频道' }} · {{ fmtDur(item.duration_s) }}</div>
          <a style="font-size:12px" @click.stop.prevent="delPool(item)">移除</a>
        </div>
      </div>
    </div>

    <!-- ═══ 子页3: 脚本生成 ═══ -->
    <div v-show="tab==='script'">
      <div class="card">
        <h3>生成脚本</h3>
        <div class="form-row" style="align-items:flex-start"><label>视频主题</label>
          <textarea v-model="sg.brief" rows="4" style="flex:1" placeholder="一句话说明这期视频讲什么"></textarea></div>
        <div class="form-row"><label>文章稿</label><div class="radio-group">
          <label><input type="radio" value="none" v-model="sg.articleMode"> 不使用</label>
          <label><input type="radio" value="paste" v-model="sg.articleMode"> 粘贴文章</label>
          <label><input type="radio" value="draft" v-model="sg.articleMode"> 图文草稿</label>
        </div></div>
        <div v-if="sg.articleMode==='paste'" class="form-row" style="align-items:flex-start"><label>文章内容</label>
          <textarea v-model="sg.pasted" rows="6" style="flex:1" placeholder="粘贴文章全文"></textarea></div>
        <div v-if="sg.articleMode==='draft'" class="form-row"><label>选择草稿</label>
          <select v-model="sg.draftId" style="min-width:360px"><option value="">请选择</option>
            <option v-for="d in drafts" :key="d.id" :value="d.id">{{ d.title }} · {{ d.updated_at }}</option></select>
          <span v-if="!drafts.length" class="muted">图文页还没有草稿</span></div>
        <div class="form-row"><label>脚本风格</label>
          <select v-model="sg.styleId" style="min-width:280px"><option v-for="s in styles" :key="s.id" :value="s.id">{{ s.name }} · {{ s.target_s }}秒</option></select></div>
        <p v-if="selectedStyle" class="muted" style="margin:-4px 0 10px 98px">{{ selectedStyle.prompt }}</p>
        <div class="form-row"><label>参考分析</label>
          <select v-model="sg.analysisKey" style="min-width:360px"><option value="">不使用</option>
            <option v-for="p in analyzedPool" :key="p.id" :value="p.video_id">{{ p.title }}</option></select></div>
        <button class="btn primary" :disabled="sgBusy" @click="startGenerate">
          {{ sgBusy ? '生成中…' + (sgProgress && sgProgress.message ? ' ' + sgProgress.message : '') : '生成脚本' }}</button>
      </div>
      <div v-if="sgPreview" class="card">
        <h3>{{ sgPreview.title }}</h3>
        <div style="display:flex;gap:6px;margin-bottom:10px">
          <span class="badge blue">{{ sgPreview.format }}</span><span class="badge">{{ sgPreview.duration_est_s }} 秒</span><span class="badge">{{ sgPreview.word_count }} 字</span></div>
        <div v-if="sgPreview.warnings && sgPreview.warnings.length" class="notice">
          <div v-for="(w,i) in sgPreview.warnings" :key="i">{{ w }}</div></div>
        <h3>Hook · {{ sgPreview.hook.type }}</h3>
        <div v-for="(v,i) in sgPreview.hook.variants" :key="i" class="list-item" :class="{sel:sgHookSel===i}" @click="sgHookSel=i">● {{ v.text || v }}</div>
        <table class="tbl" style="margin-top:12px"><thead><tr><th>段落</th><th>时长</th><th>口播 / 画面</th></tr></thead>
          <tbody><tr v-for="b in sgPreview.beats" :key="b.id"><td><span class="badge" :class="b.role==='hook'||b.role==='payoff' ? 'yellow' : 'blue'">{{ b.role }}</span></td>
            <td class="mono">{{ b.duration_est_s }}s</td><td><div>{{ b.narration }}</div><div v-if="b.on_screen && b.on_screen.length">字幕：{{ b.on_screen.join('、') }}</div><div class="muted">{{ b.visual_hint }}</div></td></tr></tbody></table>
        <div class="notice" style="margin-top:12px"><strong>CTA · {{ sgPreview.cta.action }}</strong><div>{{ sgPreview.cta.line }}</div></div>
        <button class="btn primary" @click="saveGenerated">保存到脚本仓库</button>
      </div>
    </div>

    <!-- ═══ 子页4: 脚本仓库 ═══ -->
    <div v-show="tab==='scripts'" class="two-col">
      <div class="card">
        <h3>脚本仓库({{ scripts.length }})</h3>
        <div class="form-row"><select v-model="scriptFilter" style="width:auto">
          <option value="">全部</option><option value="analysis_seed">骨架种子</option><option value="generated">成稿</option></select>
          <span class="switch" :class="{on:reusableOnly}" @click="reusableOnly=!reusableOnly"></span><span>仅可复用</span></div>
        <table class="tbl"><thead><tr><th>标题</th><th>类型</th><th>风格</th><th>更新时间</th><th></th></tr></thead>
          <tbody><tr v-for="r in filteredScripts" :key="r.id" @click="selectScript(r)" :style="scriptSel && scriptSel.id===r.id ? 'background:var(--accent-weak)' : ''">
            <td :title="r.title">{{ cut(r.title, 18) }}</td><td><span class="badge" :class="r.kind==='analysis_seed' ? 'yellow' : 'blue'">{{ r.kind==='analysis_seed' ? '种子' : '成稿' }}</span></td>
            <td>{{ r.style_id || '—' }}</td><td class="mono muted">{{ r.updated_at }}</td><td><a @click.stop="delScript(r)">删除</a></td></tr></tbody></table>
      </div>
      <div class="card">
        <h3>脚本详情</h3>
        <div v-if="!scriptSel" class="empty">从左侧选择一个脚本</div>
        <template v-else>
          <div style="display:flex;justify-content:space-between;gap:10px"><h3>{{ scriptSel.title }}</h3>
            <span><span class="switch" :class="{on:scriptSel.reusable}" @click="toggleReusable(scriptSel)"></span> 可复用</span></div>
          <template v-if="scriptSel.kind==='generated' && scriptSel.script">
            <div style="display:flex;gap:6px;margin-bottom:10px"><span class="badge blue">{{ scriptSel.script.format }}</span><span class="badge">{{ scriptSel.script.duration_est_s }} 秒</span><span class="badge">{{ scriptSel.script.word_count }} 字</span></div>
            <div v-if="scriptSel.script.warnings && scriptSel.script.warnings.length" class="notice"><div v-for="(w,i) in scriptSel.script.warnings" :key="i">{{ w }}</div></div>
            <h3>Hook · {{ scriptSel.script.hook.type }}</h3><div v-for="(v,i) in scriptSel.script.hook.variants" :key="i" class="list-item">● {{ v.text || v }}</div>
            <table class="tbl"><thead><tr><th>段落</th><th>时长</th><th>口播 / 画面</th></tr></thead><tbody>
              <tr v-for="b in scriptSel.script.beats" :key="b.id"><td><span class="badge" :class="b.role==='hook'||b.role==='payoff' ? 'yellow' : 'blue'">{{ b.role }}</span></td><td class="mono">{{ b.duration_est_s }}s</td>
                <td><div>{{ b.narration }}</div><div v-if="b.on_screen && b.on_screen.length">字幕：{{ b.on_screen.join('、') }}</div><div class="muted">{{ b.visual_hint }}</div></td></tr></tbody></table>
            <div class="notice" style="margin-top:12px"><strong>CTA · {{ scriptSel.script.cta.action }}</strong><div>{{ scriptSel.script.cta.line }}</div></div>
          </template>
          <template v-else-if="scriptSel.kind==='analysis_seed' && scriptSel.script">
            <h3>可复用风格骨架</h3>
            <div v-if="scriptSel.script.reusable"><p><strong>保留：</strong>{{ fmtList(scriptSel.script.reusable.keep) }}</p>
              <div class="notice"><strong>复刻时必须替换：</strong>{{ fmtList(scriptSel.script.reusable.change) }}</div></div>
            <p class="muted">这是风格骨架种子，可去脚本生成页以 from-analysis 风格展开</p>
          </template>
        </template>
      </div>
    </div>

    <!-- ═══ 子页5/6: 占位 ═══ -->
    <div v-show="tab==='templates' || tab==='materials'">
      <div class="card">
        <h3>{{ phTitles[tab] }}</h3>
        <div class="stub-wrap">
          <button class="btn stub" disabled>后续版本开放</button>
          <div class="stub-tip">该子页在本期只保留占位 —— 热点追踪与追踪账号已可用。</div>
        </div>
      </div>
    </div>

    <!-- ═══ 子页4: 视频制作(项目列表 + 创建视频向导) ═══ -->
    <div v-show="tab==='make'">
      <div class="two-col">
        <div class="card">
          <h3>视频项目({{ videos.length }})
            <span style="float:right">
              <button class="btn primary" @click="openWizard">＋ 创建视频</button>
            </span></h3>
          <div v-if="!videos.length" class="muted" style="padding:12px 0">
            暂无项目 —— 点右上「＋ 创建视频」从脚本一键出片，或 <code class="mono">python cli.py video build &lt;id&gt;</code></div>
          <div v-for="v in videos" :key="v.id" class="list-item" :class="{sel: sel === v}" @click="sel = v">
            <div class="t">{{ v.title }}
              <span class="badge" :class="gateClass(v.status)" style="float:right">{{ gateText(v.status) }}</span></div>
            <div class="s">{{ v.id }}<span v-if="v.scenes"> · {{ v.scenes }} 幕</span>
              <span v-if="v.mp4.length"> · {{ v.mp4.length }} 个 mp4</span>
              <a style="font-size:12px;float:right" @click.stop.prevent="delVideo(v)">删除</a></div>
          </div>
        </div>
        <div>
          <!-- ═══ 创建视频向导(卡内三步) ═══ -->
          <div class="card" v-if="mk.open">
            <h3>创建视频 · 第 {{ mk.step }} / 3 步
              <span style="float:right"><a @click="closeWizard">收起</a></span></h3>

            <!-- Step 1: 文稿来源 -->
            <template v-if="mk.step===1">
              <div class="form-row"><label>文稿来源</label><div class="radio-group">
                <label><input type="radio" value="repo" v-model="mk.source"> 脚本仓库</label>
                <label><input type="radio" value="paste" v-model="mk.source"> 粘贴文稿</label>
                <label><input type="radio" value="upload" v-model="mk.source"> 上传文件</label>
              </div></div>

              <template v-if="mk.source==='repo'">
                <div class="form-row"><label>选择脚本</label>
                  <select v-model="mk.repoId" style="min-width:340px"><option value="">请选择</option>
                    <option v-for="r in mkRepoScripts" :key="r.id" :value="r.id">{{ cut(r.title, 24) }} · {{ r.updated_at }}</option></select>
                  <span v-if="!mkRepoScripts.length" class="muted">仓库还没有成稿 —— 先到【脚本生成】生成并保存</span></div>
                <table class="tbl" v-if="mkRepoScript" style="margin:6px 0 10px">
                  <thead><tr><th>段落</th><th>口播</th></tr></thead>
                  <tbody><tr v-for="b in mkRepoScript.beats" :key="b.id">
                    <td><span class="badge" :class="b.role==='hook'||b.role==='payoff' ? 'yellow' : 'blue'">{{ b.role }}</span></td>
                    <td>{{ b.narration }}</td></tr></tbody></table>
                <div v-if="mkRepoScript">
                  <button class="btn primary" @click="wizardToStep2">用这个脚本制作 →</button></div>
              </template>

              <template v-else>
                <div v-if="mk.source==='upload'" class="form-row"><label>上传文件</label>
                  <input type="file" accept=".txt,.md" @change="wizardFilePicked">
                  <span v-if="mk.fileName" class="muted">{{ mk.fileName }}（已读入下方文本框）</span></div>
                <div class="form-row" style="align-items:flex-start"><label>文稿内容</label>
                  <textarea v-model="mk.pasted" rows="6" style="flex:1"
                            placeholder="粘贴文章全文（或上传 .txt/.md，≤200KB）"></textarea></div>
                <div class="form-row"><label>脚本风格</label>
                  <select v-model="mk.styleId" style="min-width:260px"><option v-for="s in styles" :key="s.id" :value="s.id">{{ s.name }} · {{ s.target_s }}秒</option></select>
                  <button class="btn" :disabled="sgBusy || !mk.pasted.trim()" @click="wizardGenerate">
                    {{ sgBusy ? '生成中…' + (sgProgress && sgProgress.message ? ' ' + sgProgress.message : '') : '生成口播脚本' }}</button></div>
              </template>

              <!-- 脚本快照预览 + 换选 hook 变体 -->
              <template v-if="mk.script">
                <h3 style="margin-top:14px">{{ mk.script.title }}
                  <span class="muted" style="font-weight:400;margin-left:8px">{{ mk.script.word_count }} 字 · {{ mk.script.duration_est_s }} 秒</span></h3>
                <div v-if="mk.script.hook && mk.script.hook.variants && mk.script.hook.variants.length">
                  <div class="muted" style="margin:4px 0">开场钩子（点选一条）：</div>
                  <div v-for="(v,i) in mk.script.hook.variants" :key="i"
                       class="list-item" :class="{sel:mk.hookSel===i}" @click="mk.hookSel=i">● {{ v.text || v }}</div>
                </div>
                <table class="tbl" style="margin-top:8px"><thead><tr><th>段落</th><th>口播</th></tr></thead>
                  <tbody><tr v-for="b in mk.script.beats" :key="b.id">
                    <td><span class="badge" :class="b.role==='hook'||b.role==='payoff' ? 'yellow' : 'blue'">{{ b.role }}</span></td>
                    <td>{{ b.narration }}</td></tr></tbody></table>
                <div style="margin-top:10px">
                  <button class="btn primary" @click="wizardToStep2">用这个脚本制作 →</button></div>
              </template>
            </template>

            <!-- Step 2: 创作设置 -->
            <template v-else-if="mk.step===2">
              <div class="form-row"><label>标题</label>
                <input type="text" v-model="mk.title" maxlength="30" style="flex:1;min-width:280px"
                       placeholder="≤30 字，出片封面与项目名"></div>
              <div class="form-row"><label>画幅</label>
                <select v-model="mk.format" style="width:auto">
                  <option value="horizontal">横版 1920×1080</option>
                  <option value="vertical">竖版 1080×1920</option></select>
                <span v-if="mk.format==='vertical'" class="badge yellow">将按 1080×1920 渲染</span></div>
              <div class="form-row"><label>配音</label>
                <select v-model="mk.voice" style="min-width:280px">
                  <optgroup label="Edge（免费）">
                    <option v-for="v in mkVoiceGroups.edge" :key="v.id" :value="v.id">{{ v.name }}</option>
                  </optgroup>
                  <optgroup label="DashScope" v-if="mkVoiceGroups.dashscope.length">
                    <option v-for="v in mkVoiceGroups.dashscope" :key="v.id" :value="v.id"
                            :disabled="!mkDashOk"
                            :title="mkDashOk ? '' : '未配置 DASHSCOPE_API_KEY'">{{ v.name }}{{ mkDashOk ? '' : '（未配 Key）' }}</option>
                  </optgroup>
                </select></div>
              <div class="form-row"><label>画面编排</label><div class="radio-group">
                <label><input type="radio" value="llm" v-model="mk.enrich" :disabled="!mkLlmReady">
                  AI 编排{{ mkLlmReady ? '' : '（需先在设置页配置翻译模型）' }}</label>
                <label><input type="radio" value="plain" v-model="mk.enrich"> 简洁版式</label></div></div>
              <div class="form-row"><label>视觉风格包</label>
                <select v-model="mk.stylePack" :disabled="mk.busy || mk.format==='vertical'" style="min-width:280px">
                  <option v-for="p in (mk.presets && mk.presets.packs) || []" :key="p.id" :value="p.id">{{ p.name }}</option>
                  <option v-if="!mk.presets || !mk.presets.packs || !mk.presets.packs.length" value="auto">AI 自动（LLM 按内容选型）</option>
                </select>
                <span v-if="mk.format==='vertical'" class="muted">竖版不支持风格包</span></div>
              <div class="form-row"><label>出片模式</label><div class="radio-group">
                <label><input type="radio" value="build" v-model="mk.mode"> 正式成片（TTS 配音 + 渲染）</label>
                <label><input type="radio" value="estimate" v-model="mk.mode"> 无声预览（估时长快出）</label></div></div>
              <div style="margin-top:10px">
                <button class="btn" @click="mk.step=1">← 上一步</button>
                <button class="btn primary" @click="mk.step=3">下一步 →</button></div>
            </template>

            <!-- Step 3: 确认 + 进度 -->
            <template v-else>
              <table class="tbl" v-if="mk.script"><tbody>
                <tr><td style="width:90px" class="muted">标题</td><td>{{ mk.title || '（未命名）' }}</td></tr>
                <tr><td class="muted">画幅</td><td>{{ mk.format==='vertical' ? '竖版 1080×1920' : '横版 1920×1080' }}</td></tr>
                <tr><td class="muted">配音</td><td>{{ mk.voice }} · {{ mk.mode==='estimate' ? '无声预览' : 'TTS 配音' }}</td></tr>
                <tr><td class="muted">画面编排</td><td>{{ mk.enrich==='llm' ? 'AI 编排' : '简洁版式' }}</td></tr>
                <tr><td class="muted">字数</td><td>{{ mkWords }} 字</td></tr>
                <tr><td class="muted">预估时长</td><td>约 {{ mkEstSeconds }} 秒（字数 ÷ 4.2 + 场景数 × 1.5）</td></tr>
                <tr><td class="muted">场景数</td><td>{{ mkBeats.length }} 场</td></tr>
              </tbody></table>
              <h3 style="margin-top:14px">分镜轻编辑</h3>
              <p class="muted">{{ mkWords }} 字 · 约 {{ mkEstSeconds }} 秒 · {{ mkBeats.length }} 场</p>
              <div v-if="mkBeats.length && !mkBeats.some(b => b.role==='cta')" class="notice">脚本已无 CTA 场景，成片将缺少行动引导</div>
              <div v-if="mkEmptyNarrs.length" class="notice">
                <div v-for="n in mkEmptyNarrs" :key="n">场景 {{ n }} 口播为空</div></div>
              <table class="tbl"><thead><tr><th>段落</th><th>口播</th><th>字幕</th><th>屏幕要点</th><th>时长</th><th>操作</th></tr></thead>
                <tbody><tr v-for="(b,i) in mkBeats" :key="i">
                  <td><span class="badge" :class="b.role==='hook'||b.role==='payoff' ? 'yellow' : 'blue'">{{ b.role }}</span></td>
                  <td><textarea rows="2" v-model="b.narration" :disabled="mk.busy" style="width:100%;min-width:100px"></textarea></td>
                  <td><textarea rows="2" v-model="b.subtitle" :disabled="mk.busy" style="width:100%;min-width:80px"></textarea></td>
                  <td><input :value="(b.on_screen||[]).join('、')" @input="setOnScreen(b, $event)" :disabled="mk.busy" style="width:100%;min-width:80px"></td>
                  <td class="mono">{{ b.duration_est_s }}s</td>
                  <td><a v-if="!mk.busy" style="font-size:12px" @click="delBeat(i)">删除</a><span v-else class="muted">删除</span></td>
                </tr></tbody></table>
              <p class="muted" style="margin:8px 0">渲染约 1-5 分钟；期间请勿关闭工作台页面。</p>
              <div v-if="!mk.busy && !mk.err">
                <button class="btn" @click="mk.step=2">← 上一步</button>
                <button class="btn primary" @click="startBuild">开始制作</button></div>
              <div v-if="mk.busy" style="margin:10px 0">
                <div style="display:flex;justify-content:space-between;margin-bottom:4px">
                  <span>{{ mk.progress ? mk.progress.message : '准备中…' }}</span>
                  <span class="mono">{{ mk.progress ? mk.progress.pct : 0 }}%</span></div>
                <span class="bar-track"><span class="bar-fill"
                      :style="{width: (mk.progress ? mk.progress.pct : 0) + '%'}"></span></span>
                <div class="muted" style="margin-top:4px">阶段: {{ mk.progress ? mk.progress.stage : 'queued' }}</div>
              </div>
              <div v-if="mk.err" class="err-box" style="margin-top:10px">
                {{ mk.err }}
                <div style="margin-top:8px">
                  <button class="btn" @click="loadBuildLog">{{ mk.logOpen ? '收起日志' : '查看日志' }}</button>
                  <button class="btn primary" @click="retryBuild">重试</button></div></div>
              <div v-if="mk.logOpen && mk.logLines.length"
                   style="margin-top:8px;max-height:260px;overflow:auto;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:8px">
                <div v-if="mk.logTruncated" class="muted">（仅显示末尾 {{ mk.logLines.length }} 行）</div>
                <pre class="mono" style="white-space:pre-wrap;margin:0"><code v-for="(l,i) in mk.logLines" :key="i">{{ l }}
</code></pre></div>
            </template>
          </div>

          <div class="card" v-else-if="!sel">
            <h3>项目详情</h3>
            <div class="muted">从左侧选择一个视频项目查看详情与预览</div>
          </div>
          <template v-else>
            <div class="card">
              <h3>{{ sel.title }}</h3>
              <p class="muted" style="margin-bottom:10px">项目 {{ sel.id }} · 门禁状态: {{ gateText(sel.status) }}
                <span v-if="sel.verify_mode==='estimate'" class="badge yellow">无声预览版</span></p>
              <div v-if="mk.warn.length && sel && mk.jobPid && sel.id.indexOf(mk.jobPid)===0" class="notice">
                <div v-for="(w,i) in mk.warn" :key="i">{{ w }}</div></div>
              <div v-if="sel.verify_warnings && sel.verify_warnings.length" class="notice">
                <strong>QA 警告</strong><div v-for="(w,i) in sel.verify_warnings" :key="i">{{ w }}</div></div>
              <div v-if="sel.verify_errors && sel.verify_errors.length" class="err-box">
                <div v-for="(e,i) in sel.verify_errors" :key="i">{{ e }}</div></div>
              <video v-if="selMp4" :src="selMp4" controls preload="metadata" style="max-height:420px"></video>
              <img v-else-if="selCover" :src="selCover" class="cover-thumb" style="max-width:280px">
              <div v-else class="muted">尚无渲染产物(out/ 为空)</div>
              <div v-if="sel.mp4.length > 1" class="muted" style="margin-top:6px">
                产物: <span v-for="m in sel.mp4" class="mono" style="margin-right:8px">{{ m }}</span></div>
            </div>
            <div class="card">
              <h3>操作</h3>
              <div class="stub-wrap">
                <button class="btn stub" disabled>投稿 B站/抖音</button>
                <div class="stub-tip">
                  重新出片: <code>python cli.py video build {{ sel.id }}</code><br>
                  投稿(先草稿): <code>{{ pubCmd }}</code> <a style="font-size:12px" @click="copyPubCmd">复制</a>
                </div>
              </div>
              <a style="font-size:12px" @click="delVideo(sel)">删除项目</a>
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
