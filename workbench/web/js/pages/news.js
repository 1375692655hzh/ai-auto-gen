/* 资讯页: 大页内双子页(信息筛选 / 来源详情)
   信息筛选 = 标签筛选(双标签制: 市场/定位/类型/赛道L1/情绪) + 信息流 + 统计右栏(同事看板式);
   来源详情 = /stats 来源注册表(前端搜索+排序), 「筛选」跳回信息筛选。
   数据全部来自 workbench 代理的 /wb-api/* → sources serve;
   统计来自 /stats(服务端聚合, 60s 缓存), 右栏与来源详情共用一份。
   2026-09-03 对齐 commit 0188415 双标签制(taxonomy.py 单一真相):
   卡片改【来源信息】+【内容信息】双框, 源级标签(定位/市场/简介)与条目级标签(类型/赛道/情绪/标的)分区独立。 */
window.WB = window.WB || {};
WB.pages = WB.pages || {};

WB.pages.news = {
  data() {
    return {
      /* 子页: feed=信息筛选, sources=来源详情 */
      tab: "feed",
      /* 筛选枚举: 市场从 /v1/sources 聚合(新 8 值); 定位/类型/赛道/情绪为封闭枚举
         (对齐 taxonomy.py, commit 0188415; 值域封闭, 前端硬编码) */
      dict: { markets: [], sources: [], sectorsTop: [] },
      enums: {
        item_types: ["聚合", "快讯", "资讯", "分析"],
        sentiments: [["bull", "利好"], ["bear", "利空"], ["neutral", "中性"]],
        positionings: ["官方", "机构", "大V", "快讯源", "新闻源"],
        /* L1 19 值, 键序对齐 taxonomy.py L1_L2 */
        sectors_l1: ["宏观与政策", "半导体", "AI与算力", "互联网与传媒", "消费电子",
                     "通信与卫星", "汽车与智能驾驶", "新能源与电力", "油气与能源",
                     "金属与矿业", "化工与新材料", "医药生物", "金融与加密", "地产与基建",
                     "消费", "军工与航空航天", "工业与机器人", "交通运输", "农业与食品"],
      },
      /* sources 保留: 来源详情页与右栏条形图会写入, 仅 UI 不再提供多选框;
         sectors 为客户端过滤(serve 无 sectors 参数, 全库过滤属板块一 follow-up) */
      f: { markets: [], positionings: [], item_types: [], sentiments: [],
           sectors: [], sources: [], q: "", tickers: "",
           since: "24h", dedup: true, display: true },
      showAllSectors: false,
      sinceOpts: [["1h", "近1小时"], ["4h", "近4小时"], ["24h", "近24小时"], ["3d", "近3天"], ["", "全部"]],
      items: [], total: 0, nextCursor: "", loading: false, error: null,
      expanded: {}, bodyExpanded: {},
      /* X 池账号档案(按账号展示): xAccounts=池录入信息, xProfiles=grok x-search 缓存 */
      xAccounts: {}, xProfiles: {},
      /* /stats 聚合成品: null=未加载, statsErr=加载失败原因 */
      stats: null, statsErr: "",
      /* 来源详情表: 排序(默认条目数降序, 再点反向) + 前端搜索 */
      sortKey: "count", sortDir: -1, regQ: "",
    };
  },
  computed: {
    activeCount() {
      return ["markets", "positionings", "item_types", "sentiments", "sectors", "sources"]
        .reduce((n, k) => n + this.f[k].length, 0) + (this.f.q ? 1 : 0) + (this.f.tickers ? 1 : 0);
    },
    arrow() { return this.sortDir === 1 ? "↑" : "↓"; },
    /* 赛道 L1 过滤: 客户端作用于已加载条目(任一路径首段命中即中) */
    feedItems() {
      if (!this.f.sectors.length) return this.items;
      return this.items.filter((it) => (it.sectors || [])
        .some((s) => this.f.sectors.includes(String(s).split(">")[0])));
    },
    /* 赛道 chips: 常驻 top6(stats 高频, 兜底枚举前 6), 展开出全 19 */
    sectorCountMap() {
      const m = {};
      for (const [k, n] of (this.stats && this.stats.sectors_l1) || []) m[k] = n;
      return m;
    },
    sectorChipsTop() {
      return this.dict.sectorsTop.length ? this.dict.sectorsTop
        : this.enums.sectors_l1.slice(0, 6);
    },
    sectorChipsRest() {
      const top = new Set(this.sectorChipsTop);
      return this.enums.sectors_l1.filter((s) => !top.has(s));
    },
    /* 右栏条形图 top8 + 各自最大值(算宽度百分比) */
    marketBars() { return this.stats ? this.stats.markets.slice(0, 8) : []; },
    marketMax() { return this.marketBars.reduce((m, r) => Math.max(m, r[1]), 0); },
    sourceBars() { return this.stats ? this.stats.top_sources.slice(0, 8) : []; },
    sourceMax() { return this.sourceBars.reduce((m, r) => Math.max(m, r[1]), 0); },
    tickerBars() { return this.stats ? this.stats.tickers.slice(0, 8) : []; },
    typeBars() { return this.stats && this.stats.item_types ? this.stats.item_types : []; },
    typeMax() { return this.typeBars.reduce((m, r) => Math.max(m, r[1]), 0); },
    posBars() { return this.stats && this.stats.positionings ? this.stats.positionings : []; },
    posMax() { return this.posBars.reduce((m, r) => Math.max(m, r[1]), 0); },
    /* X 账号产量 Top10(独立卡, 点击 q=handle 反查) */
    xBars() { return this.stats && this.stats.x_accounts ? this.stats.x_accounts : []; },
    xMax() { return this.xBars.reduce((m, r) => Math.max(m, r[1]), 0); },
    tickerMax() { return this.tickerBars.reduce((m, r) => Math.max(m, r[1]), 0); },
    /* 来源详情行: 搜索过滤 + 排序均在前端完成(110 行量级无需服务端) */
    regRows() {
      const all = (this.stats && this.stats.sources) || [];
      const q = this.regQ.trim().toLowerCase();
      const rows = q ? all.filter((s) => s.id.toLowerCase().includes(q) ||
        (s.title || "").toLowerCase().includes(q) ||
        (s.brief || "").toLowerCase().includes(q)) : all.slice();
      const k = this.sortKey, dir = this.sortDir;
      const num = ["count", "ttl_min", "ms", "round_new"].includes(k);
      const val = (s) => (k === "markets" ? (s.markets || []).join("、") : s[k]);
      rows.sort((a, b) => {
        let va = val(a), vb = val(b);
        if (num) {
          /* 空值排最后(按 -1 参与比较, 降序时自然沉底) */
          va = va == null ? -1 : va; vb = vb == null ? -1 : vb;
          return (va - vb) * dir;
        }
        va = va == null ? "" : String(va); vb = vb == null ? "" : String(vb);
        return va.localeCompare(vb, "zh") * dir;
      });
      return rows;
    },
    regSummary() {
      const st = this.stats;
      if (!st) return this.statsErr ? "" : "加载中…";
      const rf = st.refresh || {};
      let t = st.sources.length + " 源 · 存活 " +
        (rf.sources_ok != null ? rf.sources_ok : "-") + " · 熔断 " + (st.dead || []).length;
      if (this.regQ.trim()) t += " · 匹配 " + this.regRows.length;
      return t;
    },
  },
  watch: {
    /* 切到来源详情时兜底补拉(正常 mounted 已拉, 覆盖失败重试/空场景) */
    tab(t) { if (t === "sources" && !this.stats) this.loadStats(); },
  },
  methods: {
    sinceValue() {
      const now = new Date();
      const fmt = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" +
        String(d.getDate()).padStart(2, "0") + " " + String(d.getHours()).padStart(2, "0") + ":" +
        String(d.getMinutes()).padStart(2, "0");
      if (this.f.since === "1h") return fmt(new Date(now - 3600e3));
      if (this.f.since === "4h") return fmt(new Date(now - 4 * 3600e3));
      if (this.f.since === "24h") return fmt(new Date(now - 24 * 3600e3));
      if (this.f.since === "3d") return fmt(new Date(now - 3 * 86400e3));
      return "";
    },
    buildQuery(cursor) {
      const p = new URLSearchParams();
      for (const k of ["markets", "positionings", "item_types", "sentiments", "sources"])
        if (this.f[k].length) p.set(k, this.f[k].join(","));
      if (this.f.q) p.set("q", this.f.q);
      if (this.f.tickers) p.set("tickers", this.f.tickers);
      const s = this.sinceValue();
      if (s) p.set("since", s);
      p.set("limit", "100");
      p.set("dedup", this.f.dedup ? "1" : "0");
      p.set("display", this.f.display ? "1" : "0");
      if (cursor) p.set("cursor", cursor);
      return p.toString();
    },
    async load(cursor) {
      this.loading = true; this.error = null;
      try {
        const d = await WB.api.get("/v1/items?" + this.buildQuery(cursor));
        this.items = cursor ? this.items.concat(d.items) : d.items;
        this.total = d.total; this.nextCursor = d.next_cursor || "";
        this.registerSubs();             // 更新左菜单上的命中计数
      } catch (e) { this.error = e; }
      this.loading = false;
    },
    reload() { this.items = []; this.nextCursor = ""; this.load(); },
    toggle(group, val) {
      const arr = this.f[group];
      const i = arr.indexOf(val);
      i >= 0 ? arr.splice(i, 1) : arr.push(val);
      if (group === "sectors") return;    // 赛道是客户端过滤, 不必重拉
      this.reload();
    },
    onSearch() { this.reload(); },
    clearAll() {
      for (const k of ["markets", "positionings", "item_types", "sentiments", "sectors", "sources"])
        this.f[k] = [];
      this.f.q = ""; this.f.tickers = "";
      this.reload();
    },
    addMaterial(it) { WB.basket.add(it); },
    sentimentBadge(s) {
      return s === "bull" ? "green" : s === "bear" ? "red" : s === "neutral" ? "yellow" : "";
    },
    sentimentText(s) {
      return { bull: "利好", bear: "利空", neutral: "中性" }[s] || s;
    },
    async loadDict() {
      try {
        const d = await WB.api.get("/v1/sources");
        const mk = new Set();
        for (const s of d.sources) (s.markets || []).forEach((m) => mk.add(m));
        this.dict = { markets: [...mk].sort(), sources: d.sources, sectorsTop: [] };
      } catch (e) { /* 数据站未起: load() 会报错展示 */ }
    },
    async loadStats() {
      this.statsErr = "";
      try { this.stats = await WB.api.get("/stats"); }
      catch (e) { this.statsErr = (e && e.error) || "统计接口不可用"; return; }
      /* 高频赛道 L1 top6 进筛选区常驻位 */
      this.dict.sectorsTop = (this.stats.sectors_l1 || []).slice(0, 6).map((r) => r[0]);
      this.registerSubs();               // 更新左菜单上的源总数
    },
    /* X 账号档案: 池录入(/x-accounts) + grok 增强缓存(/x-profiles), 失败静默降级 */
    async loadX() {
      try {
        const d = await WB.api.get("/x-accounts");
        this.xAccounts = d.accounts || {};
      } catch (e) { /* 池不可读: X 条目按通用源卡渲染 */ }
      try {
        const p = await WB.api.get("/x-profiles");
        this.xProfiles = p.profiles || {};
      } catch (e) {}
    },
    /* ── X 条目按账号渲染(author_handle 非空即 X 池条目) ── */
    isX(it) { return !!it.author_handle; },
    xAcct(it) {
      return this.xAccounts[String(it.author_handle || "").toLowerCase()] || null;
    },
    xProf(it) {
      return this.xProfiles[String(it.author_handle || "").toLowerCase()] || null;
    },
    /* 显示名: 池录入 name > 条目 source 去「X·」前缀 > @handle */
    xName(it) {
      const a = this.xAcct(it);
      if (a && a.name) return a.name;
      const s = String(it.source || "").replace(/^X·/, "").trim();
      return s || "@" + it.author_handle;
    },
    /* 简介: 池录入 note > grok bio; 都没有则空(降级不硬撑) */
    xBrief(it) {
      const a = this.xAcct(it), p = this.xProf(it);
      return (a && a.note) || (p && p.bio) || "";
    },
    /* 账号级标签: 定位=账号 role 投影(池档案优先), 市场=账号级(不再叠池级 6 徽章) */
    xPos(it) {
      const a = this.xAcct(it);
      return (a && a.positioning) || it.positioning || "";
    },
    xMarkets(it) {
      const a = this.xAcct(it);
      return (a && a.markets && a.markets.length) ? a.markets : (it.markets || []);
    },
    xRoleText(role) {
      return { media: "媒体", analyst: "分析师", trader: "交易员", kol: "大V",
               insider: "内部人士", company: "公司", data_bot: "数据Bot",
               breaks: "快讯Bot" }[role] || role;
    },
    xFollowers(it) {
      const p = this.xProf(it);
      const n = p && p.followers;
      if (!n) return "";
      return n >= 1e4 ? (n / 1e4).toFixed(1).replace(/\.0$/, "") + " 万"
                      : String(n);
    },
    /* 正文截断: 长文默认折叠, 点「展开全文」放开(flex 布局下 line-clamp 须配 white-space:normal) */
    bodyLong(it) {
      return ((it.title ? it.title.length + 3 : 0) + (it.text || "").length) > 300;
    },
    bodyClamp(it) { return this.bodyLong(it) && !this.bodyExpanded[it.id]; },
    pickXAccount(h) { this.f.q = h; this.f.since = ""; this.reload(); },
    /* 源对象查询: 先 dict(全量注册表), 兜底 stats.sources_detail, 都没有返回 null */
    sourceInfo(id) {
      const d = (this.dict.sources || []).find((s) => s.id === id);
      if (d) return d;
      const st = this.stats && this.stats.sources.find((s) => s.id === id);
      return st || null;
    },
    sourceTitle(id) {
      const s = this.sourceInfo(id);
      return (s && s.title) || id;
    },
    removeSource(sid) {
      this.f.sources = this.f.sources.filter((x) => x !== sid);
      this.reload();
    },
    /* 赛道路径分层: "L1>L2[>L3]" → [L1, "L2[>L3]"] */
    sectorParts(sec) {
      const p = String(sec).split(">");
      return [p[0] || "", p.slice(1).join(">")];
    },
    visibleSectors(it) { return (it.sectors || []).slice(0, 2); },
    sectorsRest(it) { return Math.max((it.sectors || []).length - 2, 0); },
    /* 右栏条形图点击 = 反查信息流。统计口径是全库窗口, 同步放开 since 避免 24h 截出 0 条 */
    pickMarket(m) { this.f.markets = [m]; this.f.since = ""; this.reload(); },
    pickSource(sid) { this.f.sources = [sid]; this.f.since = ""; this.reload(); },
    pickTicker(t) { this.f.tickers = t; this.f.since = ""; this.reload(); },
    pickPositioning(p) { this.f.positionings = [p]; this.f.since = ""; this.reload(); },
    /* 来源详情「筛选」= 单源过滤并跳回信息流子页(同上放开时间窗); 同步左侧菜单高亮 */
    srcFilter(id) {
      this.f.sources = [id]; this.f.since = ""; this.tab = "feed";
      if (WB.shell) WB.shell.setSub("feed");
      this.reload();
    },
    /* 向壳层注册左侧子页面菜单(火山控制台式: 主导航在上, 子页在左);
       cnt 随数据加载更新, 故 load/loadStats 完成后都会重注册一次 */
    registerSubs() {
      if (!WB.shell) return;
      if (!location.hash.replace(/^#/, "").startsWith("/news")) return;  // 迟到的异步回调不得覆盖别的页面
      const I = (p) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + p + "</svg>";
      WB.shell.setSubs([
        { id: "feed", title: "信息筛选", cnt: this.total || "",
          icon: I('<polygon points="22 3 2 3 10 12.5 10 19 14 21 14 12.5"/>'),
          onPick: () => { this.tab = "feed"; } },
        { id: "sources", title: "来源详情", cnt: this.stats ? this.stats.sources.length : "",
          icon: I('<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/>' +
                  '<path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>'),
          onPick: () => { this.tab = "sources"; } },
      ], this.tab);
    },
    /* 点表头排序: 同列反向, 新列数字降序/文本升序 */
    sortReg(key) {
      if (this.sortKey === key) { this.sortDir = -this.sortDir; return; }
      this.sortKey = key;
      this.sortDir = ["count", "ttl_min", "ms", "round_new"].includes(key) ? -1 : 1;
    },
    /* 健康列: 停用优先于健康状态展示 */
    pillClass(s) {
      if (s.enabled === false) return "off";
      if (s.health === "ok") return "ok";
      if (s.health === "dead") return "dead";
      return "unknown";
    },
    pillText(s) {
      if (s.enabled === false) return "停用";
      if (s.health === "ok") return "正常";
      if (s.health === "dead") return "熔断";
      return "未知";
    },
    /* bar-fill 宽度(唯一允许的 :style 动态绑定) */
    barW(c, max) { return max > 0 ? Math.round((c / max) * 100) + "%" : "0%"; },
  },
  mounted() { this.registerSubs(); this.loadDict(); this.loadStats(); this.loadX(); this.load(); },
  unmounted() { if (WB.shell) WB.shell.setSubs([]); },   // 离开资讯页清空左菜单
  template: `
  <div>
    <!-- 子页选择在左侧 subnav(壳层 WB.shell), 页内不再渲染页签 -->
    <!-- 子页1: 信息筛选(三栏: 筛选 / 双框信息流 / 统计右栏) -->
    <div class="news-layout" v-show="tab==='feed'">
      <!-- 左栏: 标签筛选器(双标签制: 源级=市场/定位, 条目级=类型/赛道/情绪) -->
      <div>
        <div class="card">
          <h3>标签筛选 <span v-if="activeCount" class="badge blue">{{ activeCount }}</span></h3>
          <div class="filter-group">
            <h4>市场 <span class="clear" v-if="f.markets.length" @click="f.markets=[]; reload()">清空</span></h4>
            <span v-for="m in dict.markets" class="chip" :class="{on: f.markets.includes(m)}"
                  @click="toggle('markets', m)">{{ m }}</span>
            <div class="muted" v-if="!dict.markets.length">(需数据站在线)</div>
          </div>
          <div class="filter-group">
            <h4>定位 <span class="clear" v-if="f.positionings.length" @click="f.positionings=[]; reload()">清空</span></h4>
            <span v-for="p in enums.positionings" class="chip" :class="{on: f.positionings.includes(p)}"
                  @click="toggle('positionings', p)">{{ p }}</span>
          </div>
          <div class="filter-group">
            <h4>类型 <span class="clear" v-if="f.item_types.length" @click="f.item_types=[]; reload()">清空</span></h4>
            <span v-for="t in enums.item_types" class="chip" :class="{on: f.item_types.includes(t)}"
                  @click="toggle('item_types', t)">{{ t }}</span>
          </div>
          <div class="filter-group">
            <h4>赛道 <span class="muted">作用于已加载</span>
              <span class="clear" v-if="f.sectors.length" @click="f.sectors=[]">清空</span></h4>
            <span v-for="s in sectorChipsTop" :key="s" class="chip" :class="{on: f.sectors.includes(s)}"
                  @click="toggle('sectors', s)">{{ s }}<template v-if="sectorCountMap[s]"> {{ sectorCountMap[s] }}</template></span>
            <template v-if="showAllSectors">
              <span v-for="s in sectorChipsRest" :key="s" class="chip" :class="{on: f.sectors.includes(s)}"
                    @click="toggle('sectors', s)">{{ s }}<template v-if="sectorCountMap[s]"> {{ sectorCountMap[s] }}</template></span>
            </template>
            <span class="act" @click="showAllSectors = !showAllSectors">
              {{ showAllSectors ? '收起' : '展开全部(19)' }}</span>
          </div>
          <div class="filter-group">
            <h4>情绪 <span class="clear" v-if="f.sentiments.length" @click="f.sentiments=[]; reload()">清空</span></h4>
            <span v-for="[v, t] in enums.sentiments" class="chip" :class="{on: f.sentiments.includes(v)}"
                  @click="toggle('sentiments', v)">{{ t }}</span>
          </div>
          <button class="btn" style="width:100%;justify-content:center" @click="clearAll">清空全部筛选</button>
        </div>
      </div>

      <!-- 中栏: 信息流(双框卡片: 左=来源信息, 右=内容信息) -->
      <div>
        <div class="feed-toolbar">
          <input type="text" v-model="f.q" placeholder="搜索(拆词 AND, 中英同检), 回车确认"
                 @keyup.enter="onSearch">
          <select v-model="f.since" @change="reload()">
            <option v-for="[v, t] in sinceOpts" :value="v">{{ t }}</option>
          </select>
          <label class="muted"><input type="checkbox" v-model="f.dedup" @change="reload()"> 折叠同事件</label>
          <label class="muted"><input type="checkbox" v-model="f.display" @change="reload()"> 中文优先</label>
          <!-- 来源过滤(由来源详情/条形图写入)在此露出, 点 × 清除 -->
          <span v-for="sid in f.sources" :key="sid" class="chip on" @click="removeSource(sid)">{{ sourceTitle(sid) }} ×</span>
        </div>
        <input type="text" v-model="f.tickers" placeholder="标的过滤(如 NVDA,TSLA), 回车确认"
               style="width:100%;margin-bottom:10px" @keyup.enter="onSearch">

        <div v-if="error" class="err-box">
          <p>{{ error.error }}</p>
          <p v-if="error.hint" style="margin-top:6px">{{ error.hint }}</p>
          <p style="margin-top:10px"><code>python cli.py sources serve</code></p>
        </div>
        <div v-else-if="!feedItems.length && !loading" class="empty">
          {{ f.sectors.length ? '已加载条目里无该赛道 —— 试试加载更多或放宽其他筛选' : '无匹配条目 —— 调整筛选或先跑 sources refresh' }}</div>

        <div class="feed">
        <div v-for="it in feedItems" :key="it.id" class="news-card">
          <div class="nc-grid">
            <!-- 左框 X 账号版: 显示名 + @handle + 账号级标签 + 简介(note>grok bio) + 粉丝数 -->
            <div class="nc-src" v-if="isX(it)">
              <div class="name">{{ xName(it) }}</div>
              <div class="who">
                <a :href="'https://x.com/' + it.author_handle" target="_blank" rel="noopener"
                   @click.stop>@{{ it.author_handle }}</a>
                <span v-if="xAcct(it) && xAcct(it).role && xRoleText(xAcct(it).role) !== xPos(it)"
                      class="badge">{{ xRoleText(xAcct(it).role) }}</span>
                <span v-if="xProf(it) && xProf(it).verified" class="badge blue" title="X 认证账号">✓</span>
              </div>
              <div class="nc-badges" style="margin-bottom:0">
                <span v-if="xPos(it)" class="badge blue">{{ xPos(it) }}</span>
                <span v-for="m in xMarkets(it)" class="badge">{{ m }}</span>
              </div>
              <div class="brief" v-if="xBrief(it)">{{ xBrief(it) }}</div>
              <div class="who" v-if="xFollowers(it)">X 粉丝 ~{{ xFollowers(it) }}</div>
            </div>
            <!-- 左框通用版: 来源信息(源级标签 + 简介) -->
            <div class="nc-src" v-else>
              <div class="name">{{ sourceTitle(it.source_id) }}</div>
              <div class="nc-badges" style="margin-bottom:0">
                <span v-if="it.positioning" class="badge blue">{{ it.positioning }}</span>
                <span v-for="m in ((sourceInfo(it.source_id) || {}).markets || it.markets || [])"
                      class="badge">{{ m }}</span>
              </div>
              <div class="brief" v-if="(sourceInfo(it.source_id) || {}).brief">
                {{ sourceInfo(it.source_id).brief }}</div>
            </div>
            <!-- 右框: 内容信息(条目级标签 + 时间点 + 标题正文 + 操作) -->
            <div class="nc-body">
              <div class="nc-badges">
                <span class="nc-time">{{ it.time }}</span>
                <span v-if="it.item_type" class="badge blue">{{ it.item_type }}</span>
                <template v-for="sec in visibleSectors(it)">
                  <span class="badge yellow" :title="sec">{{ sectorParts(sec)[0] }}</span>
                  <span v-if="sectorParts(sec)[1]" class="badge" :title="sec">{{ sectorParts(sec)[1] }}</span>
                </template>
                <span v-if="sectorsRest(it)" class="badge"
                      :title="(it.sectors || []).join('\\n')">+{{ sectorsRest(it) }}</span>
                <span v-if="it.sentiment" class="badge" :class="sentimentBadge(it.sentiment)">
                  {{ sentimentText(it.sentiment) }}</span>
                <span v-for="t in it.tickers" class="badge">{{ t }}</span>
                <span v-if="it.event_type" class="badge">{{ it.event_type }}</span>
                <span v-if="it.dup_count > 1" class="badge yellow">同事件 ×{{ it.dup_count }}</span>
              </div>
              <div class="news-text" :class="{clamp: bodyClamp(it)}">{{ it.title ? it.title + ' — ' : '' }}{{ it.text }}</div>
              <div class="news-src-text" v-if="expanded[it.id] && it.text_src">{{ it.text_src }}</div>
              <div class="news-actions">
                <a v-if="it.url" :href="it.url" target="_blank" rel="noopener">原文链接 ↗</a>
                <span class="act" v-if="bodyLong(it)" @click="bodyExpanded[it.id] = !bodyExpanded[it.id]">
                  {{ bodyExpanded[it.id] ? '收起' : '展开全文' }}</span>
                <span class="act" v-if="it.text_src" @click="expanded[it.id] = !expanded[it.id]">
                  {{ expanded[it.id] ? '收起原文' : '查看原文(译前)' }}</span>
                <span class="act" @click="addMaterial(it)">＋加入素材篮</span>
              </div>
            </div>
          </div>
        </div>
        </div>

        <div class="load-more">
          <button v-if="nextCursor" class="btn" :disabled="loading" @click="load(nextCursor)">
            {{ loading ? '加载中…' : '加载更多' }}</button>
          <span v-else-if="items.length" class="muted">—— 已加载全部 {{ items.length }} 条 ——</span>
        </div>
      </div>

      <!-- 右栏: 统计看板(数据全部来自 /stats) -->
      <div class="news-status">
        <div class="err-box" v-if="statsErr">{{ statsErr }}</div>
        <div class="card" v-else-if="!stats"><p class="muted">统计加载中…</p></div>
        <template v-else>
          <div class="card">
            <div class="stat-mini-grid">
              <div class="stat-mini">
                <div class="k">命中条数</div>
                <div class="v">{{ activeCount ? total : stats.fetched }}</div>
                <div class="n">{{ stats.truncated ? '已达抓取上限' : (activeCount ? '当前筛选命中' : '未筛选 · 抓取量') }}</div>
              </div>
              <div class="stat-mini">
                <div class="k">库内总条数</div>
                <div class="v">{{ stats.total }}</div>
                <div class="n">聚合簇 {{ stats.clusters }}</div>
              </div>
              <div class="stat-mini">
                <div class="k">本轮新增</div>
                <div class="v">{{ stats.refresh.new }}</div>
                <div class="n">{{ stats.refresh.round_started_at }}</div>
              </div>
              <div class="stat-mini">
                <div class="k">源存活</div>
                <div class="v">{{ stats.refresh.sources_ok }}/{{ stats.refresh.sources_total }}</div>
                <div class="n">{{ stats.dead.length ? 'dead ' + stats.dead.length + ' 已熔断' : '全部健康' }}</div>
              </div>
            </div>
          </div>
          <div class="card">
            <h3>市场覆盖</h3>
            <div class="bars">
              <div v-for="r in marketBars" :key="r[0]" class="bar-row clickable" @click="pickMarket(r[0])">
                <span class="lab">{{ r[0] }}</span>
                <span class="bar-track"><span class="bar-fill" :style="{width: barW(r[1], marketMax)}"></span></span>
                <span class="val">{{ r[1] }}</span>
              </div>
            </div>
          </div>
          <div class="card">
            <h3>类型分布</h3>
            <div class="bars">
              <div v-for="r in typeBars" :key="r[0]" class="bar-row">
                <span class="lab">{{ r[0] }}</span>
                <span class="bar-track"><span class="bar-fill" :style="{width: barW(r[1], typeMax)}"></span></span>
                <span class="val">{{ r[1] }}</span>
              </div>
            </div>
          </div>
          <div class="card">
            <h3>定位分布</h3>
            <div class="bars">
              <div v-for="r in posBars" :key="r[0]" class="bar-row clickable" @click="pickPositioning(r[0])">
                <span class="lab">{{ r[0] }}</span>
                <span class="bar-track"><span class="bar-fill" :style="{width: barW(r[1], posMax)}"></span></span>
                <span class="val">{{ r[1] }}</span>
              </div>
            </div>
          </div>
          <div class="card">
            <h3>产量最高的源</h3>
            <div class="bars">
              <div v-for="r in sourceBars" :key="r[2]" class="bar-row clickable" @click="pickSource(r[2])">
                <span class="lab">{{ r[0] }}</span>
                <span class="bar-track"><span class="bar-fill" :style="{width: barW(r[1], sourceMax)}"></span></span>
                <span class="val">{{ r[1] }}</span>
              </div>
            </div>
          </div>
          <div class="card" v-if="xBars.length">
            <h3>X 账号产量 Top10</h3>
            <div class="bars">
              <div v-for="r in xBars" :key="r[2]" class="bar-row clickable" @click="pickXAccount(r[2])">
                <span class="lab" :title="'@' + r[2]">{{ r[0] }}</span>
                <span class="bar-track"><span class="bar-fill" :style="{width: barW(r[1], xMax)}"></span></span>
                <span class="val">{{ r[1] }}</span>
              </div>
            </div>
            <p class="muted" style="margin-top:6px">点击账号名 = 反查该账号全部内容</p>
          </div>
          <div class="card">
            <h3>热门标的</h3>
            <div class="bars">
              <div v-for="r in tickerBars" :key="r[0]" class="bar-row clickable" @click="pickTicker(r[0])">
                <span class="lab">{{ r[0] }}</span>
                <span class="bar-track"><span class="bar-fill" :style="{width: barW(r[1], tickerMax)}"></span></span>
                <span class="val">{{ r[1] }}</span>
              </div>
            </div>
          </div>
          <div class="card">
            <h3>数据站</h3>
            <p class="muted" v-if="stats.span">数据窗口 {{ stats.span[0] }} ~ {{ stats.span[1] }}</p>
            <p class="muted" v-else>数据站为空 —— 先跑 sources refresh</p>
            <p class="muted" v-if="stats.future_excluded">已剔除未来日期行 {{ stats.future_excluded }} 条</p>
            <p class="muted" v-if="stats.dead && stats.dead.length">
              已熔断 <span class="mono">{{ stats.dead.slice(0, 5).join(', ') }}</span></p>
          </div>
        </template>
      </div>
    </div>

    <!-- 子页2: 来源详情(/stats.sources 全量注册表, 搜索+排序在前端) -->
    <div v-show="tab==='sources'">
      <div class="reg-toolbar">
        <input type="text" v-model="regQ" placeholder="搜索源 ID / 说明">
        <span class="muted">{{ regSummary }}</span>
      </div>
      <div class="err-box" v-if="statsErr">{{ statsErr }}</div>
      <div class="reg-wrap" v-else-if="stats">
        <div class="reg-scroll">
          <table class="reg">
            <thead>
              <tr>
                <th @click="sortReg('count')">条目数<span class="arr" v-if="sortKey==='count'">{{ arrow }}</span></th>
                <th @click="sortReg('id')">源ID<span class="arr" v-if="sortKey==='id'">{{ arrow }}</span></th>
                <th @click="sortReg('title')">说明<span class="arr" v-if="sortKey==='title'">{{ arrow }}</span></th>
                <th @click="sortReg('kind')">形态<span class="arr" v-if="sortKey==='kind'">{{ arrow }}</span></th>
                <th @click="sortReg('markets')">市场<span class="arr" v-if="sortKey==='markets'">{{ arrow }}</span></th>
                <th @click="sortReg('positioning')">定位<span class="arr" v-if="sortKey==='positioning'">{{ arrow }}</span></th>
                <th @click="sortReg('health')">健康<span class="arr" v-if="sortKey==='health'">{{ arrow }}</span></th>
                <th @click="sortReg('ttl_min')">TTL<span class="arr" v-if="sortKey==='ttl_min'">{{ arrow }}</span></th>
                <th @click="sortReg('ms')">耗时<span class="arr" v-if="sortKey==='ms'">{{ arrow }}</span></th>
                <th @click="sortReg('round_new')">上轮新增<span class="arr" v-if="sortKey==='round_new'">{{ arrow }}</span></th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in regRows" :key="s.id">
                <td class="num">{{ s.count != null ? s.count : '-' }}</td>
                <td><span class="mono">{{ s.id }}</span></td>
                <td>{{ s.brief || s.title }}<span v-if="s.pool_accounts" class="muted"> · 池内 {{ s.pool_accounts }} 账号</span></td>
                <td><span class="badge">{{ s.kind }}</span></td>
                <td>{{ (s.markets || []).join('、') }}</td>
                <td>{{ s.positioning }}</td>
                <td><span class="pill" :class="pillClass(s)">{{ pillText(s) }}</span></td>
                <td class="num">{{ s.ttl_min != null ? s.ttl_min + 'm' : '-' }}</td>
                <td class="num">{{ s.ms != null ? s.ms + ' ms' : '-' }}</td>
                <td class="num">{{ s.round_new != null ? s.round_new : '-' }}</td>
                <td><span class="src-acts"><span class="act" @click="srcFilter(s.id)">筛选</span></span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div class="card" v-else><p class="muted">统计加载中…</p></div>
    </div>
  </div>`,
};
