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
      /* ── 推荐信息 ── */
      recoSince: "24h",
      sinceOpts: [["1h", "近1小时"], ["4h", "近4小时"], ["24h", "近24小时"], ["3d", "近3天"], ["", "全部"]],
      recoMarkets: [], recoPositionings: [], recoItemTypes: [],
      recoItems: [], recoTotal: 0, recoRule: "", recoLoading: false, recoErr: "",
      /* X 池账号档案(与资讯页同源: /x-accounts + /x-profiles) + 正文截断状态 */
      xAccounts: {}, xProfiles: {}, bodyExpanded: {},
      /* ── 内容生成(实时编辑 = 信息选择 + 生成模块排列组合 + 固定模板) ── */
      materials: [],
      modules: [
        { id: "retrieve", title: "信息检索", desc: "按素材标的/关键词回查数据站, 补全上下文", on: true },
        { id: "snapshot", title: "快照抓取", desc: "抓取素材原文页面快照存档", on: false },
        { id: "tech", title: "技术分析", desc: "对素材涉及标的生成技术面解读", on: false },
        { id: "aggregate", title: "聚合分析", desc: "同事件多源交叉验证与要点归并", on: true },
      ],
      flows: [], template: "",
      editingId: "", editorTitle: "", editorContent: "",
      drafts: [], runs: [],
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
  computed: {
    wordCount() { return (this.editorContent || "").length; },
    onModules() { return this.modules.filter((m) => m.on).map((m) => m.id); },
    pubDraft() { return this.drafts.find((d) => d.id === this.pubDraftId) || null; },
  },
  methods: {
    /* ── 壳层子菜单注册(计数随数据更新) ── */
    registerSubs() {
      if (!WB.shell) return;
      if (!location.hash.replace(/^#/, "").startsWith("/article")) return;  // 迟到的异步回调不得覆盖别的页面
      const I = (p) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + p + "</svg>";
      WB.shell.setSubs([
        { id: "reco", title: "推荐信息", cnt: this.recoTotal || "",
          icon: I('<polygon points="12 2 15 9 22 9.3 16.5 14 18.5 21 12 17 5.5 21 7.5 14 2 9.3 9 9"/>'),
          onPick: () => { this.tab = "reco"; } },
        { id: "gen", title: "内容生成", cnt: this.materials.length || "",
          icon: I('<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>'),
          onPick: () => { this.tab = "gen"; } },
        { id: "pub", title: "内容发布", cnt: this.drafts.length || "",
          icon: I('<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4Z"/>'),
          onPick: () => { this.tab = "pub"; } },
        { id: "auto", title: "自动化任务", cnt: this.tasks.length || "",
          icon: I('<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/>'),
          onPick: () => { this.tab = "auto"; } },
      ], this.tab);
    },
    go(t) { this.tab = t; if (WB.shell) WB.shell.setSub(t); },

    /* ── 推荐信息 ── */
    sinceValue() {
      const now = new Date();
      const fmt = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" +
        String(d.getDate()).padStart(2, "0") + " " + String(d.getHours()).padStart(2, "0") + ":" +
        String(d.getMinutes()).padStart(2, "0");
      const map = { "1h": 3600e3, "4h": 4 * 3600e3, "24h": 86400e3, "3d": 3 * 86400e3 };
      return map[this.recoSince] ? fmt(new Date(now - map[this.recoSince])) : "";
    },
    async loadDict() {
      try {
        const d = await WB.api.get("/v1/sources");
        const mk = new Set();
        for (const s of d.sources) (s.markets || []).forEach((m) => mk.add(m));
        this.dict = { markets: [...mk].sort() };
      } catch (e) { /* 数据站未起时 loadReco 会报错展示 */ }
    },
    async loadReco() {
      this.recoLoading = true; this.recoErr = "";
      try {
        const p = new URLSearchParams();
        const s = this.sinceValue();
        if (s) p.set("since", s);
        if (this.recoMarkets.length) p.set("markets", this.recoMarkets.join(","));
        if (this.recoPositionings.length) p.set("positionings", this.recoPositionings.join(","));
        if (this.recoItemTypes.length) p.set("item_types", this.recoItemTypes.join(","));
        p.set("limit", "50");
        const d = await WB.api.get("/recommend?" + p.toString());
        this.recoItems = d.items; this.recoTotal = d.total; this.recoRule = d.rule;
      } catch (e) { this.recoErr = e.error || "推荐接口不可用"; }
      this.recoLoading = false;
      this.registerSubs();
    },
    recoToggle(group, val) {
      const arr = this[group];
      const i = arr.indexOf(val);
      i >= 0 ? arr.splice(i, 1) : arr.push(val);
      this.loadReco();
    },
    scoreParts(it) {
      return (it.score_parts || []).map((p) => p[0] + " +" + p[1]).join(" · ");
    },
    /* 赛道路径分层展示(与资讯页同规则): [L1, "L2[>L3]"], 最多 2 条 +n 收口 */
    sectorParts(sec) {
      const p = String(sec).split(">");
      return [p[0] || "", p.slice(1).join(">")];
    },
    visibleSectors(it) { return (it.sectors || []).slice(0, 2); },
    sectorsRest(it) { return Math.max((it.sectors || []).length - 2, 0); },
    addToGen(it) {
      WB.basket.add(it);
      this.syncMaterials();
      this.go("gen");
    },
    sentimentBadge(s) {
      return s === "bull" ? "green" : s === "bear" ? "red" : s === "neutral" ? "yellow" : "";
    },
    sentimentText(s) { return { bull: "利好", bear: "利空", neutral: "中性" }[s] || s; },
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
    removeMaterial(id) { WB.basket.remove(id); this.syncMaterials(); },
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
        items: this.materials.map((m) => m.id), modules: this.onModules,
        template: this.template,
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
      this.autoForm.template = this.template;
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
  mounted() {
    this.registerSubs();
    this.syncMaterials();
    this.loadDict(); this.loadReco(); this.loadX();
    this.loadFlows(); this.loadRuns(); this.loadDrafts();
    this.loadAccounts(); this.loadLedger(); this.loadTasks();
  },
  unmounted() { if (WB.shell) WB.shell.setSubs([]); },

  template: `
  <div>
    <!-- ═══ 子页1: 推荐信息(回溯范围 + 标签筛选 + 价值排序) ═══ -->
    <div v-show="tab==='reco'">
      <div class="feed-toolbar">
        <select v-model="recoSince" @change="loadReco">
          <option v-for="[v, t] in sinceOpts" :value="v">{{ t }}</option>
        </select>
        <span class="muted">按价值、重要性排序</span>
        <span style="flex:1"></span>
        <button class="btn" @click="loadReco">{{ recoLoading ? '刷新中…' : '刷新' }}</button>
      </div>
      <div class="card">
        <div class="filter-group" style="margin-bottom:8px">
          <h4>市场</h4>
          <span v-for="m in dict.markets" class="chip" :class="{on: recoMarkets.includes(m)}"
                @click="recoToggle('recoMarkets', m)">{{ m }}</span>
        </div>
        <div class="filter-group" style="margin-bottom:8px">
          <h4>定位</h4>
          <span v-for="p in tagEnums.positionings" class="chip" :class="{on: recoPositionings.includes(p)}"
                @click="recoToggle('recoPositionings', p)">{{ p }}</span>
        </div>
        <div class="filter-group" style="margin-bottom:0">
          <h4>类型</h4>
          <span v-for="t in tagEnums.item_types" class="chip" :class="{on: recoItemTypes.includes(t)}"
                @click="recoToggle('recoItemTypes', t)">{{ t }}</span>
        </div>
      </div>
      <p class="muted" style="margin-bottom:10px">打分规则: {{ recoRule }}(服务端透明打分, 可在每条下展开构成)</p>

      <div v-if="recoErr" class="err-box">{{ recoErr }}</div>
      <div v-else-if="!recoItems.length && !recoLoading" class="empty">该范围内暂无推荐 —— 放宽回溯时间或标签</div>
      <div class="feed">
        <div v-for="it in recoItems" :key="it.id" class="news-card">
          <div class="nc-grid">
            <!-- 左框 X 账号版(与资讯页同规则: 账号名+handle+账号级标签+简介) -->
            <div class="nc-src" v-if="isX(it)">
              <div class="name">{{ xName(it) }}</div>
              <div class="who">@{{ it.author_handle }}</div>
              <div class="nc-badges" style="margin-bottom:0">
                <span v-if="xPos(it)" class="badge blue">{{ xPos(it) }}</span>
                <span v-for="m in xMarkets(it)" class="badge">{{ m }}</span>
              </div>
              <div class="brief" v-if="xBrief(it)">{{ xBrief(it) }}</div>
            </div>
            <!-- 左框通用版: 来源信息(推荐场景密度优先: 来源名+定位+市场) -->
            <div class="nc-src" v-else>
              <div class="name">{{ it.source }}</div>
              <div class="nc-badges" style="margin-bottom:0">
                <span v-if="it.positioning" class="badge blue">{{ it.positioning }}</span>
                <span v-for="m in it.markets" class="badge">{{ m }}</span>
              </div>
            </div>
            <!-- 右框: 内容信息(价值分 + 条目级标签 + 正文) -->
            <div class="nc-body">
              <div class="nc-badges">
                <span class="nc-time">{{ it.time }}</span>
                <span class="badge blue" :title="scoreParts(it)">价值 {{ it.score }}</span>
                <span v-if="it.item_type" class="badge">{{ it.item_type }}</span>
                <template v-for="sec in visibleSectors(it)">
                  <span class="badge yellow" :title="sec">{{ sectorParts(sec)[0] }}</span>
                  <span v-if="sectorParts(sec)[1]" class="badge" :title="sec">{{ sectorParts(sec)[1] }}</span>
                </template>
                <span v-if="sectorsRest(it)" class="badge"
                      :title="(it.sectors || []).join('\\n')">+{{ sectorsRest(it) }}</span>
                <span v-if="it.sentiment" class="badge" :class="sentimentBadge(it.sentiment)">
                  {{ sentimentText(it.sentiment) }}</span>
                <span v-if="it.dup_count > 1" class="badge yellow">同事件 ×{{ it.dup_count }}</span>
              </div>
              <div class="news-text" :class="{clamp: bodyClamp(it)}">{{ it.title ? it.title + ' — ' : '' }}{{ it.text }}</div>
              <div class="muted" style="margin-top:4px">{{ scoreParts(it) }}</div>
              <div class="news-actions">
                <a v-if="it.url" :href="it.url" target="_blank" rel="noopener">原文链接 ↗</a>
                <span class="act" v-if="bodyLong(it)" @click="bodyExpanded[it.id] = !bodyExpanded[it.id]">
                  {{ bodyExpanded[it.id] ? '收起' : '展开全文' }}</span>
                <span class="act" @click="addToGen(it)">＋加入生成</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ 子页2: 内容生成(信息选择 + 模块排列组合 + 固定模板 + 实时编辑) ═══ -->
    <div v-show="tab==='gen'" class="three-col">
      <!-- 左: 信息选择 + 历史/草稿 -->
      <div>
        <div class="card">
          <h3>信息选择({{ materials.length }})</h3>
          <div v-if="!materials.length" class="muted">
            空 —— 到「推荐信息」点「＋加入生成」, 或资讯页点「＋加入素材篮」</div>
          <div v-for="m in materials" :key="m.id" class="list-item">
            <div class="t">{{ m.text || '(无标题)' }}</div>
            <div class="s">{{ m.time }} · {{ m.source }}
              <a style="float:right" @click.stop="removeMaterial(m.id)">移除</a></div>
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

      <!-- 中: 生成模块排列组合 + 固定模板 + 实时编辑画布 -->
      <div>
        <div class="card">
          <h3>生成模块(勾选 + 排列组合)</h3>
          <div v-for="(m, i) in modules" :key="m.id" class="list-item" :class="{sel: m.on}">
            <div class="t">
              <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
                <input type="checkbox" v-model="m.on">{{ m.title }}</label>
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
            <label>固定模板</label>
            <select v-model="template" style="width:260px">
              <option value="">(不使用模板)</option>
              <option v-for="fl in flows" :value="fl.name">{{ fl.name }} — {{ fl.title }}</option>
            </select>
          </div>
        </div>

        <div class="card">
          <h3>实时编辑 <span class="muted">{{ editingId ? '草稿 ' + editingId : '新草稿' }}</span></h3>
          <div class="form-row">
            <label>标题</label>
            <input type="text" v-model="editorTitle" placeholder="文章标题" style="width:100%;max-width:420px">
          </div>
          <textarea v-model="editorContent" rows="14"
                    placeholder="正文(生成后在此实时编辑)…" style="width:100%"></textarea>
          <div class="muted" style="margin-top:6px">{{ wordCount }} 字</div>
          <div class="stub-wrap" style="margin-top:10px">
            <button class="btn stub" disabled>开始生成</button>
            <button class="btn primary" @click="saveDraft">存草稿</button>
            <button class="btn" v-if="editingId" @click="newDraft">新建</button>
            <div class="stub-tip">真生成走 <code>python cli.py flows run {{ template || '&lt;工作流&gt;' }} --auto</code>;
              生成模块的真实编排执行本期留桩</div>
          </div>
        </div>
      </div>

      <!-- 右: 草稿箱 -->
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
  </div>`,
};
