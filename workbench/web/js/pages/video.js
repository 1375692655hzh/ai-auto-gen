/* 视频页: 热点追踪 + 视频工坊(分析/制作/脚本仓库) + 制作/仓库/追踪账号。 */
window.WB = window.WB || {};
WB.pages = WB.pages || {};

WB.pages.video = {
  data() {
    return {
      tab: "hot",
      /* ── 热点追踪 ── */
      hotItems: [], hotTotal: 0, hotMeta: null, hotInsights: [],
      f: { range: "7d", sort: "views", kind: "all", channel: "", q: "" },   // 默认7d: 低活跃日24h窗口天然为空
      hotLoading: false, hotErr: null,
      voiceTesting: false, voiceTestUrl: "", voiceTestPhrase: "你好，我是特朗普的爷爷，巴菲特的爸爸，鲍威尔的祖宗",
      claimsOpen: false,   // claims 事实账本明细展开
      /* ── 视频分析·本地文件方式 + 历史结果 ── */
      anMode: "url", anWorkflow: "gemini", anPaths: [], anPathIdx: null, anFiles: [], anFile: "",
      anHistory: [], anHistoryLoading: false, anRenaming: '', anRenameTitle: '',
      collecting: false, collectPoll: null,
      /* ── 视频工坊 ── */
      pool: [], poolMeta: null, poolIds: {}, poolSel: null,
      anUrl: '', anRec: null, anBusy: false, anErr: null, anProgress: null,
      jobPolls: { analyze: null, generate: null, voice: null, build: null },
      styles: [], lengthTiers: [], llmOptions: [], drafts: [],
      scripts: [], scriptSel: null, scriptFilter: '', reusableOnly: false,
      /* ── 追踪账号 ── */
      chs: [], chMeta: null, chQ: "",
      chForm: { input: "", note: "" }, showChForm: false, adding: false, chBusyId: "",
      coverForm: { open: false, busy: false, err: '', done: '', title: '', kicker: '', sub: '', bg_asset_id: '', person_asset_id: '' },
      /* ── 视频制作(原视频页内容) ── */
      videos: [], sel: null, error: null,
      /* 四段制作：草稿持久化，任务槽独立恢复。 */
      makes: [], cur: null, blank: null,   /* blank=内存态空白新稿(不落库, 首次编辑才建行) */
      presets: null, narTab: 'a', narBrief: '', narDraftId: '', importId: '',
      makeRoute: 'script',   /* 制作路线: script=文案路线 audio=音频路线(建设中) */
      makeStep: 1,           /* 生成卡内部步骤子页(0913a): 1项目名称/2口播/3脚本/4音频/5视频 */
      narBusy: false, narProgress: null, storyBusy: false, storyProgress: null,
      voiceBusy: false, voiceProgress: null, makeErr: '', narErr: '', scriptErr: '', voiceErr: '',
      buildBusy: false, buildProgress: null, buildErr: '', buildPid: '', buildMakeId: '',
      buildMode: 'build', buildLogOpen: false, buildLogLines: [], buildLogTruncated: false, buildWarnings: [],
      assetUploadBusy: {}, makeActionBusy: false, saveTimers: {}, savePending: {}, saveChains: {},
      saveVersions: {}, saveState: {}, savedAt: {}, renameDraft: null, renameDraftTitle: '', projTitle: '',
      voiceFolderPath: '', outFolderPath: '',
      beatCursors: {}, makeJobIds: {}, disposed: false,
      /* ── 素材 / 模板仓库 ── */
      libAssets: [], libFilter: 'all', libSearch: '', libUpBusy: false,
      previewAsset: null, renamingAsset: null, renamingAssetName: '',
      templatesCards: [], templateDefaults: {}, templateFilter: 'all', templateSearch: '',
      favBusy: false, styleBusy: false,
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
    /* 追踪账号列表过滤: 关键词(频道名/handle/备注/频道ID), 账号多了好找 */
    chRows() {
      const q = (this.chQ || "").trim().toLowerCase();
      if (!q) return this.chs;
      return this.chs.filter((c) =>
        (c.title || "").toLowerCase().includes(q) ||
        (c.handle || "").toLowerCase().includes(q) ||
        (c.note || "").toLowerCase().includes(q) ||
        (c.channel_id || "").toLowerCase().includes(q));
    },
    pendingChs() {
      return this.enabledChs.filter((c) => c.resolve_status === "pending");
    },

    filteredScripts() {
      return (this.scripts || []).filter((r) =>
        (!this.scriptFilter || r.kind === this.scriptFilter) && (!this.reusableOnly || r.reusable));
    },
    libFiltered() {
      const q = this.libSearch.toLowerCase();
      return this.libAssets.filter((a) => (this.libFilter === 'all' || a.kind === this.libFilter) && (a.name || '').toLowerCase().includes(q));
    },
    templatesFiltered() {
      const q = this.templateSearch.toLowerCase();
      return this.templatesCards.filter((c) => (this.templateFilter === 'all' || c.kind === this.templateFilter) && ((c.name || '') + ' ' + (c.blurb || '')).toLowerCase().includes(q));
    },
    curMake() { return this.cur ? (this.makes.find((m) => m.id === this.cur) || null) : this.blank; },
    makeBeats() { return (this.curMake && this.curMake.script && this.curMake.script.beats) || []; },
    /* claims 事实账本：四级分级摘要（写稿期 LLM 产出，随脚本存档锁定） */
    makeClaims() {
      const raw = (this.curMake && this.curMake.script && this.curMake.script.claims) || [];
      const levels = { verified: 0, opinion: 0, pending: 0, high_risk: 0 };
      const items = [];
      for (const c of raw) {
        if (!c || typeof c !== 'object' || !String(c.text || '').trim()) continue;
        const level = Object.prototype.hasOwnProperty.call(levels, c.level) ? c.level : 'pending';
        levels[level] += 1;
        items.push({ text: String(c.text), level, status: String(c.status || ''), source: String(c.source || ''), suggestion: String(c.suggestion || '') });
      }
      return { items, levels, total: items.length };
    },
    narrationWords() { return [...String(this.curMake && this.curMake.narration.text || '').replace(/\s+/g, '')].length; },
    importScripts() { return this.scripts.filter((r) => r.kind === 'generated' && r.script && r.script.beats && r.script.beats.length); },
    ttsProviders() { return ((this.presets && this.presets.tts && this.presets.tts.providers) || []).filter((p) => p.enabled && (p.voices || []).length); },
    makeVoices() { const p = this.ttsProviders.find((p) => this.curMake && p.id === this.curMake.voice.profile_id); return p ? p.voices || [] : []; },
    makeTheme() { return ((this.presets && this.presets.themes) || []).find((t) => this.curMake && t.id === this.curMake.video.theme); },
    /* 右侧步骤子页导航(0913a): 一次只见一个步骤, 状态徽章与分段口径同源 */
    makeSteps() {
      const titled = this.curMake && String(this.curMake.title || '').trim();
      return [
        { n: 1, label: '项目名称', badge: { cls: titled ? 'green' : '', text: titled ? '已命名' : '未命名' } },
        { n: 2, label: '口播稿生成', badge: this.segBadge(1) },
        { n: 3, label: '脚本生成', badge: this.segBadge(2) },
        { n: 4, label: '音频生成', badge: this.segBadge(3) },
        { n: 5, label: '视频生成', badge: this.segBadge(4) },
      ];
    },
    // ── 视觉风格预设(一个选择框): 预设=三元组套餐, 选中即写三字段, id 永不落库 ──
    stylePresetList() { return (this.presets && this.presets.style_presets) || []; },
    resolveMakeMethod(v) {
      // inherit 解析规则源 = vmake inherit 分支(vox-collage 主题或 fast-cut 编排→vox-fast-cut,
      // 否则 template); 仅做展示层两层匹配, 改渲染链须同步此函数
      const gm = v.generation_method || 'inherit';
      if (gm !== 'inherit') return gm;
      return (v.theme === 'vox-collage' || v.layout === 'fast-cut') ? 'vox-fast-cut' : 'template';
    },
    curStylePreset() {
      const v = this.curMake && this.curMake.video; if (!v) return null;
      const rm = this.resolveMakeMethod(v);
      return this.stylePresetList.find((p) => p.theme === v.theme && p.layout === v.layout && p.method_resolved === rm) || null;
    },
    curStylePresetId: {
      get() { return this.curStylePreset ? this.curStylePreset.id : 'custom'; },
      async set(id) {
        const p = this.stylePresetList.find((x) => x.id === id); if (!p || !this.curMake) return;
        const v = this.curMake.video;
        v.theme = p.theme; v.layout = p.layout; v.generation_method = p.generation_method;
        await this.saveMake(); WB.toast('已应用风格：' + p.name + (p.cost_type === 'billed' ? '（生图计费）' : ''));
      },
    },
    customStyleLabel() {
      const v = (this.curMake && this.curMake.video) || {};
      const nm = (rows, id) => { const r = ((this.presets && this.presets[rows]) || []).find((x) => x.id === id); return r ? r.name : (id || '—'); };
      const gm = { inherit: '按主题/编排', template: '模板动效', 'vox-fast-cut': 'VOX拼贴快切', 'vox-collage': 'VOX纸拼贴', 'hand-drawn': '手绘跟随' }[v.generation_method] || v.generation_method || '—';
      return '自定义（' + nm('themes', v.theme) + ' × ' + nm('layouts', v.layout) + ' × ' + gm + '，保持原设置）';
    },
    beatOverrideCount() { return this.curMake ? (this.curMake.video.beat_overrides || []).length : 0; },
    makeBusy() { return this.makeActionBusy || Object.values(this.makeJobIds).includes(this.cur) || Object.keys(this.assetUploadBusy).some((k) => k.startsWith(this.cur + ':') && this.assetUploadBusy[k]); },
    makeVoiceReady() { return this.segBadge(3).cls === 'green'; },
    /* 划分铁律(2026-09-12 用户定): 视频项目列表只摆出了片的成品(built/警告);
       没出片的 project(draft/reviewed/qa_failed 残留)不是成品, 归并到草稿概念, 从列表隐藏。 */
    productVideos() { return (this.videos || []).filter((v) => v.status === "built" || v.status === "built_with_warnings"); },
    orphanVideos() { return (this.videos || []).filter((v) => !(v.status === "built" || v.status === "built_with_warnings")); },
    /* 本项目产出（第四段出片）：在视频项目列表中定位当前制作单的成片 */
    makeProject() {
      const pid = this.curMake && this.curMake.project_id;
      return pid ? (this.videos.find((v) => v.id === pid) || null) : null;
    },
    makeOutUrl() {
      const p = this.makeProject;
      if (!p || !p.mp4 || !p.mp4.length) return '';
      return '/wb-api/videos/' + p.id + '/file/' + (p.mp4.includes('final.mp4') ? 'final.mp4' : p.mp4[0]);
    },

  },
  methods: {
    gateClass(s) { return s === "built" ? "green" : s === "built_with_warnings" ? "yellow" : s === "qa_failed" ? "red" : ""; },
    /* 用户模型(2026-09-12): 出没出片是唯一分界线——没成片的一律「草稿」(含旧 draft/reviewed) */
    gateText(s) { return { draft: "草稿", reviewed: "草稿", built: "已出片",
                           built_with_warnings: "已出片·警告", qa_failed: "QA未过" }[s] || s; },
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
        { id: "make", title: "视频制作", cnt: this.videos.length || "",
          icon: I('<rect x="2" y="2" width="20" height="20" rx="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="17" x2="22" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/>'),
          onPick: () => { this.tab = "make"; this.loadMakePresets().then(() => { if (this.curMake) this.setMakeDefaults(this.curMake); }); this.ensureActiveMake(); } },
        { id: "templates", title: "模板仓库",
          icon: I('<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/>'),
          onPick: () => { this.tab = "templates"; this.loadTemplates(); } },
        { id: "materials", title: "素材仓库",
          icon: I('<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>'),
          onPick: () => { this.tab = "materials"; this.loadLibAssets(); } },
        { id: 'scripts', title: '脚本仓库', cnt: this.scripts.length || '',
          icon: I('<path d="M4 4h16v16H4z"/><path d="M8 8h8M8 12h8M8 16h5"/>'),
          onPick: () => { this.tab = 'scripts'; } },
        { id: "tracked", title: "账号管理", cnt: this.chs.length || "",
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
      this.hotSeq = (this.hotSeq || 0) + 1;       // 快速切筛选: 旧响应不得覆盖新列表
      const mySeq = this.hotSeq;
      try {
        const d = await WB.api.get("/yt/hot?" + this.hotQuery());
        if (mySeq !== this.hotSeq || this.disposed) return;
        this.hotItems = d.items; this.hotTotal = d.total; this.hotMeta = d.meta;
        this.hotInsights = d.insights || [];
      } catch (e) {
        if (mySeq !== this.hotSeq || this.disposed) return;
        this.hotErr = e;
      }
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
        if (this.disposed) return;
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
    clearPoolSel() {
      this.poolSel = null; this.anRec = null; this.anErr = null; this.anUrl = '';
    },
    async selectPool(item) {
      if (this.poolSel && this.poolSel.id === item.id) { this.clearPoolSel(); return; }
      this.poolSel = item; this.anRec = null; this.anErr = null; this.anUrl = item.url || '';
      if (item.analysis_status === 'ok' || item.analysis_status === 'partial') {
        try {
          this.anRec = await WB.api.get('/video-analyses?key=' + encodeURIComponent(item.video_id));
        } catch (e) { if (e.status !== 404) this.anErr = e; }
      }
    },
    /* ── 分析方式: 本地文件(可配置扫描根) ── */
    async loadAnPaths() {
      try {
        const d = await WB.api.get("/analysis-paths");
        this.anPaths = (d.paths || []).filter(p => p.configured);
        if (this.anPaths.length && this.anPathIdx == null) {
          this.anPathIdx = this.anPaths[0].idx;
          this.loadAnFiles();
        }
      } catch (e) {}
    },
    async loadAnFiles() {
      if (this.anPathIdx == null) return;
      this.anLoadingFile = true;
      try {
        const d = await WB.api.get("/analysis-files?idx=" + this.anPathIdx);
        this.anFiles = d.files || [];
        this.anFile = "";
        if (d.error) WB.toast(d.error);
      } catch (e) { this.anFiles = []; }
      this.anLoadingFile = false;
    },
    async loadAnHistory() {
      this.anHistoryLoading = true;
      try { this.anHistory = await WB.api.get("/video-analyses"); }
      catch (e) { this.anHistory = []; }
      this.anHistoryLoading = false;
    },
    async openAnalysis(key) {
      try {
        this.anRec = await WB.api.get("/video-analyses?key=" + encodeURIComponent(key));
      } catch (e) { WB.toast(e.error || "记录载入失败"); }
    },
    /* 语音试听: 用当前选择的供应商+音色念固定台词(Trump 爷爷/巴菲特爸爸/鲍威尔祖宗) */
    async testVoiceListen() {
      const pid = this.curMake && this.curMake.voice.profile_id;
      const voice = this.curMake && this.curMake.voice.voice;
      if (!pid || !voice) { WB.toast("先选择供应商和音色"); return; }
      this.voiceTesting = true; this.voiceTestUrl = "";
      try {
        const d = await WB.api.post("/test-tts",
          { provider_id: pid, voice, text: this.voiceTestPhrase });
        // 版本号在成功这一刻固化一次: 模板里拼 Date.now() 会被 2s 自动保存的
        // 重渲染打断试听(2026-09-11 codex 复审发现)
        this.voiceTestUrl = d.url + "?t=" + Date.now();
      } catch (e) { WB.toast(e.error || "试听失败"); }
      this.voiceTesting = false;
    },
    async startAnalyzeLocal(force) {
      if (!this.anFile) { WB.toast("先选择要分析的视频文件"); return; }
      this.anErr = null;
      try {
        await WB.api.post("/video-analyze", { local_path: this.anFile, force: !!force });
        this.anBusy = true; this.pollJob('analyze');
      } catch (e) {
        if (e.status === 409) { WB.toast("分析进行中"); this.anBusy = true; this.pollJob('analyze'); }
        else WB.toast(e.error + (e.hint ? " — " + e.hint : ""));
      }
    },
    async startAnalyze(force) {
      const url = (this.anUrl || '').trim();
      if (!url && !this.poolSel) { WB.toast('请选择素材或粘贴 YouTube 链接'); return; }
      this.anErr = null;
      try {
        await WB.api.post('/video-analyze', {
          pool_id: this.poolSel ? this.poolSel.id : undefined,
          url: url || undefined, force: !!force, workflow: this.anWorkflow,
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
        if (this.disposed) return;
        let jobs;
        try { jobs = await WB.api.get('/video-jobs'); }
        catch (e) {
          if (this.disposed) return;
          WB.toast(this.makeError(e) + '，稍后重连任务进度');
          this.jobPolls[kind] = setTimeout(tick, 5000); return;
        }
        if (this.disposed) return;
        const job = jobs[kind] || {}, task = (job.request || {}).task;
        this.adoptMakeJob(kind, job);
        if (kind === 'analyze') this.anProgress = job.progress || null;
        else if (kind === 'build') this.buildProgress = job.progress || null;
        else if (kind === 'voice') this.voiceProgress = job.progress || null;
        else if (task === 'narration') this.narProgress = job.progress || null;
        else if (task === 'storyboard') this.storyProgress = job.progress || null;
        if (job.running) { this.jobPolls[kind] = setTimeout(tick, 3000); return; }
        this.jobPolls[kind] = null;
        if (kind === 'analyze') this.anBusy = false;
        else if (kind === 'build') this.buildBusy = false;
        else if (kind === 'voice') this.voiceBusy = false;
        else { this.narBusy = false; this.storyBusy = false; }
        delete this.makeJobIds[kind];
        if (job.exit === 0) {
          if (kind === 'analyze') {
            try {
              this.anRec = await WB.api.get('/video-analyses?key=' + encodeURIComponent(job.result_key));
              await this.loadPool(); WB.toast('分析完成');
            } catch (e) { WB.toast(e.error); }
          } else if (kind === 'build') {
            await this.refreshMakeJob(job);
            const pid = (job.request && job.request.project_id) || this.buildPid;
            const hit = this.videos.find((v) => pid && v.id.indexOf(pid) === 0);
            if (hit) this.sel = hit;
            this.buildWarnings = (job.result && job.result.warnings) || [];
            this.buildErr = '';
            WB.toast('视频已生成' + (hit ? ': ' + this.cut(hit.title, 18) : ''));
          } else if (kind === 'voice' || task === 'narration' || task === 'storyboard') {
            await this.refreshMakeJob(job);
            WB.toast(kind === 'voice' ? '语音已生成' : task === 'narration' ? '口播稿已生成' : '分镜脚本已生成');
          } else {
            WB.toast('独立生成页已下线，产物可在脚本仓库查看');
          }
        } else {
          const msg = this.makeError(job.error ? job : { error: '任务失败', hint: job.hint });
          if (kind === 'build') this.buildErr = msg;
          else if (kind === 'voice') this.voiceErr = msg;
          else if (task === 'narration') this.narErr = msg;
          else if (task === 'storyboard') this.scriptErr = msg;
          else WB.toast(msg);
          if (kind === 'build' || kind === 'voice' || task === 'narration' || task === 'storyboard') await this.refreshMakeJob(job);
        }
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
      try { const d = await WB.api.get('/video-script/styles'); this.styles = d.styles || []; this.lengthTiers = d.length_tiers || []; this.llmOptions = d.llm_options || []; }
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
    /* ── 全局素材仓库 ── */
    async loadLibAssets() {
      try {
        const d = await WB.api.get('/video-assets'); this.libAssets = d.assets || [];
        if (this.previewAsset) this.previewAsset = this.libAssets.find((a) => a.asset_id === this.previewAsset.asset_id) || null;
      } catch (e) { WB.toast(this.makeError(e)); }
    },
    libKindName(k) { return { image: '图片', video: '视频', audio: '音频' }[k] || k; },
    fmtSize(n) {
      if (n == null) return '—';
      return n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : n >= 1024 ? (n / 1024).toFixed(1) + ' KB' : n + ' B';
    },
    assetFileUrl(a) { return '/wb-api/video-assets/' + encodeURIComponent(a.asset_id) + '/file'; },
    libRefsTitle(a) { return (a.refs || []).length ? '被引用: ' + a.refs.map((r) => r.title + '×' + r.beat_id).join('、') : ''; },
    validLibFile(file, want) {
      const ext = file.name.split('.').pop().toLowerCase();
      const kind = ['png','jpg','jpeg','webp'].includes(ext) ? 'image' : ['mp4','webm'].includes(ext) ? 'video' : ['mp3','wav','m4a'].includes(ext) ? 'audio' : '';
      if (!kind || (want && want !== kind)) { WB.toast(file.name + '：素材格式不支持或与当前方法不符'); return false; }
      const limit = { image: 15, video: 100, audio: 30 }[kind];
      if (!file.size || file.size > limit * 1024 * 1024) { WB.toast(file.name + '：文件为空或超过 ' + limit + ' MB'); return false; }
      return true;
    },
    async uploadLibAssets(ev) {
      const files = Array.from(ev.target.files || []); ev.target.value = '';
      if (this.libUpBusy || !files.length) return;
      this.libUpBusy = true;
      try {
        for (const file of files) {
          if (!this.validLibFile(file)) continue;
          try {
            const q = new URLSearchParams({ name: file.name });
            const resp = await fetch('/wb-api/video-assets?' + q, { method: 'PUT', body: file });
            const d = await resp.json(); if (!resp.ok) throw d;
          } catch (e) { WB.toast(file.name + '：' + this.makeError(e)); }
        }
        await this.loadLibAssets();
      } finally { this.libUpBusy = false; }
    },
    startRenameAsset(a) { this.renamingAsset = a.asset_id; this.renamingAssetName = a.name; },
    async saveRenameAsset(a) {
      const name = this.renamingAssetName.trim();
      if (!name) { WB.toast('请输入素材名称'); return; }
      try {
        await WB.api.post('/video-assets/' + encodeURIComponent(a.asset_id) + '/rename', { name });
        this.renamingAsset = null; await this.loadLibAssets();
      } catch (e) { WB.toast(this.makeError(e)); }
    },
    async deleteAsset(a) {
      if (!confirm('删除素材「' + a.name + '」？')) return;
      try {
        const path = '/video-assets/' + encodeURIComponent(a.asset_id);
        let d;
        try { d = await WB.api.del(path); }
        catch (e) {
          if (e.status !== 409) throw e;
          const refs = (this.libAssets.find((x) => x.asset_id === a.asset_id) || {}).refs || [];
          if (!confirm('该素材被 ' + refs.length + ' 个制作引用：\n' + refs.map((r) => '· ' + r.title + ' × ' + r.beat_id).join('\n') + '\n强制删除将清空这些拍的素材选择，继续？')) return;
          d = await WB.api.del(path + '?force=1');
        }
        // 同步本地选择，避免后续保存把已清空的引用写回。
        for (const m of this.makes) {
          for (const o of (m.video && m.video.beat_overrides) || []) {
            if (o.asset_id === a.asset_id) delete o.asset_id;
          }
        }
        if (this.previewAsset && this.previewAsset.asset_id === a.asset_id) this.closePreview();
        if (this.renamingAsset === a.asset_id) this.renamingAsset = null;
        WB.toast('已删除素材，清空 ' + (d.cleared_overrides || 0) + ' 处逐拍素材选择');
        await this.loadLibAssets();
      } catch (e) { WB.toast(this.makeError(e)); }
    },
    openPreview(a) { this.previewAsset = a; },
    closePreview() { this.previewAsset = null; },
    goMaterials() { this.tab = 'materials'; this.loadLibAssets(); this.registerSubs(); },
    /* ── 模板仓库 ── */
    async loadTemplates() {
      try {
        const d = await WB.api.get('/video-templates');
        this.templatesCards = d.cards || []; this.templateDefaults = d.defaults || {};
        this.registerSubs();
      } catch (e) { WB.toast(this.makeError(e)); }
    },
    cardOf(kind, id) { return this.templatesCards.find((c) => c.kind === kind && c.id === id); },
    isFav(key) { return (this.templateDefaults.favorites || []).includes(key); },
    isDefault(kind, id) { return this.templateDefaults['default_' + { theme: 'theme', layout: 'layout', method: 'generation_method' }[kind]] === id; },
    async toggleFav(card) {
      if (this.favBusy || this.styleBusy) return;
      this.favBusy = true;
      try {
        const d = await WB.api.post('/video-style', { favorite: { key: card.key, on: !this.isFav(card.key) } });
        this.templateDefaults = d.video_studio || {};
      } catch (e) { WB.toast(this.makeError(e)); }
      finally { this.favBusy = false; }
    },
    async setDefault(card) {
      if (this.styleBusy || this.favBusy) return;
      this.styleBusy = true;
      try {
        const key = 'default_' + { theme: 'theme', layout: 'layout', method: 'generation_method' }[card.kind];
        const d = await WB.api.post('/video-style', { [key]: card.id });
        this.templateDefaults = d.video_studio || {};
        WB.toast('已设为默认，对新建制作生效');
      } catch (e) { WB.toast(this.makeError(e)); }
      finally { this.styleBusy = false; }
    },
    groupCards(kind) { return this.templatesFiltered.filter((c) => c.kind === kind); },
    async useScriptInMake(r) {
      if (!r || !r.script || !this.importScripts.some((x) => x.id === r.id) || this.makeBusy) return;
      if (!confirm('将导入该脚本：拼接逐拍口播→定稿口播稿→写入分镜并定稿，继续？')) return;
      this.scriptErr = '';
      try {
        this.tab = 'make'; this.registerSubs();
        // newMake 自带忙碌保护，须在导入置忙前调用。
        if (!this.cur) await this.materializeBlank();
        if (!this.cur) throw { error: this.makeErr || '新建制作失败' };
        this.makeActionBusy = true;
        const id = this.cur, script = JSON.parse(JSON.stringify(r.script));
        await this.flushMake(id);
        await WB.api.post('/video-makes/' + id + '/unlock-narration', {});
        await WB.api.post('/video-makes', { id, title: script.title || r.title,
          narration: { text: script.beats.map((b) => b.narration || '').join(''), source: 'import', style_id: r.style_id || script.style_id || '' } });
        await WB.api.post('/video-makes/' + id + '/lock-narration', {});
        if (this.curMake.script_meta.locked) await WB.api.post('/video-makes/' + id + '/unlock-script', {});
        await WB.api.post('/video-makes', { id, script });
        await this.fetchMake(id);
        WB.toast('已导入到当前制作');
      } catch (e) { this.scriptErr = this.makeError(e); }
      finally { this.makeActionBusy = false; }
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
    /* ── 视频项目 ── */
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
    async cleanOrphanVideos() {
      const rows = this.orphanVideos;
      if (!rows.length) return;
      const preview = rows.map((v) => '· ' + (v.title || v.id)).slice(0, 8).join(' / ');
      if (!confirm('清理 ' + rows.length + ' 个未出片的残留项目？' + preview + (rows.length > 8 ? ' …' : '') + ' —— 这些项目没有成片，删除后不可恢复')) return;
      for (const v of rows) {
        try { await WB.api.del('/videos/' + v.id); } catch (e) {}
      }
      WB.toast('已清理 ' + rows.length + ' 个残留项目');
      await this.loadVideos();
    },
    copyPubCmd() { WB.copyText(this.pubCmd); },
    makeError(e) { return String(e.error || e.message || e || '请求失败') + (e.hint ? ' — ' + e.hint : ''); },
    anStartRename(h) { this.anRenaming = h.key; this.anRenameTitle = h.title || ''; },
    async anSubmitRename(h) {
      const title = this.anRenameTitle.trim();
      if (!title) return;
      try {
        await WB.api.post('/video-analyses/' + encodeURIComponent(h.key) + '/rename', { title });
        h.title = title; this.anRenaming = '';
        if (this.anRec && this.anRec.key === h.key) this.anRec.title = title;
      } catch (e) { WB.toast(this.makeError(e)); }
    },
    async anDelete(h) {
      if (!confirm('删除分析「' + (h.title || h.key) + '」？\n只删这份分析报告，素材池与视频项目不受影响')) return;
      try {
        await WB.api.del('/video-analyses/' + encodeURIComponent(h.key));
        this.anHistory = this.anHistory.filter((x) => x.key !== h.key);
        if (this.anRec && this.anRec.key === h.key) this.anRec = null;
      } catch (e) { WB.toast(this.makeError(e)); }
    },
    coverAssetName(field) { const a = this.libAssets.find((x) => x.asset_id === this.coverForm[field]); return a && a.name; },
    async uploadCoverAsset(field, ev) {
      const file = ev.target.files && ev.target.files[0]; ev.target.value = '';
      if (!file) return;
      this.coverForm.err = '';
      try {
        const q = new URLSearchParams({ name: file.name });
        const resp = await fetch('/wb-api/video-assets?' + q, { method: 'PUT', body: file });
        const d = await resp.json(); if (!resp.ok) throw d;
        this.coverForm[field] = d.asset.asset_id;
        await this.loadLibAssets();
      } catch (e) { this.coverForm.err = this.makeError(e); }
    },
    async submitCover() {
      if (this.coverForm.busy || !this.curMake.project_id) return;
      this.coverForm.busy = true; this.coverForm.err = ''; this.coverForm.done = '';
      try {
        const d = await WB.api.post('/videos/' + encodeURIComponent(this.curMake.project_id) + '/cover', {
          title: this.coverForm.title, kicker: this.coverForm.kicker, sub: this.coverForm.sub,
          bg_asset_id: this.coverForm.bg_asset_id, person_asset_id: this.coverForm.person_asset_id });
        this.coverForm.done = '封面已生成 ' + (d.output || 'out/cover.png') + '（成片文件夹内查看）';
        this.coverForm.open = false;
      } catch (e) { this.coverForm.err = this.makeError(e); }
      finally { this.coverForm.busy = false; }
    },
    normalizeMake(m) {
      const nar = { text: '', ref_text: '', style_id: '', source: '', locked: false, length_s: 0, fidelity: 'faithful', llm_source: 'compose:0', ...m.narration };
      // 旧档存的 compose/translate 已废弃(2026-09-12 供应商改全量成稿链), 一律归链首
      if (!String(nar.llm_source || '').startsWith('compose:')) nar.llm_source = 'compose:0';
      return { ...m, narration: nar,
        script_meta: { locked: false, ...m.script_meta }, voice: { profile_id: '', voice: '', voice_key: '', items: {}, ...m.voice },
        assets: m.assets || [], voice_bad: m.voice_bad || [],
        video: { mode: 'unified', aspect: '16:9', fps: 30, theme: 'terminal-dark', layout: 'auto',
          enrich: 'plain', generation_method: 'inherit', image_budget: 8, hook_index: 0, beat_overrides: [], ...m.video } };
    },
    putMake(m) {
      if (!m) throw { error: '未收到制作草稿' };
      const row = this.normalizeMake(m), i = this.makes.findIndex((r) => r.id === row.id);
      if (i < 0) this.makes.unshift(row); else this.makes.splice(i, 1, row);
      return row;
    },
    async loadMakePresets() {
      try { this.presets = await WB.api.get('/video-presets'); }
      catch (e) { this.makeErr = this.makeError(e); }
    },
    async loadMakes() {
      try {
        const rows = (await WB.api.get('/video-makes')).makes || [], local = this.makes;
        // Other jobs finishing must not erase pending keystrokes in this editor.
        this.makes = rows.map((m) => (this.saveState[m.id] === 'saving' || this.savePending[m.id])
          ? local.find((r) => r.id === m.id) || this.normalizeMake(m) : this.normalizeMake(m));
        this.makeErr = '';
      } catch (e) { this.makeErr = this.makeError(e); }
    },
    async fetchMake(id) { return this.putMake((await WB.api.get('/video-makes/' + encodeURIComponent(id))).make); },
    newBlank() {
      /* 内存态空白新稿(2026-09-12 用户模型: 编辑区=永远在写的新稿; 不进草稿箱不落库,
         首次真实编辑才 materialize 建行。默认值须对齐配置的默认模板, 否则落库时
         terminal-dark 硬编码会静默覆盖用户在模板页设的默认主题/编排/生成方式) */
      const td = this.templateDefaults || {};
      const m = this.normalizeMake({ id: '', title: '' });
      if (td.default_theme) m.video.theme = td.default_theme;
      if (td.default_layout) m.video.layout = td.default_layout;
      if (td.default_generation_method) m.video.generation_method = td.default_generation_method;
      m._blank = true;
      this.blank = m;
      this.narTab = 'b'; this.narBrief = ''; this.narDraftId = ''; this.importId = '';
      this.beatCursors = {};
      this.narErr = ''; this.scriptErr = ''; this.voiceErr = '';
      this.setMakeDefaults(m);
    },
    materializeBlank() {
      /* 空白新稿首次落库: 建行→把 blank 内容并入新行→收养真 id。竞态: 连续打字只建一次。 */
      if (this.cur) return Promise.resolve(this.cur);
      if (this._materializing) return this._materializing;
      const blank = this.blank;
      if (!blank) return Promise.resolve(null);
      this._materializing = (async () => {
        try {
          const row = this.putMake((await WB.api.post('/video-makes', {})).make);
          row.title = blank.title;
          row.narration = { ...row.narration, ...JSON.parse(JSON.stringify(blank.narration)) };
          row.voice = { ...row.voice, ...JSON.parse(JSON.stringify(blank.voice)) };
          row.video = { ...row.video, ...JSON.parse(JSON.stringify(blank.video)) };
          if (blank.script) row.script = blank.script;
          if (!this.cur) this.cur = row.id;         // 期间用户已点选别的草稿则不抢焦点
          if (this.blank === blank) this.blank = null;
          this.saveMake(row); await this.flushMake(row.id);
          return row.id;
        } catch (e) { this.makeErr = this.makeError(e); return null; }
        finally { this._materializing = null; }
      })();
      return this._materializing;
    },
    async unloadMake() {
      /* 再点已选中的草稿行 = 卸载回空白新稿(当前草稿自动保存留箱) */
      try { if (this.cur) await this.flushMake(this.cur); } catch (e) {}
      this.cur = null;
      this.newBlank();
    },
    async selectMake(id) {
      if (this.makeActionBusy) return;
      if (this.cur === id) { await this.unloadMake(); return; }
      try {
        if (this.cur) await this.flushMake(this.cur);
        const m = await this.fetchMake(id);
        this.cur = m.id; this.blank = null; this.narTab = m.narration.source === 'manual' ? 'b' : 'a';
        this.narBrief = ''; this.narDraftId = ''; this.importId = ''; this.beatCursors = {};
        this.narErr = ''; this.scriptErr = ''; this.voiceErr = ''; this.setMakeDefaults(m);
      } catch (e) { this.makeErr = this.makeError(e); }
    },
    setMakeDefaults(m) {
      let changed = false;
      if (!m.narration.style_id && this.styles.length) {
        const defStyle = this.styles.find((s) => s.default) || this.styles[0];
        m.narration.style_id = defStyle.id; changed = true;
      }
      const def = (this.presets && this.presets.tts && this.presets.tts.default) || {};
      const current = this.ttsProviders.find((p) => p.id === m.voice.profile_id);
      const p = current || this.ttsProviders.find((x) => x.id === def.provider_id) || this.ttsProviders[0];
      if (p) {
        const voices = p.voices || [];
        const voiceOk = voices.some((v) => v.id === m.voice.voice);
        if (!current) {
          m.voice.profile_id = p.id;
          m.voice.voice = voices.some((v) => v.id === def.voice) ? def.voice : ((voices[0] || {}).id || '');
          m.voice.items = {}; m.voice.voice_key = ''; m.voice_bad = [];
          changed = true;
        } else if (!voiceOk) {
          m.voice.voice = voices.some((v) => v.id === def.voice) ? def.voice : ((voices[0] || {}).id || '');
          m.voice.items = {}; m.voice.voice_key = ''; m.voice_bad = [];
          changed = true;
        }
      }
      if (changed && !m._blank) this.saveMake(m);
    },
    async ensureActiveMake() {
      /* 2026-09-12 纠偏: 进页/刷新默认空白新稿(不落库), 不再自动载入最近草稿——
         否则编辑区永远被旧稿占用, 到不了新稿状态 */
      if (this.cur) return;
      if (!this.blank) this.newBlank();
    },
    async newMake() {
      if (this.makeActionBusy) return;
      this.makeActionBusy = true;
      try {
        if (this.cur) await this.flushMake(this.cur);
        const m = this.putMake((await WB.api.post('/video-makes', {})).make);
        this.cur = m.id; this.narTab = 'b'; this.narBrief = ''; this.narDraftId = ''; this.importId = '';
        this.narErr = ''; this.scriptErr = ''; this.voiceErr = ''; this.setMakeDefaults(m);
      } catch (e) { this.makeErr = this.makeError(e); }
      finally { this.makeActionBusy = false; }
    },
    async duplicateMake(m) {
      try {
        await this.flushMake(m.id);
        const row = this.putMake((await WB.api.post('/video-makes/' + m.id + '/duplicate', {})).make);
        await this.selectMake(row.id);
      } catch (e) { this.makeErr = this.makeError(e); }
    },
    async deleteMake(m) {
      if (Object.values(this.makeJobIds).includes(m.id)) { WB.toast('该草稿正在执行任务，请收尾后删除'); return; }
      if (!confirm('删除制作草稿「' + m.title + '」及其语音和素材？删除后不可恢复')) return;
      try {
        await this.flushMake(m.id); await WB.api.del('/video-makes/' + m.id);
        this.makes = this.makes.filter((r) => r.id !== m.id);
        if (this.cur === m.id) { this.cur = null; await this.ensureActiveMake(); }
      } catch (e) { this.makeErr = this.makeError(e); }
    },
    makePayload(m) {
      const p = { id: m.id, title: m.title, video: m.video, voice: { profile_id: m.voice.profile_id, voice: m.voice.voice } };
      if (!m.narration.locked) p.narration = { text: m.narration.text, ref_text: m.narration.ref_text, source: m.narration.source, style_id: m.narration.style_id };
      if (!m.script_meta.locked && m.script) p.script = m.script;
      return JSON.parse(JSON.stringify(p));
    },
    saveMake(m = this.curMake) {
      if (!m) return;
      if (m._blank) { this.materializeBlank(); return; }
      if (!m.id) return;
      this.saveVersions[m.id] = (this.saveVersions[m.id] || 0) + 1;
      this.savePending[m.id] = { body: this.makePayload(m), version: this.saveVersions[m.id] };
      this.saveState[m.id] = 'pending'; clearTimeout(this.saveTimers[m.id]);
      this.saveTimers[m.id] = setTimeout(() => this.flushMake(m.id).catch(() => {}), 2000);
    },
    async flushMake(id = this.cur) {
      if (!id) return;
      clearTimeout(this.saveTimers[id]);
      const pending = this.savePending[id];
      if (!pending) return this.saveChains[id];
      delete this.savePending[id];
      const chain = (this.saveChains[id] || Promise.resolve()).catch(() => {}).then(async () => {
        this.saveState[id] = 'saving';
        try {
          const d = await WB.api.post('/video-makes', pending.body);
          const full = await WB.api.get('/video-makes/' + id);
          if (this.saveVersions[id] === pending.version) {
            this.putMake(full.make || d.make);
            this.savedAt = { ...this.savedAt, [id]: new Date().toTimeString().slice(0, 8) };
            this.saveState[id] = 'saved';
          }
        } catch (e) {
          if (!this.savePending[id] && this.saveVersions[id] === pending.version) this.savePending[id] = pending;
          this.saveState[id] = 'error'; this.makeErr = '自动保存失败：' + this.makeError(e); throw e;
        }
      });
      this.saveChains[id] = chain; return chain;
    },
    startRenameDraft(m) { this.renameDraft = m.id; this.renameDraftTitle = m.title; },
    async saveRenameDraft(m) {
      const t = this.renameDraftTitle.trim();
      if (!t) { WB.toast('标题不能为空'); return; }
      try {
        await WB.api.post('/video-makes', { id: m.id, title: t });
        m.title = t;
        if (this.cur === m.id && this.curMake) this.curMake.title = t;
        this.savedAt = { ...this.savedAt, [m.id]: new Date().toTimeString().slice(0, 8) };
        this.renameDraft = null;
        WB.toast('已重命名');
      } catch (e) { WB.toast(this.makeError(e)); }
    },
    openProj(v) { this.sel = v; this.projTitle = v.title; },
    async saveProjTitle() {
      if (!this.sel) return;
      const t = (this.projTitle || '').trim();
      if (!t) { WB.toast('标题不能为空'); return; }
      try {
        const d = await WB.api.post('/videos/' + this.sel.id + '/rename', { title: t });
        this.sel.title = d.title || t; this.projTitle = d.title || t;
        WB.toast('已重命名');
      } catch (e) { WB.toast(this.makeError(e)); }
    },
    segBadge(stage, m = this.curMake) {
      const badge = (cls, text) => ({ cls, text });
      if (!m) return badge('', '未开始');
      const beats = (m.script || {}).beats || [], items = (m.voice || {}).items || {};
      const covered = beats.length && beats.every((b) => items[b.id]);
      if (stage === 1) return m.narration.locked ? badge('green', '已定稿') : m.narration.text || m.narration.ref_text ? badge('blue', '编辑中') : badge('', '未开始');
      if (stage === 2) return m.script_stale ? badge('yellow', '待刷新') : m.script_meta.locked ? badge('green', '已定稿') : m.script ? badge('blue', '编辑中') : badge('', '未开始');
      if (stage === 3) return (m.voice_bad || []).length || (Object.keys(items).length && m.script_stale) ? badge('yellow', '待刷新') : covered ? badge('green', '已就绪') : Object.keys(items).length || m.voice.voice_key ? badge('blue', '编辑中') : badge('', '未开始');
      if (m.status === 'rendering') return badge('blue', '制作中');
      if (m.last_build && (m.script_stale || (m.voice_bad || []).length || m.status !== 'built')) return badge('yellow', '待刷新');
      return m.status === 'built' || m.last_build ? badge('green', '已完成') : badge('', '未开始');
    },
    segColor(stage, m) { return { green: 'var(--green)', yellow: 'var(--yellow)', blue: 'var(--accent)' }[this.segBadge(stage, m).cls] || 'var(--text-mute)'; },
    narrationInput() { this.curMake.narration.source = this.narTab === 'b' ? 'manual' : 'generated'; this.saveMake(); },
    pickNarrationDraft() {
      const d = this.drafts.find((d) => d.id === this.narDraftId);
      if (d) { this.curMake.narration.ref_text = d.content || ''; this.saveMake(); }
    },
    readNarrationFile(ev) {
      const file = ev.target.files && ev.target.files[0], id = this.cur; ev.target.value = '';
      if (!file) return;
      if (file.size > 200 * 1024 || !/\.(txt|md)$/i.test(file.name)) { WB.toast('仅支持 .txt/.md，文件不能超过 200KB'); return; }
      const reader = new FileReader();
      reader.onload = () => {
        const m = this.makes.find((m) => m.id === id) || (id ? null : this.blank);
        if (m && !m.narration.locked && !Object.values(this.makeJobIds).includes(id)) { m.narration.ref_text = String(reader.result || ''); this.saveMake(m); }
      };
      reader.onerror = () => WB.toast('文稿文件读取失败'); reader.readAsText(file);
    },
    async makeLock(stage, unlock = false) {
      if (!this.curMake || this.makeBusy) return;
      if (!this.cur) await this.materializeBlank();
      if (!this.cur) return;
      if (unlock && stage === 'narration' && !confirm('解锁重定稿后，下游脚本/语音将标记待刷新')) return;
      this.makeActionBusy = true;
      const key = stage === 'narration' ? 'narErr' : 'scriptErr', id = this.cur; this[key] = '';
      try {
        await this.flushMake(id);
        await WB.api.post('/video-makes/' + id + '/' + (unlock ? 'unlock-' : 'lock-') + stage, {}); await this.fetchMake(id);
      } catch (e) { this[key] = this.makeError(e); }
      finally { this.makeActionBusy = false; }
    },
    async importMakeScript() {
      const r = this.importScripts.find((r) => r.id === this.importId);
      if (!r || this.makeBusy) return;
      if (!confirm('导入会用脚本逐拍口播替换并定稿当前口播稿，继续？')) { this.importId = ''; return; }
      this.makeActionBusy = true; this.scriptErr = '';
      const id = this.cur, script = JSON.parse(JSON.stringify(r.script));
      try {
        await this.flushMake(id); await WB.api.post('/video-makes/' + id + '/unlock-narration', {});
        await WB.api.post('/video-makes', { id, title: script.title || r.title,
          narration: { text: script.beats.map((b) => b.narration || '').join(''), source: 'import', style_id: r.style_id || script.style_id || '' } });
        await WB.api.post('/video-makes/' + id + '/lock-narration', {});
        if (this.curMake.script_meta.locked) await WB.api.post('/video-makes/' + id + '/unlock-script', {});
        await WB.api.post('/video-makes', { id, script });
      } catch (e) { this.scriptErr = this.makeError(e); }
      finally {
        try { await this.fetchMake(id); } catch (e) { this.scriptErr = this.makeError(e); }
        this.makeActionBusy = false;
      }
    },
    changeBeatScreen(b, ev) { b.on_screen = ev.target.value.split(/[、,，]/).map((s) => s.trim()).filter(Boolean); this.saveMake(); },
    splitMakeBeat(i) {
      const b = this.makeBeats[i], n = this.beatCursors[b.id], text = b.narration || '';
      if (!n || !text.slice(0, n).trim() || !text.slice(n).trim()) { WB.toast('先在该拍口播文字中点击拆分位置，两半均须非空'); return; }
      let id = b.id + 'b'; while (this.makeBeats.some((b) => b.id === id)) id += 'b';
      const next = { ...JSON.parse(JSON.stringify(b)), id, narration: text.slice(n) };
      b.narration = text.slice(0, n); this.makeBeats.splice(i + 1, 0, next); this.afterBeatEdit();
    },
    mergeMakeBeat(i) {
      if (i >= this.makeBeats.length - 1) return;
      const b = this.makeBeats[i], next = this.makeBeats[i + 1];
      b.narration += next.narration || ''; b.subtitle = (b.subtitle || '') + (next.subtitle || '');
      b.on_screen = [...(b.on_screen || []), ...(next.on_screen || [])]; this.makeBeats.splice(i + 1, 1); this.afterBeatEdit();
    },
    removeMakeBeat(i) {
      const b = this.makeBeats[i];
      const warning = b.role === 'cta' && this.makeBeats.filter((b) => b.role === 'cta').length === 1 ? '\n删除后 CTA 唯一性失守' : '';
      if (!confirm('删除第 ' + (i + 1) + ' 拍？' + warning)) return;
      this.makeBeats.splice(i, 1); this.afterBeatEdit();
    },
    afterBeatEdit() {
      const m = this.curMake;
      m.video.beat_overrides = m.video.beat_overrides.filter((o) => this.makeBeats.some((b) => b.id === o.beat_id));
      this.makeBeats.forEach((b) => { b.duration_est_s = Math.round(String(b.narration || '').replace(/\s+/g, '').length / 4.2); });
      m.script.word_count = this.makeBeats.reduce((n, b) => n + String(b.narration || '').replace(/\s+/g, '').length, 0);
      m.script.duration_est_s = this.makeBeats.reduce((n, b) => n + b.duration_est_s, 0); this.saveMake();
    },
    changeMakeProvider() { this.curMake.voice.voice = (this.makeVoices[0] || {}).id || ''; this.changeMakeVoice(); },
    changeMakeVoice() { this.curMake.voice.items = {}; this.curMake.voice.voice_key = ''; this.curMake.voice_bad = []; this.saveMake(); },
    voiceUrl(b) {
      const m = this.curMake, item = m.voice.items[b.id] || {};
      return '/wb-api/video-voice/' + encodeURIComponent(m.id) + '/' + encodeURIComponent(m.voice.voice_key) + '/' + encodeURIComponent(b.id) + '.mp3?v=' + encodeURIComponent(item.hash || '') + '-' + encodeURIComponent(m.updated_at || '');
    },
    adoptMakeJob(kind, job) {
      const req = job.request || {};
      if (job.running && req.make_id) this.makeJobIds[kind] = req.make_id;
      if (kind === 'generate') {
        this.narBusy = !!job.running && req.task === 'narration'; this.storyBusy = !!job.running && req.task === 'storyboard';
      } else if (kind === 'voice') this.voiceBusy = !!job.running;
      else if (kind === 'build') { this.buildBusy = !!job.running; this.buildPid = req.project_id || this.buildPid; this.buildMakeId = req.make_id || ''; }
    },
    async refreshMakeJob(job) {
      await Promise.all([this.loadMakes(), this.loadVideos()]);
      const id = (job.request || {}).make_id || (job.result || {}).make_id;
      if (id && !this.savePending[id] && this.saveState[id] !== 'saving') {
        try { await this.fetchMake(id); } catch (e) { this.makeErr = this.makeError(e); }
      }
    },
    async runMakeJob(task, scope = 'all') {
      if (this.makeBusy) return;
      if (!this.cur) await this.materializeBlank(); if (!this.cur) return;
      const id = this.cur, kind = task === 'voice' ? 'voice' : task === 'build' ? 'build' : 'generate';
      const errKey = { voice: 'voiceErr', build: 'buildErr', narration: 'narErr', storyboard: 'scriptErr' }[task];
      this[errKey] = ''; this.makeActionBusy = true;
      try {
        await this.flushMake(id); const m = this.curMake;
        const payload = task === 'narration' ? { make_id: id, brief: this.narBrief, ref_text: m.narration.ref_text, style_id: m.narration.style_id, length_s: m.narration.length_s || 0, fidelity: m.narration.fidelity || 'faithful', llm_source: m.narration.llm_source || 'compose:0' }
          : task === 'voice' ? { make_id: id, provider_id: m.voice.profile_id, voice: m.voice.voice, scope }
          : task === 'build' ? { make_id: id, mode: this.buildMode } : { make_id: id };
        const d = await WB.api.post(task === 'build' ? '/video-build' : '/video-' + task + '/generate', payload);
        if (task === 'build') { this.buildPid = d.project_id || ''; this.buildLogOpen = false; this.buildLogLines = []; this.buildWarnings = []; }
        this.adoptMakeJob(kind, { running: true, request: { ...payload, task, project_id: d.project_id } }); this.pollJob(kind);
      } catch (e) {
        if (e.status === 409) {
          try {
            const jobs = await WB.api.get('/video-jobs'); this.adoptMakeJob(kind, jobs[kind] || {}); this.pollJob(kind);
            WB.toast('任务槽已占用，已接入现有任务进度；本次请求未新建任务');
          } catch (err) { this[errKey] = this.makeError(err); }
        } else this[errKey] = this.makeError(e);
      } finally { this.makeActionBusy = false; }
    },
    changeMakeAspect() {
      const v = this.curMake.video;
      if (v.aspect !== '16:9') WB.toast('此画幅不支持 VOX / 手绘 / 上传，请明确改选模板动效；不兼容配置会阻止制作');
      this.saveMake();
    },
    aspectBlocked() {
      const v = this.curMake.video, aspect = v.aspect, methods = (this.presets && this.presets.generation_methods) || [];
      const ids = ['vox-fast-cut', 'vox-collage', 'hand-drawn', 'upload_image', 'upload_video', 'ai_image'];
      const blocked = [];
      if (v.theme === 'vox-collage' && aspect !== '16:9') blocked.push('VOX 纸拼贴主题');
      if (v.layout === 'fast-cut' && aspect !== '16:9') blocked.push('快切编排');
      const def = methods.find((m) => m.id === v.generation_method);
      if (def && !def.aspects.includes(aspect)) blocked.push(def.name);
      for (const o of v.beat_overrides || []) {
        const m = methods.find((x) => x.id === o.method);
        if (m && !m.aspects.includes(aspect)) blocked.push('第 ' + o.beat_id + ' 拍 · ' + m.name);
      }
      if (aspect !== '16:9' && ids.includes(v.generation_method)) blocked.push('当前默认生成方式');
      return [...new Set(blocked)];
    },
    beatOverride(b) { return this.curMake.video.beat_overrides.find((o) => o.beat_id === b.id) || { beat_id: b.id, method: 'inherit', kenburns: 'in', credit: '', start: 0, end: '' }; },
    setBeatOverride(b, key, value) {
      const list = this.curMake.video.beat_overrides; let o = list.find((o) => o.beat_id === b.id);
      if (!o) { o = { ...this.beatOverride(b) }; list.push(o); }
      if (key === 'method' && o.method !== value && (o.method === 'upload_video' || value === 'upload_video' || value === 'hand-drawn' || value === 'template' || value === 'inherit')) o.asset_id = '';
      if ((key === 'start' || key === 'end') && value === '') delete o[key]; else o[key] = value;
      this.saveMake();
    },
    beatAssets(b) {
      const wantVideo = this.beatOverride(b).method === 'upload_video';
      return (this.libAssets || []).filter((a) => wantVideo ? a.kind === 'video' : a.kind === 'image');
    },
    setBeatAsset(b, ev) {
      const v = ev.target.value;
      if (v === '__manage__') { ev.target.value = this.beatOverride(b).asset_id || ''; this.goMaterials(); return; }
      this.setBeatOverride(b, 'asset_id', v);
    },
    async uploadBeatAsset(b, ev) {
      const file = ev.target.files && ev.target.files[0], id = this.cur, method = this.beatOverride(b).method; ev.target.value = '';
      const key = id + ':' + b.id;
      if (!file || this.assetUploadBusy[key]) return;
      if (!this.validLibFile(file, method === 'upload_video' ? 'video' : 'image')) return;
      this.assetUploadBusy[key] = true;
      try {
        await this.flushMake(id);
        const q = new URLSearchParams({ name: file.name });
        const resp = await fetch('/wb-api/video-assets?' + q, { method: 'PUT', body: file });
        const d = await resp.json(); if (!resp.ok) throw d;
        if (this.cur === id) this.setBeatOverride(b, 'asset_id', d.asset.asset_id);
        else {
          // 上传期间切换制作，仍写回原制作的拍。
          const m = this.makes.find((m) => m.id === id);
          if (m) {
            let o = m.video.beat_overrides.find((o) => o.beat_id === b.id);
            if (!o) { o = { beat_id: b.id, method }; m.video.beat_overrides.push(o); }
            o.asset_id = d.asset.asset_id; this.saveMake(m);
          }
        }
        await this.flushMake(id);
        await this.loadLibAssets();
      } catch (e) { this.makeErr = this.makeError(e); }
      finally { this.assetUploadBusy[key] = false; }
    },
    async showMakeBuildLog() {
      this.buildLogOpen = !this.buildLogOpen; if (!this.buildLogOpen) return;
      if (!this.buildPid) { this.buildLogLines = ['(尚无日志：任务未启动)']; return; }
      try {
        const d = await WB.api.get('/video-builds/' + encodeURIComponent(this.buildPid) + '/log?n=200');
        this.buildLogLines = d.tail || []; this.buildLogTruncated = !!d.truncated;
      } catch (e) { this.buildLogLines = ['(日志读取失败: ' + this.makeError(e) + ')']; }
    },
    /* ── 产出可达：复制/导出/导入/打开文件夹 ── */
    downloadFile(name, content, mime) {
      const blob = new Blob([content], { type: mime });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = name;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    },
    async openMakeFolder(kind) {
      const body = { kind, make_id: this.cur, project_id: (this.curMake && this.curMake.project_id) || '', open: true };
      try {
        const d = await WB.api.post('/open-folder', body);
        if (kind === 'voice') this.voiceFolderPath = d.path || '';
        if (kind === 'project_out') this.outFolderPath = d.path || '';
        WB.toast('已在资源管理器打开');
      } catch (e) { WB.toast(this.makeError(e)); }
    },
    async copyFolderPath(kind) {
      const body = { kind, make_id: this.cur, project_id: (this.curMake && this.curMake.project_id) || '', open: false };
      try {
        const d = await WB.api.post('/open-folder', body);
        await WB.copyText(d.path || '');
      } catch (e) { WB.toast(this.makeError(e)); }
    },
    copyNarration() { WB.copyText((this.curMake && this.curMake.narration && this.curMake.narration.text) || ''); },
    exportNarrationTxt() {
      const t = (this.curMake && this.curMake.narration && this.curMake.narration.text) || '';
      if (!t.trim()) { WB.toast('口播稿为空'); return; }
      this.downloadFile((this.curMake.title || '口播稿') + '.txt', t, 'text/plain;charset=utf-8');
    },
    copyScriptText() {
      const beats = (this.curMake.script && this.curMake.script.beats) || [];
      WB.copyText(beats.map((b) => b.narration).join('\n\n'));
    },
    copyScriptJson() { WB.copyText(JSON.stringify(this.curMake.script, null, 2)); },
    exportScriptJson() {
      if (!this.curMake.script) { WB.toast('尚无脚本'); return; }
      this.downloadFile((this.curMake.title || '视频脚本') + '.json',
        JSON.stringify(this.curMake.script, null, 2), 'application/json');
    },
    importScriptJson(ev) {
      const f = ev.target.files && ev.target.files[0]; ev.target.value = '';
      if (!f) return;
      if (this.curMake.script_meta.locked) { WB.toast('脚本已定稿锁定，请先解锁脚本'); return; }
      const reader = new FileReader();
      reader.onload = () => {
        try {
          const d = JSON.parse(reader.result);
          if (!Array.isArray(d.beats) || !d.beats.length) { WB.toast('JSON 缺少 beats，无法导入'); return; }
          this.curMake.script = d;
          if (this.curMake.script_meta) this.curMake.script_meta.locked = false;
          this.saveMake(); WB.toast('脚本 JSON 已导入，请检查后重新定稿');
        } catch (e) { WB.toast('JSON 解析失败: ' + e.message); }
      };
      reader.readAsText(f, 'utf-8');
    },

  },
  async mounted() {
    this.registerSubs();
    await Promise.all([
      this.loadPool(), this.loadScripts(), this.loadStyles(), this.loadDrafts(),
      this.loadVideos(), this.loadMakePresets(), this.loadMakes(), this.loadLibAssets(), this.loadTemplates(),
    ]);
    this.loadChannels(); this.loadAnPaths(); this.loadAnHistory();
    this.ensureActiveMake();
    this.loadHot();
    try {                            // 已有采集在跑(如计划任务刚触发)则同步按钮态
      const st = await WB.api.get("/yt/status");
      if (st.running) { this.collecting = true; this.pollCollect(); }
    } catch (e) {}
    try {
      const jobs = await WB.api.get('/video-jobs');
      if (jobs.analyze && jobs.analyze.running) { this.anBusy = true; this.pollJob('analyze'); }
      for (const kind of ['generate', 'voice', 'build']) {
        if (jobs[kind] && jobs[kind].running) {
          this.adoptMakeJob(kind, jobs[kind]);
          if (!this.cur && (jobs[kind].request || {}).make_id) await this.selectMake(jobs[kind].request.make_id);
          this.pollJob(kind);
        }
      }
    } catch (e) {}
  },
  unmounted() {
    this.disposed = true;
    Object.keys(this.savePending).forEach((id) => { this.flushMake(id).catch(() => {}); });
    Object.values(this.saveTimers).forEach(clearTimeout);
    clearTimeout(this.collectPoll);
    Object.values(this.jobPolls).forEach(clearTimeout);
    try {                                     // 媒体元素随页卸载: 停播+卸 src, 防后台继续拉流
      this.$el.querySelectorAll("audio,video").forEach((m) => {
        try { m.pause(); m.removeAttribute("src"); m.load(); } catch (e) {}
      });
    } catch (e) {}
    if (WB.shell) WB.shell.setSubs([]);   // 离开视频页清空左菜单
  },
  template: `
  <div>
    <!-- 制作任务进度横栏: 页面最顶(导航栏下方 sticky), 任务运行时全页签可见 -->
    <div v-if="narBusy || storyBusy || voiceBusy || buildBusy"
         class="notice" style="position:sticky;top:56px;z-index:60;display:flex;gap:22px;align-items:center;padding:7px 16px;margin-bottom:10px">
      <div v-if="narBusy">口播稿生成中 · {{ narProgress && narProgress.message || '准备中…' }}</div>
      <div v-if="storyBusy">分镜生成中 · {{ storyProgress && storyProgress.message || '准备中…' }}</div>
      <div v-if="voiceBusy">语音生成中 · {{ voiceProgress && voiceProgress.message || '准备中…' }}</div>
      <div v-if="buildBusy">视频制作中 · {{ buildProgress && buildProgress.message || '准备中…' }}</div>
    </div>
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
            <th>#</th><th>标题</th><th>素材</th><th>频道</th><th>类型</th><th>发布</th><th>播放</th><th>赞</th><th>评</th>
            <th>内容简介</th><th>内容标签</th>
          </tr></thead>
          <tbody>
            <tr v-for="(r, i) in hotInsights" :key="r.video_id">
              <td class="mono muted">{{ i + 1 }}</td>
              <td style="max-width:200px"><a :href="r.url" target="_blank" rel="noopener"
                   :title="r.channel_title + ' · ' + r.title">{{ cut(r.title, 20) }}</a></td>
              <td><span v-if="poolIds[r.video_id]" class="act-done">已加入 ✓</span>
                <a v-else style="font-size:12px" @click.stop.prevent="addToPool(r)">＋加入素材池</a></td>
              <td class="muted">{{ r.channel_title }}</td>
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
            ? '该时间窗口内启用频道没有新发布视频 —— 数据已采集到 ' + (hotMeta.tracked || '—') + ' 条, 把时间范围切到「近 7 天/28 天」即可看到' : '添加并启用频道后, 这里是它们的热播榜' }}</div>
        <table v-else class="tbl">
          <thead><tr>
            <th>视频</th><th>素材</th><th>频道</th><th>类型</th><th>发布</th>
            <th>播放</th><th>Δ24h</th><th>Δ7d</th><th>日速</th><th>赞</th><th>评</th>
          </tr></thead>
          <tbody>
            <tr v-for="r in hotItems" :key="r.video_id" :class="{stale: r.cold}">
              <td style="max-width:220px">
                <a :href="r.url" target="_blank" rel="noopener"
                   :title="r.channel_title + ' · ' + r.title">{{ cut(r.title, 20) }}</a></td>
              <td><span v-if="poolIds[r.video_id]" class="act-done">已加入 ✓</span>
                <a v-else style="font-size:12px" @click.stop.prevent="addToPool(r)">＋加入素材池</a></td>
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
        <div v-show="tab==='analysis'" class="three-col analysis-cols">
<div class="card" style="align-self:start">
        <h3>素材池({{ pool.length }})</h3>
        <div v-if="!pool.length" class="empty">到【热点追踪】点「＋加入素材池」</div>
        <div v-for="item in pool" :key="item.id" class="list-item" :class="{sel:poolSel && poolSel.id===item.id}" @click="selectPool(item)">
          <div class="t"><span>{{ cut(item.title, 25) }}</span><span v-if="item.analysis_status==='ok' || item.analysis_status==='partial'" style="color:var(--green)">●</span><span v-if="(item.analysis_status==='ok'||item.analysis_status==='partial') && item.analysis_tier_used && item.analysis_tier_used!=='gemini'" class="badge yellow" style="font-size:10px;margin-left:4px" title="文本通道分析, 可「重新分析」升级为 Gemini 看片">文本版</span></div>
          <div class="s">{{ item.channel_title || '未知频道' }} · {{ fmtDur(item.duration_s) }}</div>
          <a style="font-size:12px" @click.stop.prevent="delPool(item)">移除</a>
        </div>
      </div>
      <div>
        <div class="card">
          <h3>分析对象
            <span class="radio-group" style="margin-left:10px">
              <label><input type="radio" value="url" v-model="anMode"> YouTube 链接</label>
              <label><input type="radio" value="file" v-model="anMode"> 本地文件</label>
            </span></h3>
          <template v-if="anMode==='file'">
            <div class="form-row"><label>路径</label>
              <select v-model.number="anPathIdx" @change="loadAnFiles" style="min-width:420px">
                <option v-for="p in anPaths" :key="p.idx" :value="p.idx">{{ p.label }}: {{ p.root }}</option>
              </select></div>
            <div class="form-row"><label>视频文件</label>
              <select v-model="anFile" style="min-width:420px">
                <option value="" disabled>{{ anFiles.length ? '选择视频文件(' + anFiles.length + ')' : '该路径下暂无视频文件' }}</option>
                <option v-for="f2 in anFiles" :key="f2.path" :value="f2.path">{{ f2.name }} ({{ fmtNum(f2.size) }} B)</option>
              </select>
              <button class="btn" :disabled="anLoadingFile" @click="loadAnFiles">{{ anLoadingFile ? '扫描中…' : '重新扫描' }}</button></div>
            <div class="form-row">
              <button class="btn primary" :disabled="anBusy || !anFile" @click="startAnalyzeLocal(false)">
                {{ anBusy ? '分析中…' + (anProgress && anProgress.message ? ' ' + anProgress.message : '') : '开始分析' }}</button>
              <button v-if="anFile" class="btn" :disabled="anBusy" @click="startAnalyzeLocal(true)">重新分析</button>
            </div>
            <p class="muted">本地文件先上传到 Gemini Files API(≤2GB), 转码完成后再看片分析, 大文件请耐心等待</p>
          </template>
          <template v-else>
            <div v-if="poolSel" style="margin-bottom:10px;display:flex;align-items:flex-start;gap:8px">
              <div style="flex:1;min-width:0">
                <strong>{{ poolSel.title }}</strong>
                <div class="muted">{{ poolSel.channel_title || '未知频道' }} · {{ fmtDur(poolSel.duration_s) }} · {{ fmtNum(poolSel.views) }} 播放</div>
              </div>
              <button class="btn" @click="clearPoolSel">退回</button>
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
            <div class="form-row" style="margin-top:4px"><label>工作流</label>
              <select v-model="anWorkflow" style="min-width:280px">
                <option value="gemini">Gemini 看片(画面语义, 需 Gemini Key)</option>
                <option value="copylab">copylab（文案框架+引用核验，走成稿模型）</option>
              </select>
              <span class="muted">copylab 需要字幕, 仅 YouTube; 引用逐条机器核对, 报告带通过率</span></div>
          </template>
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
      <div class="card">
        <h3>历史分析 <span class="badge blue" style="margin-left:6px">以往结果 · 点击载入</span>
          <button class="btn" style="float:right" :disabled="anHistoryLoading" @click="loadAnHistory">
            {{ anHistoryLoading ? '刷新中…' : '刷新' }}</button></h3>
        <div v-if="!anHistory.length" class="empty">还没有分析记录 —— 分析完成的结果都会归档在这里</div>
        <div v-for="h in anHistory" :key="h.key" class="list-item"
             :class="{sel: anRec && anRec.key === h.key}" @click="openAnalysis(h.key)">
          <template v-if="anRenaming === h.key">
            <div class="form-row" style="gap:6px" @click.stop>
              <input type="text" v-model="anRenameTitle" style="flex:1;min-width:120px" @keyup.enter="anSubmitRename(h)" @keyup.esc="anRenaming=''">
              <button class="btn primary" @click="anSubmitRename(h)">保存</button>
              <button class="btn" @click="anRenaming=''">取消</button>
            </div>
          </template>
          <template v-else>
            <div class="t">{{ cut(h.title, 22) }}
              <span style="display:inline-flex;gap:4px;float:right">
                <button class="btn" style="padding:1px 8px" title="重命名" @click.stop="anStartRename(h)">改名</button>
                <button class="btn" style="padding:1px 8px" title="删除" @click.stop="anDelete(h)">删除</button>
              </span>
              <span class="badge" :class="h.status==='ok' ? 'green' : h.status==='partial' ? 'yellow' : 'red'"
                    style="float:right;margin-right:6px">{{ h.status }}</span></div>
            <div class="s">{{ h.updated_at }} · {{ h.tier_used || '—' }}</div>
          </template>
        </div>
      </div>
    </div>

    <!-- ═══ 子页4: 脚本仓库 ═══ -->
    <div v-show="tab==='scripts'" class="two-col">
      <div class="card">
        <h3>脚本仓库({{ scripts.length }})</h3>
        <p class="muted">可复用资产库——成稿脚本与分析骨架种子；脚本生成已并入视频制作，生成请到【视频制作】。</p>
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
            <button class="btn primary" :disabled="makeBusy" @click="useScriptInMake(scriptSel)">用于制作</button>
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
            <p class="muted">这是分析骨架种子；新建制作时选 from-analysis 风格即可引用本骨架展开成稿</p>
          </template>
        </template>
      </div>
    </div>

    <!-- ═══ 子页5: 模板仓库 ═══ -->
    <div v-show="tab==='templates'">
      <p class="muted">模板来自渲染引擎注册表（主题/编排/生成方式）；收藏与「设为默认」只影响新建制作，不改动已有制作单。</p>
      <div class="form-row" style="flex-wrap:wrap;gap:8px">
        <button v-for="k in ['all','theme','layout','method']" :key="k" class="btn" :class="{primary:templateFilter===k}" @click="templateFilter=k">{{ {all:'全部',theme:'视觉主题',layout:'编排策略',method:'生成方式'}[k] }}</button>
        <input v-model="templateSearch" placeholder="搜索名称或说明" aria-label="搜索模板">
      </div>
      <div v-if="!templatesCards.length" class="card empty">暂无模板，请稍后刷新</div>
      <div v-else-if="!templatesFiltered.length" class="card empty">{{ templateSearch ? '没有匹配「'+templateSearch+'」的模板' : '该分类暂无模板' }}</div>
      <template v-for="kind in ['theme','layout','method']" :key="kind">
        <section v-if="groupCards(kind).length">
          <h3>{{ {theme:'视觉主题',layout:'编排策略',method:'生成方式'}[kind] }}</h3>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px">
            <div v-for="card in groupCards(kind)" :key="card.key" class="card" :style="isDefault(card.kind,card.id) ? 'border-color:var(--accent)' : ''">
              <h3 style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">{{ card.name }}
                <template v-if="card.kind==='theme'"><span v-for="(color,i) in card.swatch || []" :key="i" :style="{backgroundColor:color}" style="display:inline-block;width:14px;height:14px;border-radius:50%;border:1px solid var(--border)"></span></template>
                <span class="badge">{{ {theme:'主题',layout:'编排',method:'生成方式'}[card.kind] }}</span>
              </h3>
              <div style="display:flex;gap:6px;flex-wrap:wrap"><span v-for="aspect in ['16:9','9:16','1:1','4:5']" :key="aspect" class="badge" :class="{muted:!(card.aspects || []).includes(aspect)}" :style="!(card.aspects || []).includes(aspect) ? 'opacity:.4' : ''">{{ aspect }}</span></div>
              <p class="muted">{{ card.cost }}</p><p>{{ card.blurb }}</p>
              <div style="display:flex;gap:8px">
                <button class="btn" :class="isFav(card.key)?'fav-on':''" :style="isFav(card.key) ? 'color:var(--yellow,#d6a93b)' : ''" :aria-label="isFav(card.key)?'取消收藏':'收藏'" :aria-pressed="isFav(card.key)" :disabled="favBusy || styleBusy" @click="toggleFav(card)">{{ isFav(card.key) ? '★' : '☆' }}</button>
                <button class="btn" :class="{primary:isDefault(card.kind,card.id)}" :disabled="styleBusy || favBusy" @click="setDefault(card)">{{ isDefault(card.kind,card.id) ? '当前默认' : '设为默认' }}</button>
              </div>
            </div>
          </div>
        </section>
      </template>
    </div>

    <!-- ═══ 子页6: 素材仓库 ═══ -->
    <div v-if="tab==='materials'" class="two-col">
      <div class="card">
        <h3>素材仓库({{ libAssets.length }})
          <label class="btn" :aria-disabled="libUpBusy">{{ libUpBusy ? '上传中…' : '上传素材' }}<input type="file" multiple style="display:none" accept=".png,.jpg,.jpeg,.webp,.mp4,.webm,.mp3,.wav,.m4a" :disabled="libUpBusy" @change="uploadLibAssets($event)"></label>
        </h3>
        <div class="form-row" style="flex-wrap:wrap;gap:8px">
          <button v-for="k in ['all','image','video','audio']" :key="k" class="btn" :class="{primary:libFilter===k}" @click="libFilter=k">{{ k==='all' ? '全部' : libKindName(k) }}</button>
          <input v-model="libSearch" placeholder="搜索素材名称" aria-label="搜索素材">
        </div>
        <div v-if="!libAssets.length" class="empty">还没有素材 —— 上传或从制作页上传会进入这里</div>
        <div v-else-if="!libFiltered.length" class="empty">没有匹配的素材</div>
        <div v-for="a in libFiltered" :key="a.asset_id" class="list-item" :class="{sel:previewAsset && previewAsset.asset_id===a.asset_id}">
          <div style="display:flex;gap:10px;align-items:center">
            <div style="width:64px;height:48px;flex-shrink:0;display:flex;align-items:center;justify-content:center;overflow:hidden">
              <img v-if="a.kind==='image'" :src="assetFileUrl(a)" :alt="a.name" loading="lazy" style="width:100%;height:100%;object-fit:cover">
              <video v-else-if="a.kind==='video'" :src="assetFileUrl(a)" preload="none" muted style="width:100%;height:100%;object-fit:cover"></video>
              <span v-else style="font-size:28px" aria-label="音频">🎧</span>
            </div>
            <div style="min-width:0;flex:1">
              <div class="t"><span :title="a.name">{{ cut(a.name,18) }}</span> <span class="badge">{{ libKindName(a.kind) }}</span>
                <span v-if="(a.refs || []).length" :title="libRefsTitle(a)" style="color:var(--yellow,#d6a93b)">● {{ a.refs.length }}</span></div>
              <div class="s muted">{{ fmtSize(a.size) }} · {{ a.created_at }}</div>
            </div>
          </div>
          <div class="form-row" style="gap:6px;margin:8px 0 0">
            <button class="btn" @click="openPreview(a)">预览</button>
            <button class="btn" @click="openPreview(a);startRenameAsset(a)">重命名</button>
            <button class="btn" @click="deleteAsset(a)">删除</button>
          </div>
        </div>
      </div>
      <div v-if="previewAsset" class="card">
        <h3>素材预览 <button class="btn" @click="closePreview">关闭</button></h3>
        <img v-if="previewAsset.kind==='image'" :src="assetFileUrl(previewAsset)" :alt="previewAsset.name" style="max-width:100%;max-height:420px;object-fit:contain">
        <video v-else-if="previewAsset.kind==='video'" :key="previewAsset.asset_id" :src="assetFileUrl(previewAsset)" controls preload="metadata" style="width:100%;max-height:420px"></video>
        <audio v-else-if="previewAsset.kind==='audio'" :key="previewAsset.asset_id" :src="assetFileUrl(previewAsset)" controls preload="metadata" style="width:100%"></audio>
        <h3 style="overflow-wrap:anywhere">{{ previewAsset.name }}</h3>
        <p class="muted">{{ libKindName(previewAsset.kind) }} · {{ fmtSize(previewAsset.size) }}<span v-if="previewAsset.duration_s!=null"> · 时长 {{ fmtDur(previewAsset.duration_s) }}</span></p>
        <p class="muted">上传时间：{{ previewAsset.created_at }}</p>
        <p v-if="libRefsTitle(previewAsset)" style="overflow-wrap:anywhere">{{ libRefsTitle(previewAsset) }}</p>
        <div v-if="renamingAsset===previewAsset.asset_id" class="form-row" style="gap:6px;flex-wrap:wrap">
          <input v-model="renamingAssetName" placeholder="新名称" aria-label="素材新名称" @keyup.enter="saveRenameAsset(previewAsset)" @keyup.esc="renamingAsset=null" style="min-width:0;flex:1">
          <button class="btn primary" @click="saveRenameAsset(previewAsset)">存</button>
          <button class="btn" @click="renamingAsset=null">取消</button>
        </div>
        <button v-else class="btn" @click="startRenameAsset(previewAsset)">重命名</button>
        <button class="btn" @click="deleteAsset(previewAsset)">删除</button>
      </div>
      <div v-else class="card empty">从左侧选择素材预览</div>
    </div>

    <!-- 四段视频制作 -->
    <div v-show="tab==='make'">
      <div v-if="makeErr || error" class="err-box" style="padding:12px">{{ makeErr || makeError(error) }}
        <button class="btn" @click="cur && flushMake(cur).catch(()=>{})">重试保存</button></div>
      <div class="two-col make-cols">
        <div style="min-width:0">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px" role="radiogroup" aria-label="制作路线">
            <div class="route-card" role="button" tabindex="0" :class="{sel: makeRoute==='script'}"
                 :style="{border: makeRoute==='script' ? '2px solid var(--accent)' : '1px solid var(--border)', background: makeRoute==='script' ? 'var(--accent-weak)' : ''}"
                 style="border-radius:10px;padding:12px 14px;cursor:pointer"
                 @click="makeRoute='script'" @keydown.enter="makeRoute='script'">
              <div style="display:flex;align-items:center;gap:8px;font-weight:600">✍️ 文案路线</div>
            </div>
            <div class="route-card" role="button" tabindex="0" :class="{sel: makeRoute==='audio'}"
                 :style="{border: makeRoute==='audio' ? '2px solid var(--accent)' : '1px solid var(--border)', background: makeRoute==='audio' ? 'var(--accent-weak)' : ''}"
                 style="border-radius:10px;padding:12px 14px;cursor:pointer"
                 @click="makeRoute='audio'" @keydown.enter="makeRoute='audio'">
              <div style="display:flex;align-items:center;gap:8px;font-weight:600">🎙️ 音频路线 <span class="badge yellow" style="font-size:10px">建设中</span></div>
            </div>
          </div>
          <div v-if="makeRoute==='audio'" class="card" style="padding:48px 24px;text-align:center">
            <div style="font-size:40px">🎙️</div>
            <h3>音频路线 · 建设中</h3>
            <p class="muted" style="margin:10px 0 4px"><b>上传音频 + 提取文案 → 视频脚本 → 视频生成</b></p>
            <p class="muted">从已成片的音频出发：上传配音/播客音频，自动转写提取文案，
              校对后进入脚本分镜与出片流程（跳过 TTS 配音环节）。该路线正在开发中。</p>
          </div>
          <div v-else-if="!curMake" class="card empty">正在准备制作单…</div>
          <template v-else>
            <div class="make-wrap">
              <aside class="make-step-nav" aria-label="制作步骤">
                <button v-for="s in makeSteps" :key="s.n" type="button" class="step-item" :class="{sel: makeStep===s.n}"
                        @click="makeStep=s.n">
                  <span class="lbl"><span class="num">{{ s.n }}</span>{{ s.label }}</span>
                  <span class="st" :style="{color: ({green:'var(--green)', yellow:'var(--yellow)', blue:'var(--accent)'})[s.badge.cls] || 'var(--text-mute)'}">{{ s.badge.text }}</span>
                </button>
              </aside>
            <div class="make-stage">
              <div class="make-step-main">
            <div class="card" v-show="makeStep===1">
              <h3>项目名称</h3>
              <div class="form-row">
                <input type="text" v-model="curMake.title" @input="saveMake()" :disabled="makeBusy" placeholder="给这条片子起个名字" style="flex:1;min-width:0;font-weight:600">
                <span class="muted" style="white-space:nowrap">{{ {pending:'2 秒后自动保存',saving:'保存中…',saved:('已保存 ' + (savedAt[cur] || '')),error:'保存失败'}[saveState[cur]] || '' }}</span></div>
            </div>
            <div class="card" v-show="makeStep===2">
              <h3>口播稿生成 <span class="badge" :class="segBadge(1).cls">{{ segBadge(1).text }}</span></h3>
              <fieldset :disabled="makeBusy" style="border:0;min-width:0;padding:0">
                <template v-if="!curMake.narration.locked">
                  <div class="form-row radio-group">
                    <label><input type="radio" value="b" v-model="narTab">直接输入</label>
                    <label><input type="radio" value="a" v-model="narTab">智能生成</label></div>
                  <template v-if="narTab==='a'">
                    <textarea v-model="curMake.narration.ref_text" @input="saveMake()" rows="5" style="width:100%" placeholder="粘贴参考文（长文直接粘，≤20000 字）"></textarea>
                    <div class="form-row"><label>一句话简报</label><input type="text" v-model="narBrief" placeholder="这期视频讲什么（可空）" style="flex:1;min-width:0"></div>
                    <div class="form-row"><label>片长</label>
                      <select v-model="curMake.narration.length_s" @change="saveMake()">
                        <option :value="0">不限 · 由材料定（默认，质量优先）</option>
                        <option v-for="t in lengthTiers" :key="t" :value="t">约 {{ t }} 秒</option></select>
                      <span class="muted" style="font-size:11px">默认不限长，要发限时平台才选档</span></div>
                    <div class="form-row" v-if="llmOptions.length"><label>生成模型</label>
                      <select v-model="curMake.narration.llm_source" @change="saveMake()">
                        <option v-for="o in llmOptions" :key="o.id" :value="o.id">{{ o.default ? '默认 · ' : '' }}{{ o.label }}{{ o.engine === 'grok-cli' ? ' · grok CLI' : '' }}</option></select>
                      <span class="muted" style="font-size:11px">成稿模型链 · 选中位失败自动落下一</span></div>
                    <div class="form-row"><label>改写幅度</label><span class="radio-group">
                      <label><input type="radio" value="faithful" v-model="curMake.narration.fidelity" @change="saveMake()">忠于原文</label>
                      <label><input type="radio" value="rewrite" v-model="curMake.narration.fidelity" @change="saveMake()">重写成片</label></span></div>
                    <details style="margin:6px 0 8px"><summary class="muted" style="cursor:pointer;font-size:12px">高级：结构变体（一般不用动）</summary>
                      <div class="form-row" style="margin-top:6px"><label>结构</label><select v-model="curMake.narration.style_id" @change="saveMake()" style="max-width:100%">
                        <option v-for="s in styles" :key="s.id" :value="s.id">{{ s.name }}{{ s.default ? '（默认）' : '' }}</option></select></div>
                    </details>
                    <button class="btn primary" :disabled="narBusy || storyBusy || !(narBrief.trim() || curMake.narration.ref_text.trim())" @click="runMakeJob('narration')">{{ narBusy ? '生成中…' : '生成口播稿' }}</button>
                  </template>
                </template>
                <div class="muted" style="margin:10px 0 4px">正文</div>
                <textarea v-model="curMake.narration.text" @input="narrationInput" :readonly="curMake.narration.locked" rows="10" style="width:100%" placeholder="在这里输入或修改口播稿"></textarea>
                <p class="muted">{{ narrationWords }} 字 · 预估 {{ Math.round(narrationWords / 4.2) }} 秒
                  <button class="btn" style="margin-left:8px" @click="copyNarration">复制</button>
                  <button class="btn" @click="exportNarrationTxt">导出 TXT</button></p>
                <div v-if="curMake.narration.locked" style="margin-top:10px">
                  <p class="muted mono">已定稿 hash {{ curMake.narration.hash }} · {{ curMake.narration.locked_at }}</p>
                  <button class="btn" @click="makeLock('narration', true)">解锁改稿</button></div>
                <button v-else class="btn primary" :disabled="narrationWords < 40" @click="makeLock('narration')">定稿</button>
              </fieldset>
              <div v-if="narErr" class="err-box" style="padding:12px">{{ narErr }}</div>
            </div>
            <div class="card" v-show="makeStep===3">
              <h3>脚本生成 <span class="badge" :class="segBadge(2).cls">{{ segBadge(2).text }}</span></h3>
              <div v-if="!curMake.narration.locked" class="stub-wrap" style="padding:30px;text-align:center;background:var(--bg-hover);color:var(--text-mute)">先定稿口播稿</div>
              <template v-else>
                <div v-if="curMake.script_stale" class="notice">口播稿已重定稿，脚本与口播不一致——重新生成或手动对齐后再定稿</div>
                <div class="form-row" v-if="curMake.script" style="margin-bottom:10px">
                  <button class="btn" @click="copyNarration">复制口播全文</button>
                  <button class="btn" @click="copyScriptJson">复制脚本 JSON</button>
                  <button class="btn" @click="exportScriptJson">导出 JSON</button>
                  <button class="btn" @click="exportNarrationTxt">导出口播 TXT</button>
                  <label class="btn">导入 JSON<input type="file" accept=".json" style="display:none" @change="importScriptJson"></label>
                  <span class="muted">可导出修改后再导入；导入仅改副字段与节拍，口播仍以口播稿定稿为准</span></div>
                <fieldset :disabled="makeBusy" style="border:0;min-width:0;padding:0">
                  <div v-if="!curMake.script_meta.locked" class="form-row">
                    <button class="btn primary" :disabled="narBusy || storyBusy" @click="runMakeJob('storyboard')">{{ storyBusy ? '分镜生成中…' : curMake.script ? '重新生成分镜脚本' : 'AI 生成分镜脚本' }}</button>
                    <select v-model="importId" @change="importMakeScript" style="max-width:100%"><option value="">从脚本仓库导入</option>
                      <option v-for="r in importScripts" :key="r.id" :value="r.id">{{ r.title }}</option></select></div>
                  <div v-if="storyBusy" class="muted">{{ storyProgress && storyProgress.message || '准备中…' }}</div>
                  <template v-if="curMake.script">
                    <p v-if="curMake.script.disclaimer" class="notice">免责声明：{{ curMake.script.disclaimer }}</p>
                    <fieldset :disabled="curMake.script_meta.locked" style="border:0;min-width:0;padding:0">
                      <div class="form-row"><label>脚本标题</label><input type="text" v-model="curMake.script.title" @input="curMake.title=curMake.script.title;saveMake()" style="flex:1;min-width:0"></div>
                      <div class="muted">开场 Hook 变体</div>
                      <label v-for="(h,i) in ((curMake.script.hook || {}).variants || []).slice(0,3)" :key="i" class="list-item" style="display:block">
                        <input type="radio" :value="i" v-model="curMake.video.hook_index" @change="saveMake()"> {{ h.text || h }}</label>
                      <p class="muted">口播只读，点击文字定位光标后可拆分；删除后的口播一致性在定稿时校验。</p>
                      <div style="overflow-x:auto"><table class="tbl"><thead><tr><th>拍 / role</th><th>口播（只读）</th><th>字幕 / 屏幕要点 / 画面</th><th>操作</th></tr></thead>
                        <tbody><tr v-for="(b,i) in makeBeats" :key="b.id">
                          <td>{{ i+1 }} · {{ b.id }}<select v-model="b.role" @change="saveMake()" style="width:90px"><option v-for="r in ['hook','setup','move','gives','payoff','cta']" :key="r">{{ r }}</option></select></td>
                          <td><textarea :value="b.narration" readonly rows="4" style="width:100%;min-width:130px" @click="beatCursors[b.id]=$event.target.selectionStart" @keyup="beatCursors[b.id]=$event.target.selectionStart" @select="beatCursors[b.id]=$event.target.selectionStart"></textarea></td>
                          <td><input type="text" v-model="b.subtitle" @input="saveMake()" placeholder="字幕" style="width:100%;min-width:130px">
                            <input type="text" :value="(b.on_screen || []).join('、')" @input="changeBeatScreen(b,$event)" placeholder="屏幕要点（顿号分隔）" style="width:100%">
                            <input type="text" v-model="b.visual_hint" @input="saveMake()" placeholder="画面建议" style="width:100%"></td>
                          <td><button class="btn" @click="splitMakeBeat(i)">拆分</button><button class="btn" :disabled="i===makeBeats.length-1" @click="mergeMakeBeat(i)">合并↓</button><button class="btn" @click="removeMakeBeat(i)">删除</button></td>
                        </tr></tbody></table></div>
                    </fieldset>
                    <div v-if="curMake.script.warnings && curMake.script.warnings.length" class="notice"><div v-for="(w,i) in curMake.script.warnings" :key="i">{{ w }}</div></div>
                    <div v-if="makeClaims.total" style="margin-top:10px">
                      <div class="form-row" style="align-items:center;gap:6px">
                        <span class="muted">事实账本 {{ makeClaims.total }} 条：</span>
                        <span class="badge green">已核验 {{ makeClaims.levels.verified }}</span>
                        <span class="badge blue">观点 {{ makeClaims.levels.opinion }}</span>
                        <span class="badge yellow">待确认 {{ makeClaims.levels.pending }}</span>
                        <span class="badge red">高危 {{ makeClaims.levels.high_risk }}</span>
                        <button class="btn" @click="claimsOpen=!claimsOpen">{{ claimsOpen ? '收起明细' : '展开明细' }}</button></div>
                      <table v-if="claimsOpen" class="tbl" style="margin-top:6px"><thead><tr><th>分级</th><th>原文引句</th><th>来源</th><th>建议核实方式</th></tr></thead>
                        <tbody><tr v-for="(c,i) in makeClaims.items" :key="i">
                          <td><span class="badge" :class="{'green':c.level==='verified','blue':c.level==='opinion','yellow':c.level==='pending','red':c.level==='high_risk'}">{{ {verified:'已核验',opinion:'观点',pending:'待确认',high_risk:'高危'}[c.level] }}</span></td>
                          <td style="max-width:280px">{{ c.text }}</td>
                          <td style="max-width:140px">{{ c.source || '—' }}</td>
                          <td style="max-width:200px">{{ c.suggestion || '—' }}</td>
                        </tr></tbody></table></div>
                    <div v-if="curMake.script_meta.locked" style="margin-top:10px"><p class="muted mono">已定稿 hash {{ curMake.script_meta.hash }} · {{ curMake.script_meta.locked_at }}</p>
                      <button class="btn" @click="makeLock('script',true)">解锁</button></div>
                    <button v-else class="btn primary" style="margin-top:10px" @click="makeLock('script')">定稿脚本</button>
                  </template>
                </fieldset>
              </template>
              <div v-if="scriptErr" class="err-box" style="padding:12px">{{ scriptErr }}</div>
            </div>
            <div class="card" v-show="makeStep===4">
              <h3>音频生成 <span class="badge" :class="segBadge(3).cls">{{ segBadge(3).text }}</span></h3>
              <div v-if="!curMake.script_meta.locked" class="stub-wrap" style="padding:30px;text-align:center;background:var(--bg-hover);color:var(--text-mute)">先定稿视频脚本</div>
              <template v-else>
                <div v-if="curMake.voice_bad.length" class="notice">{{ curMake.voice_bad.length }} 拍语音与最新脚本不一致，需重生成（{{ curMake.voice_bad.map(id => {const i=makeBeats.findIndex(b=>b.id===id);return i>=0 ? '第 '+(i+1)+' 拍 ('+id+')' : id;}).join('、') }}）</div>
                <fieldset :disabled="makeBusy" style="border:0;min-width:0;padding:0">
                  <div class="form-row"><label>供应商</label><select v-model="curMake.voice.profile_id" @change="changeMakeProvider"><option value="" disabled>请选择</option>
                    <option v-for="p in ttsProviders" :key="p.id" :value="p.id">{{ p.name }} · {{ p.engine }}</option></select></div>
                  <div class="form-row"><label>音色</label><select v-model="curMake.voice.voice" @change="changeMakeVoice"><option value="" disabled>请选择音色</option>
                    <option v-for="v in makeVoices" :key="v.id" :value="v.id">{{ v.name }}</option></select>
                    <button class="btn" :disabled="voiceTesting || !curMake.voice.profile_id || !curMake.voice.voice" @click="testVoiceListen">
                      {{ voiceTesting ? '合成中…' : '试听' }}</button></div>
                  <div v-if="voiceTestUrl" style="margin:6px 0">
                    <audio controls :src="voiceTestUrl" style="max-width:100%;height:36px"></audio>
                    <p class="muted" style="font-size:11px">试听文本: 「{{ voiceTestPhrase }}」</p></div>
                  <p class="muted">换音色=全新合成；旧音色文件保留，切回即复用</p>
                  <p v-if="!ttsProviders.length" class="notice">请到 <a href="#/settings">设置 → 语音合成</a> 启用供应商和音色</p>
                  <button class="btn primary" :disabled="voiceBusy || !makeVoices.some(v=>v.id===curMake.voice.voice) || curMake.script_stale" @click="runMakeJob('voice')">{{ voiceBusy ? '生成中…' : '生成语音稿' }}</button>
                  <div class="form-row" v-if="curMake.voice.voice_key" style="margin-top:8px;align-items:center">
                    <button class="btn" @click="openMakeFolder('voice')">打开语音文件夹</button>
                    <button class="btn" @click="copyFolderPath('voice')">复制路径</button>
                    <span class="muted" style="font-size:11px">可直接复制 mp3 使用</span></div>
                </fieldset>
                <p v-if="voiceBusy" class="muted">{{ voiceProgress && voiceProgress.message || '准备中…' }}</p>
                <div v-for="(b,i) in makeBeats" :key="b.id" style="padding:8px 0;border-bottom:1px solid var(--border)" :style="curMake.voice_bad.includes(b.id) ? {background:'color-mix(in oklch,var(--yellow) 12%,transparent)'} : {}">
                  <div>{{ i+1 }} · {{ cut(b.narration,20) }} <span class="muted">{{ curMake.voice.items[b.id] ? curMake.voice.items[b.id].duration_s + ' 秒' : '待合成' }}</span></div>
                  <div class="form-row" style="margin:4px 0"><audio v-if="curMake.voice.items[b.id] && curMake.voice.voice_key" controls preload="none" :src="voiceUrl(b)" style="max-width:100%;height:34px"></audio>
                    <button class="btn" :disabled="makeBusy || voiceBusy || curMake.script_stale || !makeVoices.some(v=>v.id===curMake.voice.voice)" @click="runMakeJob('voice',b.id)">重生成</button></div>
                </div>
              </template>
              <div v-if="voiceErr" class="err-box" style="padding:12px">{{ voiceErr }}</div>
            </div>
            <div class="card" v-show="makeStep===5">
              <h3>视频生成 <span class="badge" :class="segBadge(4).cls">{{ segBadge(4).text }}</span></h3>
              <p v-if="!makeVoiceReady" class="notice">语音尚未就绪，可先定稿脚本并制作无声预览</p>
              <fieldset :disabled="makeBusy" style="border:0;min-width:0;padding:0">
                <div class="form-row"><label>语音稿</label><select disabled style="max-width:100%"><option>{{ curMake.voice.voice_key || '尚无语音稿' }}</option></select></div>
                <div class="form-row"><label>画幅</label><select v-model="curMake.video.aspect" @change="changeMakeAspect"><option v-for="a in (presets && presets.aspects) || []" :key="a.id" :value="a.id">{{ a.label }} {{ a.dims.join('×') }}</option></select></div>
                <div class="form-row"><label>视觉风格</label>
                  <select v-model="curStylePresetId" style="max-width:100%">
                    <option v-for="p in stylePresetList" :key="p.id" :value="p.id" :disabled="!p.aspects.includes(curMake.video.aspect)">{{ p.name }}{{ !p.aspects.includes(curMake.video.aspect) ? '（仅 16:9）' : '' }}{{ p.cost_type==='billed' ? ' · 生图计费' : '' }}</option>
                    <option v-if="curStylePresetId==='custom'" value="custom">{{ customStyleLabel }}</option>
                  </select>
                  <span v-if="makeTheme" style="display:inline-flex;gap:5px"><span v-for="(color,i) in makeTheme.swatch" :key="i" :style="{backgroundColor:color}" style="display:inline-block;width:14px;height:14px;border-radius:50%;border:1px solid var(--border)"></span></span></div>
                <div class="form-row" v-if="curStylePreset"><label></label>
                  <span class="muted" style="display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px;min-width:0">
                    {{ curStylePreset.desc }}<span class="badge" :class="curStylePreset.cost_type==='billed' ? 'yellow' : 'green'">{{ curStylePreset.cost_label }}</span>
                    <span v-if="curStylePreset.cost_type==='billed' && curMake.video.image_budget > 0">本次上限 {{ curMake.video.image_budget }} 张（高级可改）</span>
                    <span v-if="beatOverrideCount">逐拍覆盖 {{ beatOverrideCount }} 拍优先于全片风格</span>
                  </span></div>
                <div v-if="aspectBlocked().length" class="notice">当前画幅不支持：{{ aspectBlocked().join('、') }}。请改选支持当前画幅的风格或切回 16:9；不会静默忽略，制作时会直接报错。</div>
                <details style="margin:6px 0">
                  <summary class="muted" style="cursor:pointer;font-size:12px">高级设置（主题 / 编排 / 生成方式 / 帧率 / 逐拍覆盖…）</summary>
                  <div style="padding:8px 0 0">
                <div class="form-row"><label>帧率</label><div class="radio-group"><label v-for="fps in [30,60]" :key="fps"><input type="radio" :value="fps" v-model="curMake.video.fps" @change="saveMake()">{{ fps }} fps</label></div></div>
                <div class="form-row"><label>制作方式</label><div class="radio-group">
                  <label><input type="radio" value="unified" v-model="curMake.video.mode" @change="saveMake()">统一生成</label>
                  <label><input type="radio" value="edit" v-model="curMake.video.mode" @change="saveMake()" :disabled="curMake.video.aspect!=='16:9'">编辑生成</label></div>
                  <span v-if="curMake.video.aspect!=='16:9'" class="muted">编辑生成仅支持 16:9</span></div>
                  <div class="form-row"><label>视觉主题</label><select v-model="curMake.video.theme" @change="saveMake()"><option v-for="t in (presets && presets.themes) || []" :key="t.id" :value="t.id" :disabled="t.aspect_limit && t.aspect_limit!==curMake.video.aspect">{{ t.name }}{{ t.aspect_limit && t.aspect_limit!==curMake.video.aspect ? '（仅 '+t.aspect_limit+'）' : '' }}</option></select></div>
                  <div class="form-row"><label>编排策略</label><select v-model="curMake.video.layout" @change="saveMake()"><option v-for="l in (presets && presets.layouts) || []" :key="l.id" :value="l.id" :disabled="l.id==='fast-cut' && curMake.video.aspect!=='16:9'">{{ l.name }}{{ l.id==='fast-cut' && curMake.video.aspect!=='16:9' ? '（仅 16:9）' : '' }}</option></select></div>
                  <div class="form-row"><label>画面编排</label><div class="radio-group"><label><input type="radio" value="llm" v-model="curMake.video.enrich" @change="saveMake()" :disabled="!presets || !presets.llm_ready">AI 编排</label>
                    <label><input type="radio" value="plain" v-model="curMake.video.enrich" @change="saveMake()">简洁</label></div>
                    <span v-if="!presets || !presets.llm_ready" class="muted">AI 编排需先在设置页配置翻译模型</span></div>
                  <div class="form-row"><label>默认生成方式</label><select v-model="curMake.video.generation_method" @change="saveMake()"><option value="inherit">按主题 / 编排</option><option v-for="m in ((presets && presets.generation_methods) || []).filter(x => ['template','vox-fast-cut','vox-collage','hand-drawn'].includes(x.id))" :key="m.id" :value="m.id" :disabled="!m.aspects.includes(curMake.video.aspect)">{{ m.name }}{{ !m.aspects.includes(curMake.video.aspect) ? "（不支持此画幅）" : "" }}</option></select>
                    <span class="muted" style="font-size:11px">手改任一项，上方风格即显示为「自定义」</span></div>
                  <div class="form-row"><label>本次生图上限</label><input type="number" min="0" max="100" v-model.number="curMake.video.image_budget" @change="saveMake()" placeholder="默认 8 张；0 禁止新生图"></div>
                  <div class="notice" style="font-size:11px">逐拍选择优先于全片主题。VOX 快切 / 纸拼贴保留完整图片，约每 3–6 秒切换构图；每父拍最多一张新图，重复提示词复用缓存。手绘跟随使用本地 SVG，箭头仅表示原文顺序。字幕无真实对齐轨时按音频时长估算，不重合成已选语音。生图按供应商计费，耗时取决于缓存、音频与帧率。</div>
                  </div>
                </details>
                <div v-if="curMake.video.mode==='edit'" style="overflow-x:auto"><table class="tbl"><thead><tr><th>拍</th><th>生成方法</th><th>素材 / 参数</th></tr></thead><tbody>
                  <tr v-for="(b,i) in makeBeats" :key="b.id"><td>{{ i+1 }} · {{ b.id }}</td>
                    <td><select :value="beatOverride(b).method" @change="setBeatOverride(b,'method',$event.target.value)">
                      <option v-for="m in (presets && presets.generation_methods) || []" :key="m.id" :value="m.id" :disabled="!m.aspects.includes(curMake.video.aspect)">{{ m.name }}{{ !m.aspects.includes(curMake.video.aspect) ? "（不支持此画幅）" : "" }}</option></select></td>
                    <td>
                      <template v-if="beatOverride(b).method.startsWith('upload_') || beatOverride(b).method==='vox-fast-cut' || beatOverride(b).method==='vox-collage'">
                        <select :value="beatOverride(b).asset_id || ''" @change="setBeatAsset(b,$event)" style="max-width:220px"><option value="">选择该拍素材</option><option v-for="a in beatAssets(b)" :key="a.asset_id" :value="a.asset_id">{{ a.name }} · {{ fmtSize(a.size) }}</option><option value="__manage__">从素材仓库管理 →</option></select>
                        <label class="btn">{{ assetUploadBusy[cur+':'+b.id] ? '上传中…' : '上传' }}<input type="file" style="display:none" :accept="beatOverride(b).method==='upload_video' ? '.mp4,.webm' : '.png,.jpg,.jpeg,.webp'" @change="uploadBeatAsset(b,$event)"></label>
                      </template>
                      <input v-if="beatOverride(b).method==='ai_image'" type="text" :value="beatOverride(b).prompt || ''" @input="setBeatOverride(b,'prompt',$event.target.value)" :placeholder="(b.visual_hint || '')+' · 纸质拼贴、剪报纹理、档案风格，无文字'" style="width:100%;min-width:180px">
                      <details style="margin-top:8px"><summary>每拍参数</summary>
                        <div class="form-row"><label>镜头运动</label><select :value="beatOverride(b).kenburns || 'in'" @change="setBeatOverride(b,'kenburns',$event.target.value)"><option value="in">推近</option><option value="out">拉远</option><option value="left">向左</option><option value="right">向右</option></select></div>
                        <div class="form-row"><label>署名</label><input type="text" :value="beatOverride(b).credit || ''" @input="setBeatOverride(b,'credit',$event.target.value)" style="width:160px"></div>
                        <div class="form-row"><label>起止（秒）</label><input type="number" min="0" step="0.1" :value="beatOverride(b).start" @input="setBeatOverride(b,'start',$event.target.value==='' ? '' : Number($event.target.value))" style="width:75px" aria-label="开始秒数">—<input type="number" min="0" step="0.1" :value="beatOverride(b).end" @input="setBeatOverride(b,'end',$event.target.value==='' ? '' : Number($event.target.value))" style="width:75px" aria-label="结束秒数"></div>
                      </details>
                    </td></tr></tbody></table></div>
                <div class="form-row" style="margin-top:12px"><label>出片模式</label><div class="radio-group"><label><input type="radio" value="build" v-model="buildMode">正式成片</label><label><input type="radio" value="sample" v-model="buildMode">带音样片20s</label><label><input type="radio" value="keyframes" v-model="buildMode">静帧预览</label><label><input type="radio" value="estimate" v-model="buildMode">无声预览</label></div></div>
                <button class="btn primary" :disabled="buildBusy || !curMake.script_meta.locked || curMake.script_stale || (buildMode!=='estimate' && !makeVoiceReady)" @click="runMakeJob('build')">开始制作</button>
              </fieldset>
              <div v-if="buildBusy || curMake.status==='rendering'" style="margin-top:12px">
                <div style="display:flex;justify-content:space-between"><span>{{ buildProgress && buildProgress.message || '正在恢复制作进度…' }}</span><span>{{ buildProgress && buildProgress.pct || 0 }}%</span></div>
                <span class="bar-track"><span class="bar-fill" :style="{width:Math.max(0,Math.min(100,Number(buildProgress && buildProgress.pct)||0))+'%'}"></span></span>
                <p class="muted">{{ buildPid }} · {{ buildProgress && buildProgress.stage || 'queued' }}</p></div>
              <div v-if="buildErr" class="err-box" style="padding:12px">{{ buildErr }}<div>
                <button class="btn" @click="showMakeBuildLog">{{ buildLogOpen ? '收起日志' : '查看日志' }}</button>
                <button class="btn primary" :disabled="makeBusy || buildBusy || !curMake.script_meta.locked || curMake.script_stale || (buildMode!=='estimate' && !makeVoiceReady)" @click="runMakeJob('build')">重试</button></div></div>
              <div v-if="buildLogOpen" style="max-height:260px;overflow:auto;margin-top:8px"><p v-if="buildLogTruncated" class="muted">仅显示末尾 {{ buildLogLines.length }} 行</p><pre class="mono" style="white-space:pre-wrap">{{ buildLogLines.join('\\n') }}</pre></div>
            </div>
            <div class="card" v-if="curMake.project_id" v-show="makeStep===5">
              <h3>本项目产出
                <span class="muted" style="margin-left:10px;font-weight:400" v-if="makeProject && makeProject.built_at">成片于 {{ makeProject.built_at.slice(0,19).replace('T',' ') }}</span></h3>
              <template v-if="makeProject">
                <video v-if="makeOutUrl" :key="makeOutUrl" :src="makeOutUrl" controls preload="metadata" style="max-width:100%;max-height:460px;border-radius:8px"></video>
                <div class="form-row" style="margin-top:10px;align-items:center">
                  <button class="btn" @click="openMakeFolder('project_out')">打开成片文件夹</button>
                  <button class="btn" @click="copyFolderPath('project_out')">复制路径</button>
                  <a class="btn" v-if="makeProject.has_review" :href="'/wb-api/videos/'+encodeURIComponent(curMake.project_id)+'/file/'+encodeURIComponent('发布前核对.md')" download="发布前核对.md">发布前核对</a>
                  <span class="muted" style="font-size:11px">含 final.mp4 / 封面 / 字幕 SRT</span></div>
                <p class="muted" style="margin-top:6px">该成片同时会出现在「视频项目」列表。</p>
                <div style="margin-top:10px;border-top:1px dashed var(--line,#ccc);padding-top:10px">
                  <button class="btn" @click="coverForm.open=!coverForm.open">{{ coverForm.open ? '收起封面制作' : '制作封面' }}</button>
                  <span v-if="coverForm.done" class="muted" style="margin-left:8px">✓ {{ coverForm.done }}</span>
                  <div v-if="coverForm.open" style="margin-top:8px">
                    <div class="form-row"><label>背景图</label><input type="file" accept=".png,.jpg,.jpeg,.webp" @change="uploadCoverAsset('bg_asset_id',$event)"><span class="muted">{{ coverAssetName('bg_asset_id') || '必选' }}</span></div>
                    <div class="form-row"><label>人物形象</label><input type="file" accept=".png,.jpg,.jpeg,.webp" @change="uploadCoverAsset('person_asset_id',$event)"><span class="muted">{{ coverAssetName('person_asset_id') || '可选，右侧站立' }}</span></div>
                    <div class="form-row"><label>标题</label><input type="text" v-model="coverForm.title" placeholder="主标题；**文字** 琥珀高亮" style="width:340px"></div>
                    <div class="form-row"><label>眉题</label><input type="text" v-model="coverForm.kicker" placeholder="可选，顶部小字" style="width:240px"></div>
                    <div class="form-row"><label>副题</label><input type="text" v-model="coverForm.sub" placeholder="可选，底部小字" style="width:240px"></div>
                    <div class="form-row"><button class="btn primary" :disabled="coverForm.busy || !coverForm.title.trim() || !coverForm.bg_asset_id" @click="submitCover">{{ coverForm.busy ? '渲染中…（约 1 分钟）' : '生成封面' }}</button>
                      <span v-if="coverForm.err" class="err-text" style="color:#c0392b">{{ coverForm.err }}</span></div>
                  </div>
                </div>
              </template>
              <div v-else class="muted">本项目尚未出片 —— 第五步点「开始制作」后，成片会出现在这里。</div>
            </div>
              </div>
            </div>
            </div>
          </template>
        </div>
        <div style="position:sticky;top:64px;align-self:start;max-height:calc(100vh - 76px);overflow-y:auto;min-width:0">
          <div class="card"><h3>草稿箱（{{ makes.length }}）</h3>
            <div v-if="!makes.length" class="muted">尚无制作草稿</div>
            <div v-for="m in makes" :key="m.id" class="list-item" :class="{sel:cur===m.id}"
                 style="padding:7px 10px;cursor:pointer" title="点击载入该草稿" @click="selectMake(m.id)">
              <div class="t" style="display:flex;align-items:center;gap:6px">
                <span :title="m.title" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ m.title }}</span>
                <span style="display:inline-flex;gap:3px;flex-shrink:0">
                  <span v-for="stage in [1,2,3,4]" :key="stage" :title="['口播','脚本','语音','视频'][stage-1]+'：'+segBadge(stage,m).text" :style="{backgroundColor:segColor(stage,m)}" style="display:inline-block;width:7px;height:7px;border-radius:50%"></span></span></div>
              <div style="display:flex;align-items:center;gap:5px;margin-top:5px">
                <span class="muted" style="font-size:11px;flex:1;min-width:0;overflow:hidden;white-space:nowrap">{{ (m.updated_at || '').slice(5) }}</span>
                <button class="btn" style="padding:2px 9px;font-size:12px;flex-shrink:0" :disabled="makeActionBusy" @click.stop="selectMake(m.id)">{{ cur===m.id ? '退回' : '载入' }}</button>
                <button class="btn" style="padding:2px 9px;font-size:12px;flex-shrink:0" :disabled="makeActionBusy" @click.stop="startRenameDraft(m)">重命名</button>
                <button class="btn" style="padding:2px 9px;font-size:12px;flex-shrink:0" :disabled="makeActionBusy || Object.values(makeJobIds).includes(m.id)" @click.stop="deleteMake(m)">删除</button></div>
              <div v-if="renameDraft===m.id" class="form-row" style="gap:5px;margin:5px 0 0" @click.stop>
                <input v-model="renameDraftTitle" :disabled="makeActionBusy" style="min-width:0;flex:1"
                       placeholder="新标题" @keyup.enter="saveRenameDraft(m)" @keyup.esc="renameDraft=null">
                <button class="btn primary" style="padding:2px 9px;font-size:12px" @click="saveRenameDraft(m)">存</button>
                <button class="btn" style="padding:2px 9px;font-size:12px" @click="renameDraft=null">取消</button></div>
            </div>
          </div>
          <div class="card"><h3>视频项目（{{ productVideos.length }}）<button class="btn" @click="loadVideos">刷新</button></h3>
            <div v-if="!productVideos.length" class="muted">暂无已出片项目 —— 出了片的成品才会出现在这里</div>
          <div v-for="v in productVideos" :key="v.id" class="list-item" :class="{sel: sel === v}"
               style="padding:7px 10px;cursor:pointer" @click="openProj(v)">
            <div class="t" style="display:flex;align-items:center;gap:6px">
              <span :title="v.title" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ v.title }}</span>
              <span v-if="v.status !== 'built'" class="badge" :class="gateClass(v.status)" style="flex-shrink:0">{{ gateText(v.status) }}</span></div>
            <div style="display:flex;align-items:center;gap:5px;margin-top:5px">
              <span class="muted" style="font-size:11px;flex:1;min-width:0;overflow:hidden;white-space:nowrap">{{ v.date || v.id }}<span v-if="v.scenes"> · {{ v.scenes }} 幕</span><span v-if="v.verify_duration_s"> · {{ fmtDur(v.verify_duration_s) }}</span></span>
              <button class="btn" style="padding:2px 9px;font-size:12px;flex-shrink:0" @click.stop="openProj(v)">打开</button>
              <button class="btn" style="padding:2px 9px;font-size:12px;flex-shrink:0" @click.stop.prevent="delVideo(v)">删除</button></div>
          </div>
            <div v-if="orphanVideos.length" class="muted" style="font-size:11px;margin-top:6px;border-top:1px dashed var(--border);padding-top:6px">
              另有 {{ orphanVideos.length }} 个未出片残留(草稿类, 已隐藏)
              <a style="cursor:pointer;color:var(--red)" title="逐个确认后删除全部残留" @click.stop="cleanOrphanVideos">一键清理</a></div>
          </div>
        </div>
      </div>
      <div v-if="sel" role="presentation" @click.self="sel=null" @keydown.esc="sel=null" style="position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:80;display:flex;align-items:center;justify-content:center;padding:24px">
        <div class="card" role="dialog" aria-modal="true" aria-labelledby="video-project-title" tabindex="-1" style="width:min(860px,100%);max-height:90vh;overflow:auto">
          <h3 id="video-project-title" style="display:flex;gap:8px;align-items:center">
            <input v-model="projTitle" @keyup.enter="saveProjTitle" style="flex:1;min-width:0"
                   title="点击此处可重命名，回车或点「重命名」保存">
            <button class="btn" @click="saveProjTitle">重命名</button>
            <button class="btn" autofocus @click="sel=null">关闭</button></h3>
          <p class="muted">项目 {{ sel.id }} · 门禁状态：{{ gateText(sel.status) }} <span v-if="sel.verify_duration_s!=null" class="badge">成片 {{ Math.round(sel.verify_duration_s) }} 秒</span><span v-if="sel.verify_mode==='estimate'" class="badge yellow">无声预览版</span></p>
          <div v-if="buildWarnings.length && buildPid && sel.id.indexOf(buildPid)===0" class="notice"><div v-for="(w,i) in buildWarnings" :key="i">{{ w }}</div></div>
          <div v-if="sel.verify_warnings && sel.verify_warnings.length" class="notice"><strong>QA 警告</strong><div v-for="(w,i) in sel.verify_warnings" :key="i">{{ w }}</div></div>
          <div v-if="sel.verify_errors && sel.verify_errors.length" class="err-box"><div v-for="(e,i) in sel.verify_errors" :key="i">{{ e }}</div></div>
          <video v-if="selMp4" :src="selMp4" :key="selMp4" controls preload="metadata" style="max-height:420px"></video>
          <img v-else-if="selCover" :src="selCover" class="cover-thumb" style="max-width:280px"><div v-else class="muted">尚无渲染产物(out/ 为空)</div>
          <div v-if="sel.mp4.length>1" class="muted">产物：<span v-for="m in sel.mp4" :key="m" class="mono" style="margin-right:8px">{{ m }}</span></div>
          <div class="stub-wrap" style="margin:12px 0"><button class="btn stub" disabled>投稿 B站/抖音</button><div class="stub-tip">投稿（先草稿）：<code style="white-space:pre-wrap;overflow-wrap:anywhere">{{ pubCmd }}</code><button class="btn" @click="copyPubCmd">复制</button></div></div>
          <button class="btn" @click="delVideo(sel)">删除项目</button>
        </div>
      </div>
    </div>


    <!-- ═══ 子页7: 追踪账号 ═══ -->
    <div v-show="tab==='tracked'">
      <div class="card">
        <h3>YouTube 账号管理({{ chs.length }})
          <span v-if="chMeta && !chMeta.configured" class="muted" style="font-weight:400">
            · 未配 Key, 添加后待解析</span>
          <span style="float:right">
            <input type="text" v-model="chQ" class="mat-search" placeholder="搜索(频道名/handle/备注)"
                   style="width:200px;margin-right:8px">
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
          <div v-for="c in chRows" :key="c.id" class="acct-card">
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
        <div v-if="!chRows.length && chs.length" class="muted" style="padding:8px 0">无匹配频道</div>
        <p class="muted" style="margin-top:10px">
          启停只影响采集范围(停用频道不外呼); 解析与首轮数据在下一轮采集完成
          (计划任务每小时, 或到【热点追踪】点「立即采集」)。删除不停用历史快照。</p>
      </div>
    </div>
  </div>`,
};
