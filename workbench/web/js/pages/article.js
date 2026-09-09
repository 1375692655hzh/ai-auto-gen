/* 图文页: 四子页容器(推荐信息 / 内容生成 / 内容发布 / 自动化任务)
   结构定稿 = MoA 汇总(05-codex/06-cursor/07-主控):
   · 子页选择走壳层 WB.shell.setSubs(火山控制台式左侧菜单), 组件内 tab + v-show
   · 跨页素材通道 = WB.basket(localStorage, 与资讯页素材篮打通)
   · 真实数据: /recommend 打分排序 / drafts CRUD / ledger 只读 / automation CRUD
   · 桩: 真生成 / 真发布(--draft 红线) / 真实调度 —— 全部灰显附 CLI 提示 */
window.WB = window.WB || {};
WB.pages = WB.pages || {};

WB.pages.article = {
  data() {
    return {
      tab: "reco",
      /* 枚举(双标签制: 市场动态聚合; 定位/类型封闭枚举, 对齐 taxonomy.py) */
      dict: { markets: [] },
      tagEnums: { positionings: ["官方", "机构", "大V", "快讯源", "新闻源"],
                  item_types: ["聚合", "快讯", "资讯", "分析"] },
      /* ── 推荐信息/蹭蹭流量(X 统一数据面: 同一加载器, 两份预设状态) ──
         reco=选素材视角(默认时间序), surge=卡位视角(默认起爆序); 全部只显示 X 条目 */
      sinceOpts: [["1h", "近1小时"], ["6h", "近6小时"], ["12h", "近12小时"], ["24h", "近1天"], ["48h", "近2天"]],
      sortOpts: [["fv", "金融价值"], ["time", "时间顺序"], ["growth", "增速"],
                 ["pred", "预测浏览"], ["exposure", "评论曝光"]],
      xfReco: { since: "12h", sort: "fv", markets: [], sectors: [], golden: false,
                bigOnly: false, finance: false, items: [], total: 0, meta: {}, loading: false },
      hideP3: false,                     /* FV 视图: 隐藏低值(P3)折叠开关 */
      /* ── 账号管理(全 X 池只读 + 本地偏好 x_account_prefs.json) ── */
      xaccts: { items: [], meta: {}, q: "", pos: "", followOnly: false, loading: false },
      /* 蹭蹭流量 = SoPilot 热帖 RSS(唯一来源, 不走数据站) */
      xfSurge: { sort: "prob", items: [], total: 0, meta: {}, loading: false },
      rssSortOpts: [["prob", "爆火概率"], ["views", "浏览量"], ["exposure", "评论曝光"], ["time", "时间"]],
      basketIds: {},                     // 已在素材池的条目 id(「已加入」态)
      /* X 池账号档案(与资讯页同源: /x-accounts + /x-profiles) + 正文截断状态 */
      xAccounts: {}, xProfiles: {}, bodyExpanded: {},
      /* ── 内容生成(实时编辑 = 素材池勾选 + 生成模块排列组合 + 固定模板) ── */
      materials: [], matQ: "",
      modules: [
        { id: "retrieve", title: "信息检索", desc: "按素材标的/关键词回查数据站, 补全上下文", on: true },
        { id: "snapshot", title: "快照抓取", desc: "抓素材标的近 3 个月行情 K 线图(作图文配图)", on: false },
        { id: "tech", title: "技术分析", desc: "算素材标的近端支撑位/阻力位(纯规则, 叠画进图)", on: false },
        { id: "aggregate", title: "聚合分析", desc: "汇总 X 大V 与机构/分析师对此事件的看法(LLM)", on: true },
      ],
      /* 成稿参数: 平台风格(默认X) / 语种 / 免费·付费(决定字数上限) / 成稿模板(信息结构, grok 定稿 7 模板) */
      genParams: { platform: "x", lang: "en", tier: "free", template: "catalyst-take" },
      genLangs: [["en", "英语"], ["zh-CN", "简中"], ["zh-TW", "繁中"], ["ja", "日语"], ["yue", "粤语"]],
      genTiers: [["free", "免费(≤280 加权字符, CJK 计2 ≈140 汉字)"],
                 ["paid", "付费 Basic/Premium(≤25,000 字, 可发长文)"]],
      genTpls: [{ v: "catalyst-take", t: "事件快评 · 单票突发催化(默认)" },
                { v: "earnings-print", t: "业绩拆解 · 财报/指引解读" },
                { v: "macro-print", t: "数据读数 · CPI/NFP 等宏观打印" },
                { v: "policy-call", t: "政策纪要 · 央行决议/监管" },
                { v: "tape-recap", t: "盘面综述 · 开收盘/盘中扫描" },
                { v: "thesis-note", t: "深度观点 · 非事件驱动论点" },
                { v: "thread-post", t: "串推 · 一帖拆多条(免费档涨触达)" },
                { v: "risk-flag", t: "风险提示 · 预警/证伪" },
                { v: "news-flash", t: "资讯速递 · 单条重点资讯快报", zero: 1 },
                { v: "fact-sheet", t: "披露卡 · 公告/财报要点陈列", zero: 1 },
                { v: "week-ahead", t: "一周日历 · 下周财经事件表", zero: 1 },
                { v: "earnings-watch", t: "财报前瞻 · 本周财报票+关注点", zero: 1 },
                { v: "funding-trail", t: "融资脉络 · 历轮融资时间线", zero: 1 }],
      tplLegacy: { short: "catalyst-take", morning: "tape-recap", digest: "thesis-note" },
      genJob: { running: false, progress: {}, result: "", error: "", hint: "" },
      genResult: null, genTimer: null,
      genHistory: [], historyLoading: false, historyLoaded: false,
      calendarLoading: false, genDownloading: false, tplSuggestion: null,
      manualForm: { show: false, title: "", text: "", time: "", source: "" },
      flows: [], template: "",
      editingId: "", editorTitle: "", editorContent: "",
      drafts: [], runs: [],
      /* ── 信息检索(纯只读回查: 素材→全文/同簇/同标的; retrieveRes 按 seed_id 索引) ── */
      retrieving: false, retrieveRes: {}, rvOpen: {},
      /* ── 内容发布 ── */
      pubDraftId: "", pubWhen: "now", pubTime: "", pubAccounts: [], pubMethod: "xai",
      accounts: [], ledger: { rows: [], stats: {} },
      /* ── 自动化任务 ── */
      tasks: [],
      autoForm: { name: "", note: "", template: "", scheduleKind: "daily",
                  time: "08:00", weekday: 1, target: "draft" },
      autoModules: ["retrieve", "aggregate"],
    };
  },
  watch: {
    tab(t) { if (t === "gen" && !this.historyLoaded) this.loadGenHistory(); },
  },
  computed: {
    wordCount() { return (this.editorContent || "").length; },
    onModules() { return this.modules.filter((m) => m.on).map((m) => m.id); },
    /* X 计权字数(与 server gcompose.weighted_len 同规则: CJK/emoji×2, URL 恒=23) */
    xwCount() { return this.xwLen(this.editorContent); },
    xwLimit() { return this.genParams.tier === "paid" ? 25000 : 280; },
    canGenerate() { return this.selCount > 0 && !this.genJob.running; },
    pubDraft() { return this.drafts.find((d) => d.id === this.pubDraftId) || null; },
    /* 素材池: 顶部小搜索(正文/来源模糊匹配) */
    filteredMaterials() {
      const q = this.matQ.trim().toLowerCase();
      if (!q) return this.materials;
      return this.materials.filter((m) =>
        (m.text || "").toLowerCase().includes(q) ||
        (m.source || "").toLowerCase().includes(q));
    },
    selCount() { return this.materials.filter((m) => this.matChecked(m)).length; },
    /* X 热帖市场 chips: 取池账号实际覆盖的市场 */
    xMarketChips() {
      const s = new Set();
      for (const a of Object.values(this.xAccounts)) (a.markets || []).forEach((m) => s.add(m));
      return [...s].sort();
    },
    /* FV 分组视图: 仅 sort=fv 时按 P0/P1/其余分组, 其余排序原样单列 */
    recoGroups() {
      const items = this.xfReco.items || [];
      if (this.xfReco.sort !== "fv") return [{ key: "all", label: "", cls: "", items }];
      const g = { P0: [], P1: [], rest: [] };
      items.forEach((r) => g[r.fv_tier === "P0" || r.fv_tier === "P1" ? r.fv_tier : "rest"].push(r));
      const rest = this.hideP3 ? g.rest.filter((r) => r.fv_tier !== "P3") : g.rest;
      const out = [];
      if (g.P0.length) out.push({ key: "p0", label: "打断级 P0", cls: "red", items: g.P0 });
      if (g.P1.length) out.push({ key: "p1", label: "今日必读 P1", cls: "yellow", items: g.P1 });
      if (rest.length) out.push({ key: "rest", label: "简报候选与归档", cls: "", items: rest });
      return out;
    },
    /* 账号管理行过滤: 关键词(名称/handle/市场) + 定位 chips + 仅看关注; 排序服务端已定 */
    xacctRows() {
      const q = this.xaccts.q.trim().toLowerCase();
      let rows = this.xaccts.items;
      if (this.xaccts.pos) rows = rows.filter((a) => a.positioning === this.xaccts.pos);
      if (this.xaccts.followOnly) rows = rows.filter((a) => a.follow);
      if (q) rows = rows.filter((a) =>
        (a.name || "").toLowerCase().includes(q) ||
        (a.handle || "").toLowerCase().includes(q) ||
        (a.markets || []).some((m) => m.toLowerCase().includes(q)));
      return rows;
    },
  },
  methods: {
    /* ── 浏览层按需翻译: 展示回退链 text_zh(服务端) → WB.trans 本地缓存 → 原文;
       trRef 给卡片文本元素挂 {__trItem, __trText}, WB.trans.scan 视口内自动批量翻 ── */
    dispText(r) { return r.text_zh || WB.trans.zh(r.text) || r.text; },
    trRef(el, r) {
      if (el) { el.__trItem = r; el.__trText = r.text || ""; el.setAttribute("data-tr", "1"); }
    },
    registerSubs() {
      if (!WB.shell) return;
      if (!location.hash.replace(/^#/, "").startsWith("/article")) return;  // 迟到的异步回调不得覆盖别的页面
      const I = (p) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + p + "</svg>";
      WB.shell.setSubs([
        { id: "reco", title: "推荐信息", cnt: this.xfReco.total || "",
          icon: I('<polygon points="12 2 15 9 22 9.3 16.5 14 18.5 21 12 17 5.5 21 7.5 14 2 9.3 9 9"/>'),
          onPick: () => { this.tab = "reco"; } },
        { id: "surge", title: "蹭蹭流量", cnt: this.xfSurge.total || "",
          icon: I('<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>'),
          onPick: () => { this.tab = "surge"; } },
        { id: "gen", title: "内容生成", cnt: this.materials.length || "",
          icon: I('<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>'),
          onPick: () => { this.tab = "gen"; } },
        { id: "pub", title: "内容发布", cnt: this.drafts.length || "",
          icon: I('<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4Z"/>'),
          onPick: () => { this.tab = "pub"; } },
        { id: "auto", title: "自动化任务", cnt: this.tasks.length || "",
          icon: I('<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/>'),
          onPick: () => { this.tab = "auto"; } },
        { id: "xaccts", title: "账号管理", cnt: this.xaccts.meta.count || "",
          icon: I('<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'),
          onPick: () => { this.tab = "xaccts"; } },
      ], this.tab);
    },
    go(t) { this.tab = t; if (WB.shell) WB.shell.setSub(t); },

    /* ── X 统一数据面: 推荐信息/蹭蹭流量共用加载器(两份预设状态各自独立) ── */
    sinceValue(since) {
      const now = new Date();
      const fmt = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" +
        String(d.getDate()).padStart(2, "0") + " " + String(d.getHours()).padStart(2, "0") + ":" +
        String(d.getMinutes()).padStart(2, "0");
      const map = { "1h": 3600e3, "6h": 6 * 3600e3, "12h": 12 * 3600e3,
                    "24h": 86400e3, "48h": 2 * 86400e3 };
      return map[since] ? fmt(new Date(now - map[since])) : "";
    },
    async loadDict() {
      try {
        const d = await WB.api.get("/v1/sources");
        const mk = new Set();
        for (const s of d.sources) (s.markets || []).forEach((m) => mk.add(m));
        this.dict = { markets: [...mk].sort() };
      } catch (e) { /* 数据站未起时 loadXF 会报错展示 */ }
    },
    async loadXF(key) {
      const st = this[key];
      st.loading = true;
      try {
        const p = new URLSearchParams({ range: st.since, sort: st.sort, limit: "100" });
        if (st.golden) p.set("golden", "1");
        if (st.bigOnly) p.set("min_followers", "100000");
        if (st.finance) p.set("finance", "1");
        if (st.markets.length) p.set("market", st.markets.join(","));
        if (st.sectors.length) p.set("sector", st.sectors[0]);
        const d = await WB.api.get("/x-surge?" + p.toString());
        (d.items || []).forEach((r, i) => { r.rank = i + 1; });   // 服务端已排好序
        st.items = d.items; st.total = d.total;
        st.meta = { ...(d.meta || {}), golden_n: d.golden_n, err: "" };
      } catch (e) {
        st.items = [];
        st.meta = { ...(st.meta || {}), err: (e && e.error) || "接口不可用" };
      }
      st.loading = false;
      this.registerSubs();
      this.$nextTick(() => WB.trans.scan(this.$el));   // 视口自动翻译新渲染卡片
    },
    /* 蹭蹭流量(RSS 版): 只吃 SoPilot 热帖缓存, 无筛选维度仅四选排序 */
    async loadSurgeRss() {
      const st = this.xfSurge;
      st.loading = true;
      try {
        const d = await WB.api.get("/x-surge-rss?sort=" + st.sort);
        st.items = d.items; st.total = d.total; st.meta = d.meta || {};
      } catch (e) { st.items = []; }
      st.loading = false;
      this.registerSubs();
      this.$nextTick(() => WB.trans.scan(this.$el));   // 视口自动翻译新渲染卡片
    },
    /* ── FV 金融价值徽章/明细(对齐 news.js 标签辅助, 双实现保持两处一致) ── */
    tierBadge(t) { return { P0: "red", P1: "yellow", P2: "blue", P3: "" }[t] || ""; },
    fvTitle(r) {
      const p = r.fv_parts || {};
      return "事件" + (p.event ?? 0) + " · 主体" + (p.entity ?? 0) +
             " · 信源" + (p.source ?? 0) + " · 影响面" + (p.impact ?? 0) +
             " · 意外度" + (p.surprise ?? 5) + "(缺省) · 印证时效" + (p.proof ?? 0) +
             " — 阈值 P0≥75 / P1≥60 / P2≥40";
    },
    sectorParts(sec) {
      const p = String(sec).split(">");
      return [p[0] || "", p.slice(1).join(">")];
    },
    visibleSectors(r) { return (r.sectors || []).slice(0, 2); },
    sectorsRest(r) { return Math.max((r.sectors || []).length - 2, 0); },
    /* 兼容两代值域: 库存 bullish/bearish 与筛选枚举 bull/bear */
    sentimentBadge(s) {
      return (s === "bullish" || s === "bull") ? "green"
           : (s === "bearish" || s === "bear") ? "red"
           : s === "neutral" ? "yellow" : "";
    },
    sentimentText(s) {
      return { bullish: "利好", bull: "利好", bearish: "利空", bear: "利空",
               neutral: "中性" }[s] || s;
    },
    /* ── 账号管理: 全池只读, 关注/本地备注写 data/workbench/x_account_prefs.json ── */
    async loadXaccts() {
      this.xaccts.loading = true;
      try {
        const d = await WB.api.get("/x-accounts-manage");
        this.xaccts.items = d.accounts || [];
        this.xaccts.meta = { count: d.count, followed_n: d.followed_n,
                             disabled_n: d.disabled_n, err: "" };
      } catch (e) {
        this.xaccts.items = [];
        this.xaccts.meta = { ...(this.xaccts.meta || {}), err: (e && e.error) || "接口不可用" };
      }
      this.xaccts.loading = false;
      this.registerSubs();
    },
    async saveXPref(a, patch) {
      try { await WB.api.post("/x-account-pref", { handle: a.handle, ...patch }); }
      catch (e) { WB.toast("保存失败: " + (e.error || "")); }
    },
    toggleXFollow(a) {
      a.follow = !a.follow;                              // 乐观更新, 失败由 toast 提示
      this.xaccts.meta.followed_n = (this.xaccts.meta.followed_n || 0) + (a.follow ? 1 : -1);
      this.saveXPref(a, { follow: a.follow });
    },
    saveXNote(a) { this.saveXPref(a, { note: a.local_note }); },
    xfCopy(r) { WB.copyText(this.dispText(r)); },
    xfToggleChip(key, field, val) {
      const arr = this[key][field];
      const i = arr.indexOf(val);
      i >= 0 ? arr.splice(i, 1) : arr.push(val);
      this.loadXF(key);
    },
    xfToggleFlag(key, field) {
      this[key][field] = !this[key][field];
      this.loadXF(key);
    },
    /* 加入素材: 不跳页(用户还要继续逛), 点过变「已加入」; 行对象凑齐 basket 五字段契约 */
    addXToPool(r) {
      WB.basket.add({ id: r.status_id, time: r.time, source: r.name,
                      text: this.dispText(r), url: r.reply_url });
      this.basketIds[r.status_id] = true;
      this.syncMaterials();
    },
    initBasketIds() {
      this.basketIds = {};
      for (const m of WB.basket.list()) this.basketIds[m.id] = true;
    },
    fmtFol(n) {
      return n >= 1e4 ? (n / 1e4).toFixed(1).replace(/\.0$/, "") + "万" : String(n);
    },
    fmtN(n) {
      if (n == null) return "—";
      if (n >= 1e8) return (n / 1e8).toFixed(1).replace(/\.0$/, "") + "亿";
      if (n >= 1e4) return (n / 1e4).toFixed(1).replace(/\.0$/, "") + "万";
      return String(Math.round(n));
    },
    /* ── X 条目按账号渲染(与资讯页同实现, 保持两处一致) ── */
    async loadX() {
      try { this.xAccounts = (await WB.api.get("/x-accounts")).accounts || {}; } catch (e) {}
      try { this.xProfiles = (await WB.api.get("/x-profiles")).profiles || {}; } catch (e) {}
    },
    isX(it) { return !!it.author_handle; },
    xAcct(it) { return this.xAccounts[String(it.author_handle || "").toLowerCase()] || null; },
    xProf(it) { return this.xProfiles[String(it.author_handle || "").toLowerCase()] || null; },
    xName(it) {
      const a = this.xAcct(it);
      if (a && a.name) return a.name;
      const s = String(it.source || "").replace(/^X·/, "").trim();
      return s || "@" + it.author_handle;
    },
    xBrief(it) {
      const a = this.xAcct(it), p = this.xProf(it);
      return (a && a.note) || (p && p.bio) || "";
    },
    xPos(it) {
      const a = this.xAcct(it);
      return (a && a.positioning) || it.positioning || "";
    },
    xMarkets(it) {
      const a = this.xAcct(it);
      return (a && a.markets && a.markets.length) ? a.markets : (it.markets || []);
    },
    bodyLong(it) {
      return ((it.title ? it.title.length + 3 : 0) + (it.text || "").length) > 300;
    },
    bodyClamp(it) { return this.bodyLong(it) && !this.bodyExpanded[it.id]; },

    /* ── 内容生成 ── */
    syncMaterials() { this.materials = WB.basket.list(); this.registerSubs(); },
    xwLen(s) {
      s = String(s || "");
      const urls = s.match(/https?:\/\/\S+/g) || [];
      let n = urls.length * 23;
      for (const ch of s.replace(/https?:\/\/\S+/g, "")) {
        const o = ch.codePointAt(0);
        n += ((o >= 0x2E80 && o <= 0x9FFF) || (o >= 0xF900 && o <= 0xFAFF) ||
              (o >= 0x3000 && o <= 0x303F) || (o >= 0xFE30 && o <= 0xFE4F) ||
              (o >= 0xFF00 && o <= 0xFFEF) || o >= 0x1F000) ? 2 : 1;
      }
      return n;
    },
    /* 开始生成: 端点校验+spawn CLI(检索/行情/聚合/LLM 全在子进程), 前端 2s 轮询 */
    async startGen() {
      const items = this.materials.filter((m) => this.matChecked(m))
        .map((m) => ({ id: m.id, time: m.time, source: m.source, text: m.text, url: m.url,
                       body: m.body || "" }));
      if (!items.length) { WB.toast("先勾选参与生成的素材"); return; }
      try {
        await WB.api.post("/gen-compose", { items, modules: this.onModules, ...this.genParams });
      } catch (e) {
        WB.toast("启动失败: " + (e.error || "") + (e.hint ? " —— " + e.hint : ""));
        return;
      }
      this.genResult = null;
      this.genJob = { running: true, progress: { stage: "start", pct: 0, message: "已启动" },
                      result: "", error: "", hint: "" };
      this.genTimer = setInterval(this.pollGen, 2000);
    },
    async pollGen() {
      let d;
      try { d = await WB.api.get("/gen-jobs"); } catch (e) { return; }
      const j = (d || {}).compose || {};
      this.genJob = j;
      if (j.running) return;
      clearInterval(this.genTimer); this.genTimer = null;
      if (j.exit === 0 && j.result) {
        try {
          this.genResult = await WB.api.get("/gen-posts/" + j.result);
          this.editorContent = this.genResult.text || "";
          if (!this.editorTitle)
            this.editorTitle = (this.genResult.text || "").split("\n")[0].slice(0, 40);
          this.loadGenHistory();
          WB.toast("成稿完成: 加权 " + this.genResult.weighted_len + " / " + this.genResult.limit);
        } catch (e) { WB.toast("取成稿失败: " + (e.error || "")); }
      } else if (j.exit) {
        WB.toast("生成失败: " + (j.error || "") + (j.hint ? " —— " + j.hint : ""));
      }
    },
    async copyGenText(quiet = false) {
      if (!this.genResult) return false;
      try {
        try { await navigator.clipboard.writeText(this.genResult.text || ""); }
        catch (e) {
          const ta = document.createElement("textarea");
          ta.value = this.genResult.text || ""; ta.style.position = "fixed"; ta.style.opacity = "0";
          document.body.appendChild(ta); ta.select();
          try { if (!document.execCommand("copy")) throw new Error("copy failed"); }
          finally { ta.remove(); }
        }
        if (quiet !== true) WB.toast("已复制到剪贴板");
        return true;
      } catch (e) { WB.toast("复制失败, 请手动选择文本"); return false; }
    },
    copyTweet(tweet) { WB.copyText(tweet); },
    downloadGenImage(img) {
      const a = document.createElement("a");
      a.href = img.url; a.download = img.file;
      document.body.appendChild(a); a.click(); a.remove();
    },
    async copyGenAndDownload() {
      if (!this.genResult || this.genDownloading) return;
      const images = [...(this.genResult.images || [])];
      this.genDownloading = true;
      try {
        if (!await this.copyGenText(true)) return;
        for (let i = 0; i < images.length; i++) {
          if (i) await new Promise(resolve => setTimeout(resolve, 300));
          this.downloadGenImage(images[i]);
        }
        WB.toast(images.length ? "文字已复制, 图片已下载, 到 X 先贴文字再拖图" : "文字已复制, 本篇无配图");
      } catch (e) { WB.toast("图片下载失败, 请逐张下载"); }
      finally { this.genDownloading = false; }
    },
    templateTitle(slug) {
      const tpl = this.genTpls.find(t => t.v === slug);
      return tpl ? tpl.t.split(" · ")[0] : (slug || "—");
    },
    async loadGenHistory() {
      if (this.historyLoading) return;
      this.historyLoading = true;
      try {
        this.genHistory = (await WB.api.get("/gen-posts")).posts || [];
        this.historyLoaded = true;
      } catch (e) { WB.toast("加载生成历史失败: " + (e.error || "请求失败")); }
      finally { this.historyLoading = false; }
    },
    async loadGenPost(post) {
      try {
        const r = await WB.api.get("/gen-posts/" + encodeURIComponent(post.id));
        this.genResult = r; this.editingId = "";
        this.editorContent = r.text || "";
        this.editorTitle = this.editorContent.split("\n")[0].slice(0, 40);
        WB.toast("已载入编辑器");
      } catch (e) { WB.toast("载入失败: " + (e.error || "请求失败")); }
    },
    async deleteGenPost(post) {
      try {
        await WB.api.del("/gen-posts/" + encodeURIComponent(post.id));
        this.genHistory = this.genHistory.filter(p => p.id !== post.id);
        if (this.genResult && this.genResult.id === post.id) this.genResult = null;
        WB.toast("已删除成稿及配图");
      } catch (e) { WB.toast("删除失败: " + (e.error || "请求失败")); }
    },
    async loadCalendar(source) {
      if (this.calendarLoading) return;
      this.calendarLoading = true;
      try {
        const d = await WB.api.get("/v1/items?sources=" + encodeURIComponent(source) + "&limit=50");
        const rows = d.items || [];
        if (!rows.length) {
          WB.toast("数据站暂无日历缓存, 先跑 sources refresh 或等任务计划"); return;
        }
        const existing = WB.basket.list();
        const ids = new Set(existing.map(m => m.id).filter(Boolean));
        const urls = new Set(existing.map(m => m.url).filter(Boolean));
        let added = 0;
        for (const row of rows) {
          if ((row.id && ids.has(row.id)) || (row.url && urls.has(row.url))) continue;
          const id = row.id || row.url;
          if (!id) continue;
          WB.basket.add({ ...row, id });
          ids.add(id); if (row.url) urls.add(row.url);
          added++;
        }
        this.syncMaterials(); this.initBasketIds();
        WB.toast("已加入并勾选 " + added + " 条日历素材");
      } catch (e) { WB.toast("拉取日历失败: " + (e.error || "请求失败")); }
      finally { this.calendarLoading = false; }
    },
    recommendTemplate(groups) {
      const mapping = { earnings: "earnings-print", guidance: "earnings-print",
                        macro: "macro-print", policy: "policy-call" };
      const names = { earnings: "财报", guidance: "指引", macro: "宏观数据", policy: "政策" };
      const votes = {}, events = {};
      for (const g of groups) {
        const raw = (g.tags || {}).event_type;
        for (const event of new Set(Array.isArray(raw) ? raw : (raw ? [raw] : []))) {
          const tpl = mapping[event] || "catalyst-take";
          votes[tpl] = (votes[tpl] || 0) + 1;
          (events[tpl] ||= new Set()).add(names[event] || "其他事件");
        }
      }
      const winner = Object.keys(votes).sort((a, b) => votes[b] - votes[a])[0];
      this.tplSuggestion = winner && winner !== this.genParams.template
        ? { template: winner, event: [...events[winner]].join("/") } : null;
    },
    applyTplSuggestion() {
      if (this.tplSuggestion) this.genParams.template = this.tplSuggestion.template;
      this.tplSuggestion = null;
    },
    /* 文图一起: ClipboardItem 双 MIME; X 发帖框粘贴取其一, 建议先贴文字再补图 */
    async copyGenAll() {
      const r = this.genResult;
      if (!r) return;
      if ((r.images || []).length) {
        try {
          const blob = await (await fetch(r.images[0].url)).blob();
          await navigator.clipboard.write([new ClipboardItem({
            "text/plain": new Blob([r.text], { type: "text/plain" }), "image/png": blob })]);
          WB.toast("图文已复制 —— X 粘贴会先取一项, 建议先贴文字再用「复制图片」补图");
          return;
        } catch (e) { /* 降级走纯文字 */ }
      }
      WB.copyText(r.text);
      WB.toast("已复制文字");
    },
    async copyGenImage(img) {
      try {
        const blob = await (await fetch(img.url)).blob();
        await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
        WB.toast("图片已复制, 到 X 发帖框直接粘贴");
      } catch (e) { WB.toast("图片复制失败 —— 用「下载」后手动拖入 X"); }
    },
    /* ── 信息检索: 勾选素材 → 服务端三路回查(全文/同簇/同标的), 结果按素材折叠展示 ── */
    async runRetrieve() {
      const items = this.materials.filter((m) => this.matChecked(m))
        .map((m) => ({ id: m.id, time: m.time, source: m.source, text: m.text, url: m.url,
                       body: m.body || "" }));
      if (!items.length) { WB.toast("先勾选要检索的素材"); return; }
      this.retrieving = true;
      try {
        const d = await WB.api.post("/retrieve", { items });
        (d.groups || []).forEach((g) => { this.retrieveRes[g.seed_id] = g; });
        this.recommendTemplate(d.groups || []);
        WB.toast("检索完成: " + (d.groups || []).length + " 条素材, 数据站查询 " +
                 ((d.meta || {}).queries || 0) + " 次");
      } catch (e) {
        WB.toast("检索失败: " + (e.error || "") + (e.hint ? " —— " + e.hint : ""));
      }
      this.retrieving = false;
    },
    toggleRv(id) { this.rvOpen[id] = !this.rvOpen[id]; },
    mergeText(t) {
      this.editorContent = (this.editorContent || "") + t;
      WB.toast("已并入编辑器");
    },
    mergeHit(h) {
      this.mergeText("\n\n> 【" + (h.source || "来源") + "】" + (h.time || "") + " — "
                     + (h.text || "") + "\n> 原文: " + (h.url || "(无链接)"));
    },
    mergeAnchor(m) {
      const hy = (this.retrieveRes[m.id] || {}).hydrated;
      if (!hy) return;
      this.mergeText("\n\n> 【原文】" + (hy.time || "") + (hy.title ? " " + hy.title : "") + " — "
                     + (hy.full || "") + "\n> 原文: " + (hy.url || m.url || "(无链接)"));
    },
    removeMaterial(id) { WB.basket.remove(id); this.syncMaterials(); },
    /* 素材池勾选: 无 sel 字段的旧数据按已选兼容 */
    matChecked(m) { return m.sel !== false; },
    toggleMatSel(m) { WB.basket.setSel(m.id, !this.matChecked(m)); this.syncMaterials(); },
    /* 时效: 距发布小时数; >48h 灰显提醒(m.time 形如 "2026-09-03 14:05") */
    ageHours(m) {
      const t = new Date(String(m.time || "").replace(" ", "T"));
      return isNaN(t) ? 0 : (Date.now() - t.getTime()) / 3600e3;
    },
    ageText(m) {
      const h = this.ageHours(m);
      if (h < 1) return "刚刚";
      if (h < 24) return Math.floor(h) + " 小时前";
      return Math.floor(h / 24) + " 天前";
    },
    isStale(m) { return this.ageHours(m) > 48; },
    /* ── 手动录入素材: 用户自己找到/粘贴的内容直接进素材池。
       id = manual-+正文内容哈希(重复粘贴自动撞篮提示); 链接当场剥除(成稿零链接红线),
       全文走 body 字段(篮存 200 字截断只针对 text 摘要, body 保 2000 字)。 ── */
    _fnv(s) {
      let h = 0x811c9dc5;
      for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = (h * 0x01000193) >>> 0; }
      return h.toString(36);
    },
    addManual() {
      const f = this.manualForm;
      const raw = (f.text || "").trim();
      if (raw.length < 20) { WB.toast("正文至少 20 字"); return; }
      const nLinks = (raw.match(/https?:\/\/\S+/g) || []).length;
      const body = raw.replace(/https?:\/\/\S+/g, "").replace(/[ \t]+\n/g, "\n").trim().slice(0, 2000);
      const id = "manual-" + this._fnv(body);
      if (WB.basket.list().some((r) => r.id === id)) { WB.toast("该内容已在素材池(重复粘贴)"); return; }
      const title = (f.title || "").trim() || body.split("\n")[0].slice(0, 30);
      const t = f.time ? f.time.replace("T", " ")
                       : new Date(Date.now() - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 16).replace("T", " ");
      WB.basket.add({ id, time: t, source: (f.source || "").trim() || "手动录入",
                      text: (title + "\n" + body).slice(0, 200), url: "", body });
      this.manualForm = { show: false, title: "", text: "", time: "", source: "" };
      this.syncMaterials(); this.initBasketIds();
      if (nLinks) WB.toast("已剥除 " + nLinks + " 个链接(成稿零链接)");
    },
    moveModule(i, dir) {
      const j = i + dir;
      if (j < 0 || j >= this.modules.length) return;
      const [m] = this.modules.splice(i, 1);
      this.modules.splice(j, 0, m);
    },
    async loadFlows() {
      try { this.flows = (await WB.api.get("/flows")).flows; } catch (e) {}
    },
    async loadRuns() {
      try { this.runs = (await WB.api.get("/runs")).runs; } catch (e) {}
    },
    async loadDrafts() {
      try { this.drafts = (await WB.api.get("/drafts")).drafts; } catch (e) {}
      this.registerSubs();
    },
    async saveDraft() {
      const body = {
        title: this.editorTitle || "未命名草稿", content: this.editorContent,
        items: this.materials.filter((m) => this.matChecked(m)).map((m) => m.id),
        modules: this.onModules,
        template: this.genParams.template,
        gen: { ...this.genParams },
        publish: { when: this.pubWhen, time: this.pubTime,
                   accounts: this.pubAccounts, method: this.pubMethod },
      };
      if (this.editingId) body.id = this.editingId;
      try {
        const d = await WB.api.post("/drafts", body);
        this.editingId = d.id;
        WB.toast("草稿已保存");
        this.loadDrafts();
      } catch (e) { WB.toast("保存失败: " + (e.error || "")); }
    },
    editDraft(d) {
      this.editingId = d.id;
      this.editorTitle = d.title; this.editorContent = d.content;
      this.template = d.template || "";
      if (d.gen) this.genParams = { ...this.genParams, ...d.gen };
      this.genParams.template = this.tplLegacy[this.genParams.template] || this.genParams.template;
      const on = new Set(d.modules || []);
      this.modules.forEach((m) => { m.on = on.has(m.id); });
      if (d.publish) {
        this.pubWhen = d.publish.when || "now"; this.pubTime = d.publish.time || "";
        this.pubAccounts = d.publish.accounts || []; this.pubMethod = d.publish.method || "xai";
      }
      this.go("gen");
    },
    async delDraft(d) {
      await WB.api.del("/drafts/" + d.id);
      if (this.editingId === d.id) this.newDraft();
      this.loadDrafts();
    },
    newDraft() {
      this.editingId = ""; this.editorTitle = ""; this.editorContent = "";
    },
    stepClass(v) {
      const s = String(v).toLowerCase();
      return s.includes("waiting") ? "waiting" : (s.includes("done") || s.includes("ok") ? "done" : "");
    },

    /* ── 内容发布 ── */
    pickPubDraft(d) {
      this.pubDraftId = d.id;
      const p = d.publish || {};
      this.pubWhen = p.when || "now"; this.pubTime = p.time || "";
      this.pubAccounts = p.accounts || []; this.pubMethod = p.method || "xai";
    },
    async loadAccounts() {
      try { this.accounts = (await WB.api.get("/track/accounts")).accounts; } catch (e) {}
    },
    async loadLedger() {
      try { this.ledger = await WB.api.get("/ledger"); } catch (e) {}
    },
    togglePubAccount(a) {
      const key = a.platform + "@" + a.account;
      const i = this.pubAccounts.indexOf(key);
      i >= 0 ? this.pubAccounts.splice(i, 1) : this.pubAccounts.push(key);
    },
    hasPubAccount(a) { return this.pubAccounts.includes(a.platform + "@" + a.account); },

    /* ── 自动化任务 ── */
    async loadTasks() {
      try { this.tasks = (await WB.api.get("/automation")).tasks; } catch (e) {}
      this.registerSubs();
    },
    copyFromGen() {
      this.autoForm.template = this.genParams.template;
      this.autoModules = this.onModules.slice();
      WB.toast("已复制内容生成页的工作流配置");
    },
    autoModuleToggle(id) {
      const i = this.autoModules.indexOf(id);
      i >= 0 ? this.autoModules.splice(i, 1) : this.autoModules.push(id);
    },
    async saveTask() {
      if (!this.autoForm.name.trim()) { WB.toast("先填任务名称"); return; }
      await WB.api.post("/automation", {
        name: this.autoForm.name, note: this.autoForm.note,
        template: this.autoForm.template, modules: this.autoModules,
        schedule: { kind: this.autoForm.scheduleKind, time: this.autoForm.time,
                    weekday: this.autoForm.scheduleKind === "weekly" ? this.autoForm.weekday : null },
        publish: { target: this.autoForm.target },
      });
      WB.toast("任务已保存(调度器本期留桩, 不会到点真跑)");
      this.autoForm.name = ""; this.autoForm.note = "";
      this.loadTasks();
    },
    async delTask(t) { await WB.api.del("/automation/" + t.id); this.loadTasks(); },
    scheduleText(t) {
      const s = t.schedule || {};
      const wk = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"][s.weekday] || "";
      return s.kind === "weekly" ? wk + " " + s.time
           : s.kind === "workday" ? "工作日 " + s.time : "每天 " + s.time;
    },
    moduleTitles(ids) {
      const all = { retrieve: "信息检索", snapshot: "快照抓取", tech: "技术分析", aggregate: "聚合分析" };
      return (ids || []).map((i) => all[i] || i).join(" → ");
    },
  },
  async mounted() {
    try {
      const d = await WB.api.get("/settings");
      const defaults = d.gen_defaults || {};
      if (this.genLangs.some(([v]) => v === defaults.lang)) this.genParams.lang = defaults.lang;
      if (this.genTiers.some(([v]) => v === defaults.tier)) this.genParams.tier = defaults.tier;
      if (this.genTpls.some(t => t.v === defaults.template)) this.genParams.template = defaults.template;
    } catch (e) {} // 取不到设置时保留现有默认值; 草稿恢复在此后覆盖。
    this.registerSubs();
    this.syncMaterials();
    this.initBasketIds();
    this.loadDict(); this.loadX(); this.loadXF("xfReco"); this.loadSurgeRss();
    this.loadFlows(); this.loadRuns(); this.loadDrafts();
    this.loadAccounts(); this.loadLedger(); this.loadTasks(); this.loadXaccts();
    WB.api.get("/gen-jobs").then((d) => {           // 页面重开时有未完成的生成 → 续上轮询
      const j = ((d || {}).compose) || {};
      if (j.running) { this.genJob = j; this.genTimer = setInterval(this.pollGen, 2000); }
    }).catch(() => {});
  },
  unmounted() {
    if (WB.shell) WB.shell.setSubs([]);
    if (this.genTimer) { clearInterval(this.genTimer); this.genTimer = null; }
  },

  template: `
  <div>
    <!-- ═══ 子页1: 推荐信息(全 X · 互动数据 · 五选排序 · 选素材视角) ═══ -->
    <div v-show="tab==='reco'">
            <div class="feed-toolbar">
        <select v-model="xfReco.since" @change="loadXF('xfReco')">
          <option v-for="[v, t] in sinceOpts" :key="v" :value="v">{{ t }}</option>
        </select>
        <div class="radio-group">
          <label v-for="[v, t] in sortOpts" :key="v">
            <input type="radio" :value="v" v-model="xfReco.sort" @change="loadXF('xfReco')"> {{ t }}</label>
        </div>
        <span style="flex:1"></span>
        <button class="btn" @click="loadXF('xfReco')">{{ xfReco.loading ? '刷新中…' : '刷新' }}</button>
      </div>
            <div class="card reco-filter">
        <div class="frow">
          <span class="lab">市场</span>
          <span v-for="m in xMarketChips" :key="m" class="chip" :class="{on: xfReco.markets.includes(m)}"
                @click="xfToggleChip('xfReco', 'markets', m)">{{ m }}</span>
        </div>
        <div class="frow">
          <span class="lab">赛道</span>
          <span v-for="[sl, n] in (xfReco.meta.sectors_l1 || [])" :key="sl" class="chip"
                :class="{on: xfReco.sectors.includes(sl)}" @click="xfToggleChip('xfReco', 'sectors', sl)">
            {{ sl }}<template v-if="n"> {{ n }}</template></span>
          <span v-if="!((xfReco.meta.sectors_l1 || []).length)" class="muted">窗口内暂无赛道打标</span>
        </div>
        <div class="frow">
          <span class="lab">条件</span>
          <span class="chip" :class="{on: xfReco.golden}" @click="xfToggleFlag('xfReco', 'golden')">仅黄金窗口(≤2h)</span>
          <span class="chip" :class="{on: xfReco.bigOnly}" @click="xfToggleFlag('xfReco', 'bigOnly')">粉丝≥10万</span>
          <span class="chip" :class="{on: xfReco.finance}" @click="xfToggleFlag('xfReco', 'finance')">仅投资金融</span>
          <span v-if="xfReco.meta.sector_unlabeled_n" class="muted" style="font-size:11px">
            赛道未打标 {{xfReco.meta.sector_unlabeled_n}} 条不参与赛道筛选</span>
        </div>
      </div>
            <p class="surge-meta">
        <template v-if="xfReco.meta.updated_at">快照 {{xfReco.meta.updated_at}} ·
          {{xfReco.meta.data_age_min}} 分钟前 · 在跟踪 {{xfReco.meta.tracked}} 帖 · X 条目 {{xfReco.total}}</template>
        <template v-else>暂无快照</template>
        <span v-if="xfReco.meta.err" class="badge red" style="margin-left:8px">{{ xfReco.meta.err }}</span>
        <span v-if="xfReco.meta.data_age_min > 90" class="badge yellow" style="margin-left:8px">
          数据偏旧 —— 跑 python cli.py workbench refresh-x-surge</span>
        <span class="muted" style="margin-left:8px">{{ xfReco.meta.rule }}</span>
      </p>
      <div v-if="!xfReco.items.length && !xfReco.loading" class="empty">
        窗口内暂无 X 内容 —— 放宽时间范围, 或先跑 sources refresh + refresh-x-surge</div>
      <p v-if="xfReco.sort === 'fv' && xfReco.items.length" class="surge-meta">
        <label style="cursor:pointer"><input type="checkbox" v-model="hideP3"> 隐藏低值(P3 归档)</label>
      </p>
      <div class="feed">
        <template v-for="g in recoGroups" :key="g.key">
          <div v-if="g.label" class="group-head">
            <span class="badge" :class="g.cls">{{ g.label }}</span>
            <span class="muted">{{ g.items.length }} 条</span>
          </div>
          <div v-for="r in g.items" :key="r.status_id" class="news-card"
               :class="{ 'tier-p0': g.key === 'p0', 'tier-p1': g.key === 'p1', 'p3-dim': r.fv_tier === 'P3' }">
          <div class="surge-grid">
            <!-- 左: 金融价值分 + P档(悬浮看六维明细) -->
            <div class="surge-rank">
              <div class="prob">{{ r.fv_score }}<span>分</span></div>
              <div class="prob-lab">金融价值</div>
              <div class="prob growth" :title="r.growth_views_h != null ? '浏览增速 ' + fmtN(r.growth_views_h) + '/时' : '增速基线攒集中'">
                {{ r.growth_views_h != null ? fmtN(r.growth_views_h) : '—' }}<span v-if="r.growth_views_h != null">/时</span></div>
              <div class="prob-lab">增速</div>
              <span class="badge" :class="tierBadge(r.fv_tier)" :title="fvTitle(r)">{{ r.fv_tier }}</span>
              <span v-if="r.golden" class="badge golden" style="margin-top:4px">黄金窗口</span>
            </div>
            <!-- 右: 帖子(译文优先, 悬停看原文) + 标签行(对齐资讯页双标签制) -->
            <div class="surge-body">
              <div class="surge-top">
                <span class="rank-no">#{{ r.rank }}</span>
                <b>{{ r.name }}</b>
                <span class="muted">@{{ r.handle }}</span>
                <span v-if="r.positioning" class="badge blue">{{ r.positioning }}</span>
                <span v-if="r.followers" class="xhot-fol">粉 {{ fmtFol(r.followers) }}</span>
                <span class="muted" style="margin-left:auto">{{ r.time }}</span>
              </div>
              <div class="nc-badges" style="margin-bottom:0">
                <span v-for="m in r.markets" :key="m" class="badge">{{ m }}</span>
                <template v-for="sec in visibleSectors(r)" :key="sec">
                  <span class="badge yellow" :title="sec">{{ sectorParts(sec)[0] }}</span>
                  <span v-if="sectorParts(sec)[1]" class="badge" :title="sec">{{ sectorParts(sec)[1] }}</span>
                </template>
                <span v-if="sectorsRest(r)" class="badge" :title="(r.sectors || []).join('\\n')">+{{ sectorsRest(r) }}</span>
                <span v-if="r.event_type" class="badge">{{ r.event_type }}</span>
                <span v-if="r.sentiment" class="badge" :class="sentimentBadge(r.sentiment)">{{ sentimentText(r.sentiment) }}</span>
                <span v-for="t in r.tickers" :key="t" class="badge">{{ t }}</span>
                <span v-if="r.dup_count > 1" class="badge yellow">同事件 ×{{ r.dup_count }}</span>
              </div>
              <a class="xhot-text" :href="r.reply_url" target="_blank" rel="noopener"
                 :ref="el => trRef(el, r)"
                 :title="r.text_zh ? '原文: ' + r.text : ''">{{ dispText(r) }}</a>
              <div class="surge-stats">
                <span>👍 {{ fmtN(r.likes) }}</span>
                <span>🔁 {{ fmtN(r.retweets) }}</span>
                <span>💬 {{ fmtN(r.replies) }}</span>
                <span>👁 {{ fmtN(r.views) }}</span>
              </div>
              <div class="surge-parts muted">
                参考: <template v-if="r.views_pred != null">预测浏览 {{ fmtN(r.views_pred) }}</template><template v-if="r.reply_exposure != null"> · 评论可蹭 ~{{ fmtN(r.reply_exposure) }} 曝光</template> · {{ r.age_h }}h 前</div>
              <div class="news-actions">
                <a :href="r.reply_url" target="_blank" rel="noopener">去评论 ↗</a>
                <span class="act" @click="xfCopy(r)">一键复制</span>
                <span v-if="basketIds[r.status_id]" class="act-done">已加入 ✓</span>
                <span v-else class="act" @click="addXToPool(r)">＋加入素材</span>
              </div>
            </div>
          </div>
        </div>
        </template>
      </div>
    </div>

    <!-- ═══ 子页: 蹭蹭流量(SoPilot 热帖 RSS · 评论卡位) ═══ -->
    <div v-show="tab==='surge'">
      <div class="feed-toolbar">
        <div class="radio-group">
          <label v-for="[v, t] in rssSortOpts" :key="v">
            <input type="radio" :value="v" v-model="xfSurge.sort" @change="loadSurgeRss()"> {{ t }}</label>
        </div>
        <span class="muted">数据源: SoPilot 今日热帖公开 RSS(非本站数据站)</span>
        <span style="flex:1"></span>
        <button class="btn" @click="loadSurgeRss()">{{ xfSurge.loading ? '刷新中…' : '刷新' }}</button>
      </div>
      <p class="surge-meta">
        <template v-if="xfSurge.meta.updated_at">RSS 抓取 {{ xfSurge.meta.updated_at }} ·
          在榜 {{ xfSurge.total }} 帖(48h 保留)</template>
        <template v-else>暂无数据 —— 跑一轮 python cli.py workbench refresh-x-surge</template>
        <span class="muted" style="margin-left:8px">{{ xfSurge.meta.rule }}</span>
      </p>
      <div v-if="!xfSurge.items.length && !xfSurge.loading" class="empty">
        暂无数据 —— 跑一轮 python cli.py workbench refresh-x-surge(RSS 每 30 分钟随任务计划自动更新)</div>
      <div class="feed">
        <div v-for="(r, i) in xfSurge.items" :key="r.status_id" class="news-card">
          <div class="surge-grid">
            <div class="surge-rank">
              <div class="prob">{{ r.prob == null ? '—' : r.prob }}<span>%</span></div>
              <div class="prob-lab">爆火概率</div>
            </div>
            <div class="surge-body">
              <div class="surge-top">
                <span class="rank-no">#{{ i + 1 }}</span>
                <b>{{ r.name }}</b>
                <span class="muted">@{{ r.handle }}</span>
                <span class="muted" style="margin-left:auto">{{ r.time }}</span>
              </div>
              <a class="xhot-text" :href="r.reply_url" target="_blank" rel="noopener"
                 :ref="el => trRef(el, r)"
                 :title="r.text_zh ? '原文: ' + r.text : ''">{{ dispText(r) }}</a>
              <div class="surge-stats">
                <span>👍 {{ fmtN(r.likes) }}</span>
                <span>🔁 {{ fmtN(r.retweets) }}</span>
                <span>💬 {{ fmtN(r.replies) }}</span>
                <span>🔖 {{ fmtN(r.bookmarks) }}</span>
                <span>👁 {{ fmtN(r.views) }}</span>
                <span v-if="r.views_pred != null">预测浏览 {{ fmtN(r.views_pred) }}</span>
                <span v-if="r.exposure != null" class="exposure">评论可蹭 ~{{ fmtN(r.exposure) }} 曝光</span>
              </div>
              <div class="news-actions">
                <a :href="r.reply_url" target="_blank" rel="noopener">去评论 ↗</a>
                <span class="act" @click="xfCopy(r)">一键复制</span>
                <span v-if="basketIds[r.status_id]" class="act-done">已加入 ✓</span>
                <span v-else class="act" @click="addXToPool(r)">＋加入素材</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ 子页2: 内容生成(素材池勾选 + 模块排列组合 + 固定模板 + 实时编辑) ═══ -->
    <div v-show="tab==='gen'" class="three-col gen-cols">
      <!-- 左: 素材池(顶部小搜索 + 上下滚动 + 勾选参与生成 + 时效灰显) -->
      <div>
        <div class="card">
          <h3>素材池({{ materials.length }}<template v-if="selCount !== materials.length"> · 已选 {{ selCount }}</template>)</h3>
          <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">
            <button class="btn" :disabled="calendarLoading" @click="loadCalendar('calendar')">拉财经日历</button>
            <button class="btn" :disabled="calendarLoading" @click="loadCalendar('nasdaq_earnings')">拉美股财报日历</button>
            <button class="btn" @click="manualForm.show = !manualForm.show">
              {{ manualForm.show ? '收起录入' : '＋手动录入' }}</button>
          </div>
          <!-- 手动录入: 用户自己找到的信息(研报摘录/群聊截图文字/外文原文)直接进素材池 -->
          <div v-if="manualForm.show" class="manual-form" style="border:1px solid var(--border);border-radius:8px;padding:8px;margin-bottom:8px;display:flex;flex-direction:column;gap:6px">
            <input type="text" v-model="manualForm.title" maxlength="60"
                   placeholder="标题(选填, 缺省取正文首行前30字)">
            <textarea v-model="manualForm.text" rows="5" maxlength="2000"
                      placeholder="粘贴正文(必填, 20-2000 字; 链接会被当场剥除, 出处请填下方来源标注)"></textarea>
            <div style="display:flex;gap:6px;flex-wrap:wrap">
              <input type="datetime-local" v-model="manualForm.time" title="发布时间(选填, 缺省=现在)" style="flex:1;min-width:150px">
              <input type="text" v-model="manualForm.source" placeholder="来源标注(选填): 如 高盛研报 / 群聊 / 路透" style="flex:2;min-width:180px">
            </div>
            <div class="muted" style="font-size:12px">{{ (manualForm.text || '').length }} / 2000 字 · 手动素材由你担保事实性, LLM 不会虚构出处</div>
            <button class="btn primary" :disabled="(manualForm.text || '').trim().length < 20" @click="addManual">加入素材池</button>
          </div>
          <input type="text" v-model="matQ" class="mat-search" placeholder="搜索素材(正文/来源)">
          <div v-if="!materials.length" class="muted">
            空 —— 点上方「＋手动录入」粘贴自己的内容, 或到「推荐信息」点「＋加入生成」, 或资讯页点「＋加入素材篮」</div>
          <div v-else-if="!filteredMaterials.length" class="muted">无匹配 —— 换个关键词</div>
          <div class="mat-pool">
            <div v-for="m in filteredMaterials" :key="m.id" class="list-item"
                 :class="{sel: matChecked(m), stale: isStale(m)}">
              <div class="t">
                <label style="display:flex;align-items:flex-start;gap:6px;cursor:pointer">
                  <input type="checkbox" :checked="matChecked(m)" @change="toggleMatSel(m)"
                         style="margin-top:3px;flex:none">
                  <span>{{ m.text || '(无标题)' }}</span></label>
              </div>
              <div class="s"><span :title="m.time">{{ ageText(m) }}</span><span v-if="isStale(m)"> · 超48h</span>
                · <span v-if="String(m.id).startsWith('manual-')" class="badge blue" title="手动录入素材">手</span>{{ m.source }}
                <a style="float:right" @click.stop="removeMaterial(m.id)">移除</a></div>
              <div v-if="retrieveRes[m.id]" class="rv-block">
                <a class="rv-toggle" @click="toggleRv(m.id)">
                  {{ rvOpen[m.id] ? '▾ 收起补充信息' : '▸ 补充信息' }}
                  {{ ((retrieveRes[m.id].related || []).length + (retrieveRes[m.id].hydrated ? 1 : 0)) || '' }}
                </a>
                <div v-if="rvOpen[m.id]" class="rv-list">
                  <div v-if="retrieveRes[m.id].hydrated" class="rv-item">
                    <span class="badge blue">原文全文</span>
                    <span class="muted" style="margin-left:6px">{{ retrieveRes[m.id].hydrated.source }} ·
                      {{ retrieveRes[m.id].hydrated.time }}</span>
                    <div class="rv-full">{{ retrieveRes[m.id].hydrated.full }}</div>
                    <div style="margin-top:4px">
                      <a @click="mergeAnchor(m)">并入原文</a>
                      <a v-if="retrieveRes[m.id].hydrated.url" :href="retrieveRes[m.id].hydrated.url"
                         target="_blank" rel="noopener" style="margin-left:10px">打开 ↗</a></div>
                  </div>
                  <div v-for="h in retrieveRes[m.id].related" :key="h.id" class="rv-item">
                    <span v-for="w in h.why" :key="w" class="badge blue" style="margin-right:4px">{{ w }}</span>
                    <span class="muted">{{ h.source }} · {{ h.time }}</span>
                    <div class="rv-text">{{ h.title ? h.title + ' —— ' : '' }}{{ h.text }}</div>
                    <div style="margin-top:4px">
                      <a @click="mergeHit(h)">并入</a>
                      <a v-if="h.url" :href="h.url" target="_blank" rel="noopener" style="margin-left:10px">原文 ↗</a></div>
                  </div>
                  <div v-if="!(retrieveRes[m.id].related || []).length && !retrieveRes[m.id].hydrated"
                       class="muted">{{ retrieveRes[m.id].hint || '窗口内未检到补充信息' }}</div>
                </div>
              </div>
            </div>
          </div>
          <div class="muted" style="margin-top:8px">勾选参与生成(存草稿只记勾选项); 超 48h 灰显提醒</div>
        </div>
      </div>

      <!-- 中: 生成模块排列组合 + 固定模板 + 实时编辑画布 -->
      <div>
        <div class="card">
          <h3>生成模块(勾选 + 排列组合)</h3>
          <div v-for="(m, i) in modules" :key="m.id" class="list-item" :class="{sel: m.on}">
            <div class="t">
              <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
                <input type="checkbox" v-model="m.on">{{ m.title }}</label>
              <button v-if="m.id === 'retrieve'" class="btn" style="margin-left:auto;padding:2px 10px"
                      :disabled="retrieving" @click="runRetrieve">{{ retrieving ? '检索中…' : '执行检索' }}</button>
              <span>
                <a @click="moveModule(i, -1)" :style="{opacity: i===0 ? .3 : 1}">↑</a>
                <a @click="moveModule(i, 1)" style="margin-left:8px"
                   :style="{opacity: i===modules.length-1 ? .3 : 1}">↓</a>
              </span>
            </div>
            <div class="s">{{ m.desc }}</div>
          </div>
          <div class="muted" style="margin-top:8px">执行顺序: {{ moduleTitles(onModules) || '(未启用模块)' }}</div>
          <div class="form-row" style="margin-top:12px">
            <label>平台风格</label>
            <select v-model="genParams.platform" style="width:280px">
              <option value="x">X(Twitter) 财经帖(默认)</option>
            </select>
          </div>
          <div class="form-row">
            <label>语种</label>
            <select v-model="genParams.lang" style="width:280px">
              <option v-for="[v, t] in genLangs" :key="v" :value="v">{{ t }}</option>
            </select>
          </div>
          <div class="form-row">
            <label>账号类型</label>
            <select v-model="genParams.tier" style="width:280px">
              <option v-for="[v, t] in genTiers" :key="v" :value="v">{{ t }}</option>
            </select>
          </div>
          <div class="form-row">
            <label>成稿模板</label>
            <select v-model="genParams.template" style="width:280px">
              <optgroup label="分析类(带观点)">
                <option v-for="t in genTpls.filter(x => !x.zero)" :key="t.v" :value="t.v">{{ t.t }}</option>
              </optgroup>
              <optgroup label="信息披露类(零观点)">
                <option v-for="t in genTpls.filter(x => x.zero)" :key="t.v" :value="t.v">{{ t.t }}</option>
              </optgroup>
            </select>
          </div>
          <div v-if="tplSuggestion && tplSuggestion.template !== genParams.template" class="muted" style="margin:8px 0">
            识别到{{ tplSuggestion.event }}类素材, 建议模板:{{ templateTitle(tplSuggestion.template) }}
            <button class="btn" @click="applyTplSuggestion">一键切换</button>
            <button class="btn" @click="tplSuggestion = null">忽略</button>
          </div>
          <div class="muted" style="margin-top:4px">
            模板 = 信息结构, 长短由账号类型决定(免费档只留 Hook+核心事实, 付费档骨架全开);
            披露类(零观点)模板禁观点标记(后端硬剔); 快照抓取/技术分析需素材带标的(未识别自动跳过并注明);
            聚合分析汇 X 大V+机构观点, 设置页「Finnhub」卡可再叠加投行评级与目标价</div>
        </div>

        <div class="card">
          <h3>实时编辑 <span class="muted">{{ editingId ? '草稿 ' + editingId : '新草稿' }}</span></h3>
          <div class="form-row">
            <label>标题</label>
            <input type="text" v-model="editorTitle" placeholder="标题(成稿首行自动带入)" style="width:100%;max-width:420px">
          </div>
          <textarea v-model="editorContent" rows="14"
                    placeholder="正文(开始生成后成稿在此, 可直接改)…" style="width:100%"></textarea>
          <div class="muted" style="margin-top:6px">
            加权 {{ xwCount }} / {{ xwLimit }} 字符(X 规则: CJK×2 · URL=23) · 原始 {{ wordCount }} 字符
            <span v-if="xwCount > xwLimit" class="badge red" style="margin-left:6px">超上限</span>
          </div>
          <div style="margin-top:10px">
            <button class="btn primary" :disabled="!canGenerate" @click="startGen">
              {{ genJob.running ? '生成中… ' + (genJob.progress.pct || 0) + '%' : '开始生成' }}</button>
            <button class="btn" @click="saveDraft">存草稿</button>
            <button class="btn" v-if="editingId" @click="newDraft">新建</button>
            <div class="muted" v-if="genJob.running" style="margin-top:6px">
              {{ genJob.progress.message || genJob.progress.stage }}</div>
            <div v-if="genJob.error" style="margin-top:6px">
              <span class="badge red">{{ genJob.error }}</span>
              <span class="muted">{{ genJob.hint }}</span></div>
          </div>
          <!-- 成稿: 文字在上方编辑器可直接改; 此处是配图/标签/一键复制 -->
          <div v-if="genResult" class="gen-final">
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
              <b>成稿</b>
              <span class="muted">{{ genResult.created_at }} · 加权 {{ genResult.weighted_len }}/{{ genResult.limit }}
                · {{ moduleTitles(genResult.modules) || '纯素材' }}</span>
              <span style="flex:1"></span>
              <button class="btn primary" @click="copyGenAll">复制图文</button>
              <button class="btn" @click="copyGenText">{{ (genResult.thread || []).length ? '复制全部' : '复制文字' }}</button>
              <button class="btn" :disabled="genDownloading" @click="copyGenAndDownload">复制文字+下载全部图</button>
            </div>
            <ol v-if="(genResult.thread || []).length" style="list-style:none;padding:0">
              <li v-for="(tweet, i) in genResult.thread" :key="i" class="list-item">
                <div style="white-space:pre-wrap;overflow-wrap:anywhere">{{ tweet }}</div>
                <span class="muted">计权 {{ xwLen(tweet) }}/{{ genResult.limit }}</span>
                <button class="btn" @click="copyTweet(tweet)">复制本条</button>
              </li>
            </ol>
            <div v-if="(genResult.tags || []).length" style="margin:8px 0">
              <span v-for="t in genResult.tags" :key="t" class="badge blue"
                    style="margin-right:6px">{{ t }}</span>
            </div>
            <div v-for="img in genResult.images" :key="img.file" class="gen-asset">
              <img :src="img.url" :alt="img.ticker">
              <div class="s" style="margin-top:4px">
                <span class="muted">{{ img.ticker }} 近3月日线(绿=支撑 红=阻力 · 源 {{ img.via }})</span>
                <a @click="copyGenImage(img)">复制图片</a>
                <a :href="img.url" :download="img.file" @click.prevent="downloadGenImage(img)" style="margin-left:10px">下载</a>
              </div>
            </div>
            <div v-if="(genResult.notes || []).length" class="muted" style="margin-top:8px">
              <div v-for="n in genResult.notes" :key="n">· {{ n }}</div>
            </div>
            <div class="muted" style="margin-top:8px">复制后到 X 发布页粘贴: 先贴文字, 再用「复制图片」补图</div>
          </div>
        </div>
        <div class="card">
          <h3>生成历史 <span class="muted">保留最新 50 篇</span></h3>
          <div v-if="historyLoading" class="muted">加载中…</div>
          <div v-else-if="!genHistory.length" class="muted">暂无生成历史</div>
          <div v-for="post in genHistory" :key="post.id" class="list-item">
            <div>{{ post.summary || '(无正文)' }}</div>
            <div class="muted">{{ post.created_at }} · {{ templateTitle(post.params.template) }}
              · {{ post.params.tier === 'paid' ? '付费' : '免费' }} · 计权 {{ post.weighted_len }} · {{ post.image_count }} 图</div>
            <button class="btn" @click="loadGenPost(post)">载入编辑器</button>
            <button class="btn" @click="deleteGenPost(post)">删除</button>
          </div>
        </div>
      </div>

      <!-- 右: 草稿箱 + 历史记录(原左栏, 挪到草稿下方) -->
      <div>
        <div class="card">
          <h3>草稿({{ drafts.length }})</h3>
          <div v-if="!drafts.length" class="muted">暂无草稿</div>
          <div v-for="d in drafts" :key="d.id" class="list-item" :class="{sel: editingId === d.id}">
            <div class="t">{{ d.title }}</div>
            <div class="s">{{ d.updated_at }} · {{ (d.content || '').length }} 字</div>
            <div class="s" style="margin-top:4px">
              <a @click="editDraft(d)">载入编辑</a>
              <a style="margin-left:10px" @click="pubDraftId = d.id; go('pub')">去发布</a>
              <a style="margin-left:10px" @click="delDraft(d)">删除</a>
            </div>
          </div>
        </div>
        <div class="card">
          <h3>历史记录(生成运行)</h3>
          <div v-if="!runs.length" class="muted">暂无(data/runs/)</div>
          <div v-for="r in runs.slice(0, 6)" :key="r.flow + r.date" class="list-item">
            <div class="t">{{ r.flow }} @ {{ r.date }}
              <span class="badge" :class="r.status === 'done' ? 'green' : 'yellow'"
                    style="float:right">{{ r.status }}</span></div>
            <div class="s">{{ r.mtime }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ 子页3: 内容发布(草稿 + 发布面板 + 发布记录) ═══ -->
    <div v-show="tab==='pub'">
      <div class="card">
        <h3>草稿箱(点击「继续编辑」回内容生成页)</h3>
        <div v-if="!drafts.length" class="muted">暂无草稿 —— 到「内容生成」存一篇</div>
        <table v-else class="tbl">
          <thead><tr><th>标题</th><th>更新时间</th><th>字数</th><th>模块</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="d in drafts" :key="d.id" :style="{background: pubDraftId===d.id ? 'var(--accent-weak)' : ''}">
              <td>{{ d.title }}</td>
              <td>{{ d.updated_at }}</td>
              <td>{{ (d.content || '').length }}</td>
              <td class="muted">{{ moduleTitles(d.modules) }}</td>
              <td>
                <a @click="editDraft(d)">继续编辑</a>
                <a style="margin-left:10px" @click="pickPubDraft(d)">选择发布</a>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card" v-if="pubDraft">
        <h3>发布设置 —— {{ pubDraft.title }}</h3>
        <div class="form-row">
          <label>发布时间</label>
          <div class="radio-group">
            <label><input type="radio" value="now" v-model="pubWhen"> 立即</label>
            <label><input type="radio" value="schedule" v-model="pubWhen"> 定时</label>
          </div>
          <input v-if="pubWhen === 'schedule'" type="datetime-local" v-model="pubTime">
        </div>
        <div class="form-row" style="align-items:flex-start">
          <label>发布账号</label>
          <div v-if="!accounts.length" class="muted">追踪页还没加账号 —— 先去「追踪」添加平台账号</div>
          <label v-for="a in accounts" :key="a.platform + a.account"
                 style="display:inline-flex;align-items:center;gap:5px;margin-right:14px;cursor:pointer">
            <input type="checkbox" :checked="hasPubAccount(a)" @change="togglePubAccount(a)">
            {{ a.platform }} · {{ a.account }}</label>
        </div>
        <div class="form-row">
          <label>发布方式</label>
          <div class="radio-group">
            <label><input type="radio" value="xai" v-model="pubMethod"> XAI(API 通道)</label>
            <label><input type="radio" value="bit" v-model="pubMethod"> Bit 浏览器(自动化)</label>
          </div>
        </div>
        <div class="stub-wrap">
          <button class="btn primary stub" disabled>确认发布</button>
          <button class="btn" @click="saveDraft">保存发布偏好到草稿</button>
          <div class="stub-tip">红线: 真发必须先 <code>python cli.py publish run --draft</code> 验证,
            用户确认后才去掉 --draft; XAI / Bit 两种方式本期均留桩</div>
        </div>
      </div>

      <div class="card">
        <h3>发布记录 <span class="muted">账本 {{ ledger.stats.records || 0 }} 条 ·
          成功 {{ ledger.stats.published || 0 }} · 失败 {{ ledger.stats.failed || 0 }}</span></h3>
        <div v-if="!ledger.rows.length" class="muted">暂无(autopub/state.json)</div>
        <table v-else class="tbl">
          <thead><tr><th>时间</th><th>平台</th><th>文章</th><th>状态</th><th>链接</th></tr></thead>
          <tbody>
            <tr v-for="r in ledger.rows.slice(0, 30)" :key="r.time + r.platform + r.article">
              <td class="mono">{{ r.time }}</td>
              <td>{{ r.platform }}</td>
              <td>{{ r.article }}</td>
              <td><span class="badge" :class="r.status === 'published' ? 'green' :
                    r.status === 'failed' ? 'red' : 'yellow'">{{ r.status }}</span></td>
              <td><a v-if="r.url" :href="r.url" target="_blank" rel="noopener">打开 ↗</a>
                  <span v-else class="muted">-</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ═══ 子页4: 自动化任务(建立任务 → 建立工作流 → 选择时间 → 内容发布) ═══ -->
    <div v-show="tab==='auto'" class="two-col">
      <div>
        <div class="card">
          <h3>任务列表({{ tasks.length }})</h3>
          <div v-if="!tasks.length" class="muted">暂无 —— 右侧建立第一个定时任务</div>
          <div v-for="t in tasks" :key="t.id" class="list-item">
            <div class="t">{{ t.name }}
              <span class="badge" :class="t.enabled ? 'green' : ''" style="float:right">
                {{ t.enabled ? '启用' : '停用' }}</span></div>
            <div class="s">{{ scheduleText(t) }} · {{ t.template || '无模板' }}</div>
            <div class="s">{{ moduleTitles(t.modules) }}</div>
            <div class="s" v-if="t.note">{{ t.note }}</div>
            <div class="s" style="margin-top:4px"><a @click="delTask(t)">删除</a></div>
          </div>
          <p class="muted" style="margin-top:10px">调度器本期留桩: 任务定义已真实保存,
            到点执行未来接 Windows 任务计划(对齐 bin/refresh_task.bat 模式)</p>
        </div>
      </div>
      <div>
        <div class="card">
          <h3>建立定时任务</h3>
          <div class="step-line"><span class="badge blue">1</span> <b>建立任务</b></div>
          <div class="form-row"><label>任务名称</label>
            <input type="text" v-model="autoForm.name" placeholder="如: 每日早盘速递"></div>
          <div class="form-row"><label>备注</label>
            <input type="text" v-model="autoForm.note" placeholder="可选"></div>

          <div class="step-line" style="margin-top:14px"><span class="badge blue">2</span> <b>建立工作流</b></div>
          <div class="form-row"><label>固定模板</label>
            <select v-model="autoForm.template" style="width:240px">
              <option value="">(不使用模板)</option>
              <option v-for="fl in flows" :value="fl.name">{{ fl.name }} — {{ fl.title }}</option>
            </select></div>
          <div class="form-row" style="align-items:flex-start"><label>生成模块</label>
            <label v-for="m in modules" :key="m.id"
                   style="display:inline-flex;align-items:center;gap:5px;margin-right:12px;cursor:pointer">
              <input type="checkbox" :checked="autoModules.includes(m.id)"
                     @change="autoModuleToggle(m.id)">{{ m.title }}</label></div>
          <div class="form-row"><label></label>
            <button class="btn" @click="copyFromGen">从内容生成页复制当前配置</button></div>

          <div class="step-line" style="margin-top:14px"><span class="badge blue">3</span> <b>选择时间</b></div>
          <div class="form-row"><label>频率</label>
            <div class="radio-group">
              <label><input type="radio" value="daily" v-model="autoForm.scheduleKind"> 每天</label>
              <label><input type="radio" value="workday" v-model="autoForm.scheduleKind"> 工作日</label>
              <label><input type="radio" value="weekly" v-model="autoForm.scheduleKind"> 每周</label>
            </div></div>
          <div class="form-row" v-if="autoForm.scheduleKind === 'weekly'"><label>星期</label>
            <select v-model="autoForm.weekday">
              <option :value="1">周一</option><option :value="2">周二</option>
              <option :value="3">周三</option><option :value="4">周四</option>
              <option :value="5">周五</option><option :value="6">周六</option>
              <option :value="0">周日</option>
            </select></div>
          <div class="form-row"><label>时刻</label>
            <input type="time" v-model="autoForm.time"></div>

          <div class="step-line" style="margin-top:14px"><span class="badge blue">4</span> <b>内容发布</b></div>
          <div class="form-row"><label>产物去向</label>
            <div class="radio-group">
              <label><input type="radio" value="draft" v-model="autoForm.target"> 只存草稿</label>
              <label><input type="radio" value="queue" v-model="autoForm.target"> 推入待发队列(桩)</label>
              <label><input type="radio" value="direct" v-model="autoForm.target"> 按配置发布(桩)</label>
            </div></div>

          <div style="margin-top:16px">
            <button class="btn primary" @click="saveTask">保存任务</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ 子页5: 账号管理(全 X 池账号信息来源; 池只读, 关注/备注为板块四自有偏好) ═══ -->
    <div v-show="tab==='xaccts'">
      <div class="card">
        <h3>X 账号池({{ xaccts.meta.count || 0 }})
          <span class="muted">关注 {{ xaccts.meta.followed_n || 0 }} ·
            停用 {{ xaccts.meta.disabled_n || 0 }} · 显示 {{ xacctRows.length }}</span>
          <span v-if="xaccts.meta.err" class="badge red" style="margin-left:8px">{{ xaccts.meta.err }}</span></h3>
        <div class="feed-toolbar">
          <input type="text" v-model="xaccts.q" class="mat-search" placeholder="搜索(名称/handle/市场)" style="width:220px">
          <span class="chip" :class="{on: !xaccts.pos}" @click="xaccts.pos=''">全部</span>
          <span v-for="p in tagEnums.positionings" :key="p" class="chip"
                :class="{on: xaccts.pos === p}" @click="xaccts.pos = xaccts.pos === p ? '' : p">{{ p }}</span>
          <span class="chip" :class="{on: xaccts.followOnly}" @click="xaccts.followOnly=!xaccts.followOnly">★ 仅看关注</span>
          <span style="flex:1"></span>
          <button class="btn" @click="loadXaccts">{{ xaccts.loading ? '刷新中…' : '刷新' }}</button>
        </div>
        <div class="muted" style="margin:6px 0 10px">
          池数据来自板块一 twitter_pool.yaml(只读): 启停/角色/市场改池文件或 local 覆盖后点刷新;
          关注与备注是本板块自有偏好, 只存 data/workbench/。</div>
        <table class="tbl">
          <thead><tr><th>账号</th><th>市场</th><th>定位</th><th>标签</th><th>粉丝</th><th>状态</th><th>关注</th><th>备注</th></tr></thead>
          <tbody>
            <tr v-for="a in xacctRows" :key="a.handle"
                :style="{background: a.follow ? 'var(--accent-weak)' : ''}">
              <td>
                <a :href="a.homepage" target="_blank" rel="noopener"><b>{{ a.name || '@'+a.handle }}</b></a>
                <span v-if="a.verified" class="badge blue" title="X 认证账号" style="margin-left:4px">✓</span>
                <div class="muted" style="font-size:11px">@{{ a.handle }}<template v-if="a.bio"> · {{ a.bio }}</template></div>
              </td>
              <td><span v-for="m in a.markets" :key="m" class="badge" style="margin-right:4px">{{ m }}</span></td>
              <td><span v-if="a.positioning" class="badge blue">{{ a.positioning }}</span>
                <div class="muted" style="font-size:11px" v-if="a.role">{{ a.role }}</div></td>
              <td><span v-if="a.tier" class="badge yellow">{{ a.tier }}</span>
                <span v-if="a.priority" class="badge" style="margin-left:4px">{{ a.priority }}</span>
                <div class="muted" style="font-size:11px" v-if="a.note" :title="a.note">{{ a.note.slice(0, 24) }}</div></td>
              <td class="mono">{{ a.followers ? fmtFol(a.followers) : '—' }}</td>
              <td><span class="badge" :class="a.enabled ? 'green' : 'red'">{{ a.enabled ? '启用' : '停用' }}</span></td>
              <td><span class="act" :style="{color: a.follow ? 'var(--yellow)' : ''}"
                    @click="toggleXFollow(a)">{{ a.follow ? '★ 已关注' : '☆ 关注' }}</span></td>
              <td><input type="text" v-model="a.local_note" @change="saveXNote(a)" placeholder="本地备注"
                         style="width:150px;font-size:11.5px"></td>
            </tr>
            <tr v-if="!xacctRows.length && !xaccts.loading">
              <td colspan="8" class="muted">无匹配账号</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>`,
};
