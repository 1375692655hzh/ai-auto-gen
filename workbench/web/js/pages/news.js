/* 资讯页: 大页内双子页(信息筛选 / 来源详情)
   信息筛选 = 标签筛选(四标签体系+信息标签) + 信息流 + 统计右栏(同事看板式);
   来源详情 = /stats 来源注册表(前端搜索+排序), 「筛选」跳回信息筛选。
   数据全部来自 workbench 代理的 /wb-api/* → sources serve;
   统计来自 /stats(服务端聚合, 60s 缓存), 右栏与来源详情共用一份。 */
window.WB = window.WB || {};
WB.pages = WB.pages || {};

WB.pages.news = {
  data() {
    return {
      /* 子页: feed=信息筛选, sources=来源详情 */
      tab: "feed",
      /* 筛选枚举: 市场/形态从 /v1/sources 聚合, 类型/定位/情绪用封闭枚举
         (2026-09-03 双标签制: 对齐 taxonomy.py 单一真相) */
      dict: { markets: [], forms: [], positionings: [], sources: [] },
      enums: {
        kinds: [["flash", "快讯"], ["peer_article", "文章"], ["calendar", "日历"],
                ["market", "行情"], ["announcement", "公告"], ["evidence", "证据"]],
        item_types: [["聚合", "聚合"], ["快讯", "快讯"], ["资讯", "资讯"], ["分析", "分析"]],
        info_types: [["filing", "公告披露"], ["news", "事实资讯"], ["data", "数据信号"],
                     ["analysis", "分析"], ["rumor", "传言"], ["calendar", "事件预告"]],
        sentiments: [["bull", "利好"], ["bear", "利空"], ["neutral", "中性"]],
        positionings: [["官方", "官方"], ["机构", "机构"], ["大V", "大V"],
                       ["快讯源", "快讯源"], ["新闻源", "新闻源"]],
      },
      /* sources 保留: 来源详情页与右栏条形图会写入, 仅 UI 不再提供多选框 */
      f: { markets: [], kinds: [], forms: [], positionings: [], item_types: [],
           sentiments: [], sources: [], q: "", tickers: "", event_types: "",
           since: "24h", dedup: true, display: true },
      sinceOpts: [["1h", "近1小时"], ["4h", "近4小时"], ["24h", "近24小时"], ["3d", "近3天"], ["", "全部"]],
      items: [], total: 0, nextCursor: "", loading: false, error: null,
      expanded: {},
      /* /stats 聚合成品: null=未加载, statsErr=加载失败原因 */
      stats: null, statsErr: "",
      /* 来源详情表: 排序(默认条目数降序, 再点反向) + 前端搜索 */
      sortKey: "count", sortDir: -1, regQ: "",
    };
  },
  computed: {
    activeCount() {
      return ["markets", "kinds", "forms", "positionings", "item_types", "sentiments", "sources"]
        .reduce((n, k) => n + this.f[k].length, 0) + (this.f.q ? 1 : 0) + (this.f.tickers ? 1 : 0);
    },
    arrow() { return this.sortDir === 1 ? "↑" : "↓"; },
    /* 右栏条形图 top8 + 各自最大值(算宽度百分比) */
    marketBars() { return this.stats ? this.stats.markets.slice(0, 8) : []; },
    marketMax() { return this.marketBars.reduce((m, r) => Math.max(m, r[1]), 0); },
    sourceBars() { return this.stats ? this.stats.top_sources.slice(0, 8) : []; },
    sourceMax() { return this.sourceBars.reduce((m, r) => Math.max(m, r[1]), 0); },
    tickerBars() { return this.stats ? this.stats.tickers.slice(0, 8) : []; },
    typeBars() { return this.stats && this.stats.item_types ? this.stats.item_types : []; },
    typeMax() { return this.typeBars.reduce((m, r) => Math.max(m, r[1]), 0); },
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
      for (const k of ["markets", "kinds", "forms", "positionings", "item_types", "sentiments", "sources"])
        if (this.f[k].length) p.set(k, this.f[k].join(","));
      if (this.f.q) p.set("q", this.f.q);
      if (this.f.tickers) p.set("tickers", this.f.tickers);
      if (this.f.event_types) p.set("event_types", this.f.event_types);
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
      this.reload();
    },
    onSearch() { this.reload(); },
    clearAll() {
      for (const k of ["markets", "kinds", "forms", "positionings", "item_types", "sentiments", "sources"])
        this.f[k] = [];
      this.f.q = ""; this.f.tickers = ""; this.f.event_types = "";
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
        const mk = new Set(), fm = new Set(), ps = new Set();
        for (const s of d.sources) {
          (s.markets || []).forEach((m) => mk.add(m));
          if (s.form) fm.add(s.form);
          if (s.positioning) ps.add(s.positioning);
        }
        this.dict = { markets: [...mk].sort(), forms: [...fm].sort(),
                      positionings: [...ps].sort(), sources: d.sources };
      } catch (e) { /* 数据站未起: load() 会报错展示 */ }
    },
    async loadStats() {
      this.statsErr = "";
      try { this.stats = await WB.api.get("/stats"); }
      catch (e) { this.statsErr = (e && e.error) || "统计接口不可用"; }
      this.registerSubs();               // 更新左菜单上的源总数
    },
    /* 源 id → 展示名: 优先 dict(全量注册表), 兜底 stats, 再兜底 id 本身 */
    sourceTitle(id) {
      const d = (this.dict.sources || []).find((s) => s.id === id);
      if (d && d.title) return d.title;
      const st = this.stats && this.stats.sources.find((s) => s.id === id);
      return (st && st.title) || id;
    },
    removeSource(sid) {
      this.f.sources = this.f.sources.filter((x) => x !== sid);
      this.reload();
    },
    /* 右栏条形图点击 = 反查信息流。统计口径是全库窗口, 同步放开 since 避免 24h 截出 0 条 */
    pickMarket(m) { this.f.markets = [m]; this.f.since = ""; this.reload(); },
    pickSource(sid) { this.f.sources = [sid]; this.f.since = ""; this.reload(); },
    pickTicker(t) { this.f.tickers = t; this.f.since = ""; this.reload(); },
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
  mounted() { this.registerSubs(); this.loadDict(); this.loadStats(); this.load(); },
  unmounted() { if (WB.shell) WB.shell.setSubs([]); },   // 离开资讯页清空左菜单
  template: `
  <div>
    <!-- 子页选择在左侧 subnav(壳层 WB.shell), 页内不再渲染页签 -->
    <!-- 子页1: 信息筛选(原三栏布局, v-show 保状态) -->
    <div class="news-layout" v-show="tab==='feed'">
      <!-- 左栏: 标签筛选器(来源筛选已迁至「来源详情」子页与右栏条形图) -->
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
            <h4>类型</h4>
            <span v-for="[v, t] in enums.kinds" class="chip" :class="{on: f.kinds.includes(v)}"
                  @click="toggle('kinds', v)">{{ t }}</span>
          </div>
          <div class="filter-group">
            <h4>类型</h4>
            <span v-for="[v, t] in enums.item_types" class="chip" :class="{on: f.item_types.includes(v)}"
                  @click="toggle('item_types', v)">{{ t }}</span>
          </div>
          <div class="filter-group">
            <h4>情绪</h4>
            <span v-for="[v, t] in enums.sentiments" class="chip" :class="{on: f.sentiments.includes(v)}"
                  @click="toggle('sentiments', v)">{{ t }}</span>
          </div>
          <div class="filter-group">
            <h4>定位</h4>
            <span v-for="[v, t] in enums.positionings" class="chip" :class="{on: f.positionings.includes(v)}"
                  @click="toggle('positionings', v)">{{ t }}</span>
          </div>
          <div class="filter-group">
            <h4>形态</h4>
            <span v-for="m in dict.forms" class="chip" :class="{on: f.forms.includes(m)}"
                  @click="toggle('forms', m)">{{ m }}</span>
          </div>
          <button class="btn" style="width:100%;justify-content:center" @click="clearAll">清空全部筛选</button>
        </div>
      </div>

      <!-- 中栏: 信息流 -->
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
        <div v-else-if="!items.length && !loading" class="empty">无匹配条目 —— 调整筛选或先跑 sources refresh</div>

        <div class="feed">
        <div v-for="it in items" :key="it.id" class="news-card">
          <div class="news-meta">
            <span>{{ it.time }}</span>
            <span class="badge blue">{{ it.source }}</span>
            <span v-for="m in it.markets" class="badge">{{ m }}</span>
            <span v-if="it.item_type" class="badge blue">{{ it.item_type }}</span>
            <span v-if="it.positioning" class="badge">{{ it.positioning }}</span>
            <span v-for="sec in it.sectors" class="badge yellow">{{ sec }}</span>
            <span v-if="it.sentiment" class="badge" :class="sentimentBadge(it.sentiment)">
              {{ sentimentText(it.sentiment) }}</span>
            <span v-if="it.event_type" class="badge">{{ it.event_type }}</span>
            <span v-if="it.dup_count > 1" class="badge yellow">同事件 ×{{ it.dup_count }}</span>
          </div>
          <div class="news-text">{{ it.title ? it.title + ' — ' : '' }}{{ it.text }}</div>
          <div class="news-src-text" v-if="expanded[it.id] && it.text_src">{{ it.text_src }}</div>
          <div class="tickers"><span v-for="t in it.tickers" class="badge">{{ t }}</span></div>
          <div class="news-actions">
            <a v-if="it.url" :href="it.url" target="_blank" rel="noopener">原文链接 ↗</a>
            <span class="act" v-if="it.text_src" @click="expanded[it.id] = !expanded[it.id]">
              {{ expanded[it.id] ? '收起原文' : '查看原文(译前)' }}</span>
            <span class="act" @click="addMaterial(it)">＋加入素材篮</span>
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
            <h3>产量最高的源</h3>
            <div class="bars">
              <div v-for="r in sourceBars" :key="r[2]" class="bar-row clickable" @click="pickSource(r[2])">
                <span class="lab">{{ r[0] }}</span>
                <span class="bar-track"><span class="bar-fill" :style="{width: barW(r[1], sourceMax)}"></span></span>
                <span class="val">{{ r[1] }}</span>
              </div>
            </div>
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
                <th @click="sortReg('kind')">类型<span class="arr" v-if="sortKey==='kind'">{{ arrow }}</span></th>
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
                <td>{{ s.brief || s.title }}</td>
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
