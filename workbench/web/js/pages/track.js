/* 追踪页(2026-09-11 优化): 只追踪用户自己设的账号, 不做管理——
   X 模块 = 自选追踪(日快照: 粉丝/增粉/更新/流量曲线);
   YouTube 模块 = 追踪已设频道(订阅/增粉/更新/流量曲线), 管理(添加/启停/删除)在视频页【账号管理】;
   X 池管理已归图文页【账号管理】。发布与通讯录模块不变。 */

window.WB = window.WB || {};
WB.pages = WB.pages || {};

WB.pages.track = {
  data() {
    return {
      sec: "x",
      /* ── X 模块: 自选追踪(原图文页「账号追踪」) ── */
      xtrack: { accounts: [], count: 0, enabled_n: 0, status: {}, q: "", err: "", loading: false },
      xtAdd: { input: "", note: "", busy: false },
      xtBusy: "",                      /* 行级删除/开关进行中的 handle */
      xt: { busy: false, timer: null },  /* 统一采集按钮 + 轮询 */
      xtSel: "",                       /* 详情展开的 handle(""=收起) */
      xtDetail: { loading: false, account: null, series: [] },
      xtChart: { metric: "followers", range: 30 },
      xtMetrics: [["followers", "粉丝量"], ["delta", "每日增粉"],
                  ["updates", "每日更新"], ["views", "每日流量"]],
      xtRanges: [[7, "近7天"], [30, "近30天"], [90, "近90天"], [365, "近一年"], [9999, "全部"]],
      /* ── YouTube 模块(原视频页「追踪账号」; 紧凑表替代大卡片) ── */
      chs: [], chMeta: null, chQ: "", chBusyId: "",
      chForm: { input: "", note: "" }, adding: false,
      ytCollecting: false, ytCollectPoll: null,
      disposed: false,
      /* YTB 频道行内展开曲线(对齐 X 追踪的 accordion 图表) */
      ytbSel: "", ytbBusy: "",
      ytbDetail: { loading: false, raw: null },
      ytbChart: { metric: "views7d", range: 30 },
      ytbMetrics: [["views7d", "近7日总流量"], ["subs", "订阅"], ["subs_delta", "订阅增粉"],
                   ["updates", "每日更新"], ["latest", "最新视频播放"]],
      ytbRanges: [[7, "近7天"], [30, "近30天"], [90, "近90天"], [365, "近一年"], [9999, "全部"]],
      /* ── 发布与通讯录 ── */
      accounts: [], published: [], stats: null,
      form: { platform: "雪球", account: "", note: "" },
      platforms: ["雪球", "东方财富", "富途", "长桥", "微博", "B站", "抖音",
                  "知乎", "公众号", "头条", "X", "Threads", "YouTube", "其他"],
      showForm: false,
    };
  },
  watch: {
    "xtChart.range"() { if (this.xtSel) this.loadXtDetail(); },
    "ytbChart.range"() { if (this.ytbSel) this.loadYtbSeries(); },
  },
  computed: {
    /* 自选追踪行过滤: 关键词(名称/handle) */
    xtrackRows() {
      const q = this.xtrack.q.trim().toLowerCase();
      if (!q) return this.xtrack.accounts;
      return this.xtrack.accounts.filter((a) =>
        (a.name || "").toLowerCase().includes(q) ||
        (a.handle || "").toLowerCase().includes(q));
    },
    /* 追踪大图几何: 折线(粉丝量)或柱(增粉/更新/流量), viewBox 760x240。全手工 SVG(免图表库)。 */
    xtGeom() {
      const s = this.xtDetail.series || [];
      const key = this.xtChart.metric;
      if (!s.length) return null;
      const padL = 56, padR = 16, padT = 16, padB = 28;
      const W = 760, H = 240, plotW = W - padL - padR, plotH = H - padT - padB;
      const n = s.length;
      const vals = s.map((r) => Number(r[key]) || 0);
      const barMode = key !== "followers";
      let yMin = Math.min(...vals), yMax = Math.max(...vals);
      if (barMode) yMin = Math.min(0, yMin);
      if (yMin === yMax) { yMin -= 1; yMax += 1; }             // 常量序列防除零
      const spanY = yMax - yMin;
      yMax += spanY * 0.08; yMin -= spanY * 0.04;
      const x = (i) => padL + (n === 1 ? plotW / 2 : (i * plotW) / (n - 1));
      const y = (v) => padT + plotH * (1 - (v - yMin) / (yMax - yMin));
      const pts = vals.map((v, i) => x(i).toFixed(1) + "," + y(v).toFixed(1)).join(" ");
      const bars = barMode ? vals.map((v, i) => {
        const bw = Math.max(2, Math.min(26, (plotW / n) * 0.62));
        const yv = y(v), y0 = y(0);
        return { x: +(x(i) - bw / 2).toFixed(1), y: +Math.min(yv, y0).toFixed(1),
                 w: +bw.toFixed(1), h: +Math.max(1, Math.abs(yv - y0)).toFixed(1),
                 neg: v < 0, val: v, d: s[i].date,
                 title: `${s[i].date}  ${v >= 0 ? "+" : ""}${v.toLocaleString()}` };
      }) : [];
      const area = barMode ? "" : pts + " " + x(n - 1).toFixed(1) + "," + y(yMin).toFixed(1) +
        " " + x(0).toFixed(1) + "," + y(yMin).toFixed(1);
      const fmt = (v) => this.fmtN(Math.round(v));
      /* 恒定序列(冷启动基线/全零增粉)单刻度画中线; 非恒定但 span 极小时按标签去重 */
      const flat = vals.every((v) => v === vals[0]);
      const yTicks = (flat
        ? [vals[0]]
        : [yMin + (yMax - yMin) * 0.04, (yMin + yMax) / 2, yMax - (yMax - yMin) * 0.04])
        .map((v) => ({ y: +y(v).toFixed(1), label: fmt(v) }))
        .filter((t, i, arr) => i === 0 || t.label !== arr[i - 1].label);
      const mid = Math.floor((n - 1) / 2);
      const xTicks = n >= 3
        ? [0, mid, n - 1].map((i) => ({ x: +x(i).toFixed(1), label: s[i].date.slice(5) }))
        : s.map((r, i) => ({ x: +x(i).toFixed(1), label: r.date.slice(5) }));
      const dots = barMode ? [] : vals.map((v, i) => ({
        cx: +x(i).toFixed(1), cy: +y(v).toFixed(1),
        title: `${s[i].date}  ${v.toLocaleString()}` }));
      return { pts, area, bars, dots, yTicks, xTicks, zeroY: barMode ? +y(0).toFixed(1) : null,
               single: n === 1, W, H };
    },
    /* X 追踪图读数: 最后非空点(日期+数值+较前点差), 长期视图下一眼见当前状态 */
    xtLatest() {
      const s = this.xtDetail.series || [];
      const key = this.xtChart.metric;
      for (let i = s.length - 1; i >= 0; i--) {
        const v = Number(s[i][key]);
        if (s[i][key] != null && !isNaN(v)) {
          const prev = i > 0 && s[i - 1][key] != null ? v - Number(s[i - 1][key]) : null;
          return { date: s[i].date, v, delta: prev };
        }
      }
      return null;
    },
    /* YTB 追踪图读数(同款) */
    ytbLatest() {
      const s = this.ytbSeries.filter((p) => p && p.date && p.v != null);
      if (!s.length) return null;
      const v = Number(s[s.length - 1].v);
      const prev = s.length > 1 ? v - Number(s[s.length - 2].v) : null;
      return { date: s[s.length - 1].date, v, delta: prev };
    },
    /* YouTube 频道行过滤: 关键词(频道名/handle/备注/频道ID) */
    chRows() {
      const q = (this.chQ || "").trim().toLowerCase();
      if (!q) return this.chs;
      return this.chs.filter((c) =>
        (c.title || "").toLowerCase().includes(q) ||
        (c.handle || "").toLowerCase().includes(q) ||
        (c.note || "").toLowerCase().includes(q) ||
        (c.channel_id || "").toLowerCase().includes(q));
    },
    /* YTB 曲线当前指标序列: raw → [{date, v}] */
    ytbSeries() {
      const raw = this.ytbDetail.raw;
      if (!raw) return [];
      const m = this.ytbChart.metric;
      if (m === "latest") return raw.latest_series || [];
      return raw[m] || [];
    },
    /* YTB 大图几何: 折线(流量/订阅)或柱(更新/增粉), 与 X 追踪图同风格。null=缺口跳过。 */
    ytbGeom() {
      const s = this.ytbSeries.filter((p) => p && p.date);
      if (!s.length) return null;
      const barMode = this.ytbChart.metric === "updates" || this.ytbChart.metric === "subs_delta";
      const padL = 56, padR = 16, padT = 16, padB = 28;
      const W = 760, H = 240, plotW = W - padL - padR, plotH = H - padT - padB;
      const n = s.length;
      const x = (i) => padL + (n === 1 ? plotW / 2 : (i * plotW) / (n - 1));
      const known = s.map((p, i) => ({ i, v: p.v == null ? null : Number(p.v) })).filter((p) => p.v != null);
      if (!known.length) return null;
      const vals = known.map((p) => p.v);
      let yMin = Math.min(...vals), yMax = Math.max(...vals);
      if (barMode) yMin = Math.min(0, yMin);
      if (yMin === yMax) { yMin -= 1; yMax += 1; }
      const spanY = yMax - yMin;
      yMax += spanY * 0.08; yMin -= spanY * 0.04;
      const y = (v) => padT + plotH * (1 - (v - yMin) / (yMax - yMin));
      const pts = known.map((p) => x(p.i).toFixed(1) + "," + y(p.v).toFixed(1)).join(" ");
      const bars = barMode ? known.map((p) => {
        const bw = Math.max(2, Math.min(26, (plotW / n) * 0.62));
        const yv = y(p.v), y0 = y(0);
        return { x: +(x(p.i) - bw / 2).toFixed(1), y: +Math.min(yv, y0).toFixed(1),
                 w: +bw.toFixed(1), h: +Math.max(1, Math.abs(yv - y0)).toFixed(1),
                 neg: p.v < 0, title: `${s[p.i].date}  ${p.v >= 0 ? "+" : ""}${p.v.toLocaleString()}` };
      }) : [];
      const area = barMode ? "" : pts + " " + x(known[known.length - 1].i).toFixed(1) + "," + y(yMin).toFixed(1) +
        " " + x(known[0].i).toFixed(1) + "," + y(yMin).toFixed(1);
      const fmt = (v) => this.fmtN(Math.round(v));
      const flat = vals.every((v) => v === vals[0]);
      const yTicks = (flat
        ? [vals[0]]
        : [yMin + (yMax - yMin) * 0.04, (yMin + yMax) / 2, yMax - (yMax - yMin) * 0.04])
        .map((v) => ({ y: +y(v).toFixed(1), label: fmt(v) }))
        .filter((t, i, arr) => i === 0 || t.label !== arr[i - 1].label);
      const mid = Math.floor((n - 1) / 2);
      const xTicks = n >= 3
        ? [0, mid, n - 1].map((i) => ({ x: +x(i).toFixed(1), label: s[i].date.slice(5) }))
        : s.map((p, i) => ({ x: +x(i).toFixed(1), label: p.date.slice(5) }));
      const dots = barMode ? [] : known.map((p) => ({
        cx: +x(p.i).toFixed(1), cy: +y(p.v).toFixed(1),
        title: `${s[p.i].date}  ${p.v.toLocaleString()}` }));
      return { pts, area, bars, dots, yTicks, xTicks, zeroY: barMode ? +y(0).toFixed(1) : null, W, H };
    },
  },
  methods: {
    fmtFol(n) {
      return n >= 1e4 ? (n / 1e4).toFixed(1).replace(/\.0$/, "") + "万" : String(n);
    },
    fmtN(n) {
      if (n == null) return "—";
      if (n >= 1e8) return (n / 1e8).toFixed(1).replace(/\.0$/, "") + "亿";
      if (n >= 1e4) return (n / 1e4).toFixed(1).replace(/\.0$/, "") + "万";
      return String(Math.round(n));
    },
    deltaCls(v) { return v == null ? "" : v > 0 ? "var(--green)" : v < 0 ? "var(--red)" : ""; },
    deltaText(v) {
      if (v == null) return "—";
      return (v > 0 ? "+" : "") + this.fmtN(v);
    },
    registerSubs() {
      if (!WB.shell) return;
      if (!location.hash.replace(/^#/, "").startsWith("/track")) return;  // 迟到的异步回调不得覆盖别的页面
      const I = (p) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + p + "</svg>";
      WB.shell.setSubs([
        { id: "x", title: "X 账号", cnt: this.xtrack.count || "",
          icon: I('<path d="M4 4l16 16M20 4L4 20"/>'),
          onPick: () => { this.sec = "x"; this.loadXtrack(); } },
        { id: "ytb", title: "YouTube", cnt: this.chs.length || "",
          icon: I('<polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/>'),
          onPick: () => { this.sec = "ytb"; this.loadChannels(); } },
        { id: "misc", title: "发布与通讯录", cnt: this.accounts.length || "",
          icon: I('<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'),
          onPick: () => { this.sec = "misc"; } },
      ], this.sec);
    },
    /* ── X 自选追踪: 粉丝/增粉/更新/流量日快照(采集走 CLI 子进程, 端点零外呼) ── */
    async loadXtrack() {
      this.xtrack.loading = true;
      try {
        const d = await WB.api.get("/xt/overview");
        if (this.disposed) return;                 // 卸载后迟到响应: 不回写也不再挂轮询
        this.xtrack.accounts = d.accounts || [];
        this.xtrack.count = d.count || 0;
        this.xtrack.enabled_n = d.enabled_n || 0;
        this.xtrack.status = d.status || {};
        this.xtrack.err = "";
      } catch (e) {
        if (this.disposed) return;
        this.xtrack.accounts = [];
        this.xtrack.err = (e && e.error) || "接口不可用";
      }
      this.xtrack.loading = false;
      this.registerSubs();
      if ((this.xtrack.status || {}).running && !this.disposed) this.watchXt();   // 打开页面时已在跑(计划任务拉的)
    },
    watchXt() {          // 采集中轮询(退避 4s→12s): 结束后刷新列表与已展开详情
      if (this.xt.timer || this.disposed) return;
      this.xt.delay = 4000;
      const step = async () => {
        if (this.disposed) { this.xt.timer = null; return; }
        try {
          const d = await WB.api.get("/xt/overview");
          if (this.disposed) { this.xt.timer = null; return; }
          this.xtrack.status = d.status || {};
          this.xtrack.accounts = d.accounts || [];
          if (!(d.status || {}).running) {
            this.xt.timer = null;
            this.loadXtrack();
            if (this.xtSel) this.loadXtDetail();
            return;
          }
        } catch (e) {}
        this.xt.delay = Math.min(12000, this.xt.delay * 2);
        this.xt.timer = setTimeout(step, this.xt.delay);
      };
      this.xt.timer = setTimeout(step, this.xt.delay);
    },
    async xtCollectNow() {   // X 模块统一采集: 一轮拉全部启用账号
      if (this.xt.busy) return;
      this.xt.busy = true;
      try {
        await WB.api.post("/xt/collect", {});
        this.xtrack.status = { ...(this.xtrack.status || {}), running: true };
        WB.toast("采集已启动");
        this.watchXt();
      } catch (e) {
        if (e.status === 409) { this.watchXt(); }
        else WB.toast((e && e.error) || "拉起失败, 看 data/xtrack_collect.log");
      }
      this.xt.busy = false;
    },
    async xtScheduleToggle() {
      if (this.xt.busy) return;
      this.xt.busy = true;
      try {
        const d = await WB.api.post("/xt/schedule", { on: !((this.xtrack.status || {}).scheduled) });
        this.xtrack.status = { ...(this.xtrack.status || {}), scheduled: !!d.scheduled };
        WB.toast(d.msg || (d.ok ? "已更新" : "登记失败"));
      } catch (e) { WB.toast((e && e.error) || "登记失败"); }
      this.xt.busy = false;
    },
    async xtAddSubmit() {
      if (this.xtAdd.busy || !this.xtAdd.input.trim()) return;
      this.xtAdd.busy = true;
      try {
        await WB.api.post("/xt/accounts", { input: this.xtAdd.input, note: this.xtAdd.note });
        WB.toast("已加入追踪, 点「立即采集」拉首份数据");
        this.xtAdd = { input: "", note: "", busy: false };
        this.loadXtrack();
      } catch (e) { WB.toast((e && e.error) + (e.hint ? " —— " + e.hint : "") || "添加失败"); }
      this.xtAdd.busy = false;
    },
    async xtImportFollowed() {
      if (this.xtAdd.busy) return;
      this.xtAdd.busy = true;
      try {
        const d = await WB.api.post("/xt/import-followed", {});
        WB.toast(d.imported.length
          ? `已导入 ${d.imported.length} 个关注账号` : "关注列表没有可导入的新账号");
        this.loadXtrack();
      } catch (e) { WB.toast((e && e.error) || "导入失败"); }
      this.xtAdd.busy = false;
    },
    async xtToggle(a) {
      this.xtBusy = a.handle;
      try {
        await WB.api.post("/xt/accounts/" + a.handle + "/enabled", { on: !a.enabled });
        a.enabled = !a.enabled;
      } catch (e) { WB.toast("切换失败: " + (e.error || "")); }
      this.xtBusy = "";
    },
    async xtDel(a) {
      if (!confirm(`停止追踪 @${a.handle} ?\n其历史快照将一并删除, 无法恢复。`)) return;
      this.xtBusy = a.handle;
      try {
        await WB.api.del("/xt/accounts/" + a.handle);
        if (this.xtSel === a.handle) { this.xtSel = ""; this.xtDetail = { loading: false, account: null, series: [] }; }
        WB.toast(`已停止追踪 @${a.handle}`);
        this.loadXtrack();
      } catch (e) { WB.toast("删除失败: " + (e.error || "")); }
      this.xtBusy = "";
    },
    openXt(a) {
      this.xtSel = this.xtSel === a.handle ? "" : a.handle;
      if (this.xtSel) {
        this.loadXtDetail();
        this.$nextTick(() => this.$el.querySelector(".xt-detail")
          ?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
      }
    },
    async loadXtDetail() {
      this.xtDetail.loading = true;
      const h = this.xtSel;                        // 快照句柄: 快速切换 A→B 时丢弃 A 的过期响应
      try {
        const d = await WB.api.get("/xt/accounts/" + h + "?days=" + this.xtChart.range);
        if (h !== this.xtSel) return;
        this.xtDetail.account = d.account || null;
        this.xtDetail.series = d.series || [];
      } catch (e) { if (h === this.xtSel) this.xtDetail.series = []; }
      if (h === this.xtSel) this.xtDetail.loading = false;
    },
    /* 行内迷你粉丝曲线(近30点; 不足2点不画) */
    xtSparkPts(spark) {
      const a = (spark || []).map(Number).filter((v) => !isNaN(v));
      if (a.length < 2) return "";
      const min = Math.min(...a), max = Math.max(...a), span = (max - min) || 1;
      return a.map((v, i) =>
        (i * (100 / (a.length - 1))).toFixed(1) + "," + (24 - ((v - min) / span) * 22).toFixed(1)
      ).join(" ");
    },
    /* ── YouTube 追踪(追踪数据面; 添加/备注管理在视频页【账号管理】, 本页保留采集启停与删除) ── */
    async toggleCh(c) {
      this.chBusyId = c.id;
      try {
        const d = await WB.api.post("/yt-own/channels/" + c.id + "/enabled", { on: c.enabled === false });
        c.enabled = d.enabled;
      } catch (e) { WB.toast(e.error); }
      this.chBusyId = "";
    },
    async delCh(c) {
      if (!confirm("删除追踪 " + (c.title || c.input) + " ?\n已采集的历史数据保留在本地, 但不再更新")) return;
      try {
        const d = await WB.api.del("/yt-own/channels/" + c.id);
        this.chs = d.channels;
        if (this.ytbSel === c.channel_id) this.ytbSel = "";
        WB.toast("已删除");
      } catch (e) { WB.toast(e.error); }
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
      if (!this.chForm.input.trim()) { WB.toast("请粘贴自己频道的 @handle / 链接 / 频道名"); return; }
      this.adding = true;
      try {
        const d = await WB.api.post("/yt-own/channels",
          { input: this.chForm.input, note: this.chForm.note });
        this.chs = d.channels;
        WB.toast("已添加" + (d.added.title ? ": " + d.added.title : "(下一轮采集时解析)"));
        this.chForm.input = ""; this.chForm.note = "";
        if (this.chMeta && this.chMeta.configured) this.ytCollectNow();  // 让新账号尽快出数据
      } catch (e) { WB.toast(e.error + (e.hint ? " — " + e.hint : "")); }
      this.adding = false;
      this.registerSubs();
    },
    async loadChannels() {
      try {
        const d = await WB.api.get("/yt-own/channels");
        this.chs = d.channels; this.chMeta = d.meta;
      } catch (e) {}
      this.registerSubs();
    },
    /* YTB 行内展开曲线(对齐 X 追踪 accordion): 点行开/收, 指标与范围 chips 切换 */
    openYtb(c) {
      this.ytbSel = this.ytbSel === c.channel_id ? "" : c.channel_id;
      if (this.ytbSel) {
        this.loadYtbSeries();
        this.$nextTick(() => this.$el.querySelector(".ytb-detail")
          ?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
      }
    },
    async loadYtbSeries() {
      this.ytbDetail.loading = true;
      const cid = this.ytbSel;                     // 快速切换时丢弃过期响应
      try {
        const d = await WB.api.get("/yt-own/channels/" + cid + "/series?days=" + this.ytbChart.range);
        if (cid !== this.ytbSel) return;
        this.ytbDetail.raw = d;
      } catch (e) { if (cid === this.ytbSel) this.ytbDetail.raw = null; }
      if (cid === this.ytbSel) this.ytbDetail.loading = false;
    },
    ytbLatestTitle() { return (this.ytbDetail.raw || {}).latest ? this.ytbDetail.raw.latest.title : ""; },
    async ytCollectNow() {   // YouTube 模块统一采集: 一轮拉全部启用频道
      if (this.ytCollecting) return;
      this.ytCollecting = true;
      try {
        await WB.api.post("/yt/collect", {});
        this.pollYtCollect();
      } catch (e) {
        WB.toast(e.error + (e.hint ? " — " + e.hint : ""));
        this.ytCollecting = false;
      }
    },
    pollYtCollect() {                     // 采集为异步 spawn, 每 3s 轮询状态直到收尾
      clearTimeout(this.ytCollectPoll);
      const tick = async () => {
        if (this.disposed) return;
        let st = null;
        try { st = await WB.api.get("/yt/status"); } catch (e) {}
        if (st && !st.running) {
          this.ytCollecting = false;
          const rep = (st.last_report) || {};
          if (st.last_exit === 4) WB.toast("未配置 YouTube API Key — 到设置页填写");
          else if (st.last_exit === 3) WB.toast("YouTube 配额熔断, 已保留旧数据");
          else WB.toast("采集完成: 频道 " + (rep.channels_ok != null ? rep.channels_ok : "-")
            + " · 新视频 " + (rep.new_videos != null ? rep.new_videos : "-")
            + " · 快照 " + (rep.snapshotted != null ? rep.snapshotted : "-"));
          this.loadChannels();
          return;
        }
        this.ytCollectPoll = setTimeout(tick, 3000);
      };
      this.ytCollectPoll = setTimeout(tick, 3000);
    },
    /* ── 通讯录 + 发布账本(旧追踪页职能保留) ── */
    async addAccount() {
      if (!this.form.account.trim()) { WB.toast("请填写账号名"); return; }
      const d = await WB.api.post("/track/accounts", this.form);
      this.accounts = d.accounts;
      this.form.account = ""; this.form.note = ""; this.showForm = false;
      WB.toast("已添加追踪账号");
    },
    async removeAccount(i) {
      const d = await WB.api.del("/track/accounts/" + i);
      this.accounts = d.accounts;
    },
  },
  async mounted() {
    this.registerSubs();
    this.loadXtrack(); this.loadChannels();
    try { this.accounts = (await WB.api.get("/track/accounts")).accounts; } catch (e) {}
    try {
      const d = await WB.api.get("/ledger");
      this.published = d.published; this.stats = d.stats;
    } catch (e) {}
    WB.api.get("/yt/status").then((st) => {          // 页面打开时已在采集 → 续上轮询
      if (this.disposed) return;                     // 迟到响应不得重建轮询
      if (st && st.running) { this.ytCollecting = true; this.pollYtCollect(); }
    }).catch(() => {});
  },
  unmounted() {
    this.disposed = true;
    if (WB.shell) WB.shell.setSubs([]);
    if (this.xt.timer) { clearTimeout(this.xt.timer); this.xt.timer = null; }
    clearTimeout(this.ytCollectPoll);
  },
  template: `
  <div>
    <!-- ═══ 模块一: X 账号 ═══ -->
    <div v-show="sec==='x'">
      <div class="card">
        <h3>自选追踪({{ xtrack.count || 0 }})
          <span class="muted">启用 {{ xtrack.enabled_n || 0 }} · 显示 {{ xtrackRows.length }}</span>
          <span v-if="xtrack.err" class="badge red" style="margin-left:8px">{{ xtrack.err }}</span></h3>
        <div class="feed-toolbar">
          <input type="text" v-model="xtAdd.input" @keyup.enter="xtAddSubmit"
                 placeholder="@handle 或 x.com/账号 链接" style="width:210px" :disabled="xtAdd.busy">
          <input type="text" v-model="xtAdd.note" @keyup.enter="xtAddSubmit"
                 placeholder="备注(可选)" style="width:140px" :disabled="xtAdd.busy">
          <button class="btn primary" @click="xtAddSubmit" :disabled="xtAdd.busy">添加</button>
          <button class="btn" @click="xtImportFollowed" :disabled="xtAdd.busy"
                  title="把图文页【账号管理】里标记为关注的账号批量加入追踪">从关注导入</button>
          <span style="flex:1"></span>
          <input type="text" v-model="xtrack.q" placeholder="搜索(名称/handle)" style="width:150px">
          <button class="btn" @click="xtScheduleToggle" :disabled="xt.busy"
                  :title="(xtrack.status.scheduled ? '已开启每小时自动采集, 点击停止' : '登记 Windows 计划任务, 每小时自动采集')">
            {{ xtrack.status.scheduled ? '⏰ 定时中' : '⏰ 定时' }}</button>
          <button class="btn" @click="loadXtrack">{{ xtrack.loading ? '刷新中…' : '刷新' }}</button>
          <button class="btn primary" @click="xtCollectNow" :disabled="xt.busy || xtrack.status.running">
            {{ xtrack.status.running ? '采集中…' : '⟳ 立即采集' }}</button>
        </div>
        <div class="muted" style="margin:6px 0 10px">
          统一采集: 一次拉取全部启用账号的快照。口径: 粉丝=每日快照 · 增粉=较前一日差分 ·
          更新=当日本人发帖+回复(转推不计) · 流量=当日新帖浏览量合计。
          数据经 FxTwitter 免登录通路<span v-if="xtrack.status.finished_at">;
          上轮采集 {{ xtrack.status.finished_at }}<template v-if="xtrack.status.data_age_min != null">(距今 {{ xtrack.status.data_age_min }} 分钟)</template></span><template v-if="xtrack.status.running">;
          <b style="color:var(--accent)">采集中…</b></template></div>

        <table class="tbl">
          <thead><tr>
            <th>账号</th><th>粉丝</th><th>今日增粉</th><th>近7日</th>
            <th>今日更新</th><th>今日流量</th><th>近30日粉丝</th><th>采集</th><th>操作</th>
          </tr></thead>
          <tbody>
            <template v-for="a in xtrackRows" :key="a.handle">
            <tr :class="{sel: xtSel === a.handle}"
                :style="{opacity: a.enabled ? '' : .5, cursor: 'pointer'}"
                @click="openXt(a)">
              <td>
                <div style="display:flex;align-items:center;gap:8px">
                  <img v-if="a.avatar" :src="a.avatar" alt=""
                       style="width:26px;height:26px;border-radius:50%">
                  <div>
                    <b>{{ a.name || '@'+a.handle }}</b>
                    <span v-if="a.verified" class="badge blue" style="margin-left:4px">✓</span>
                    <div class="muted" style="font-size:11px">@{{ a.handle }}<template v-if="a.note"> · {{ a.note }}</template></div>
                  </div>
                </div>
                <div v-if="a.error" class="badge red" style="margin-top:4px;white-space:normal"
                     :title="a.error + ' (' + (a.error_at || '') + ')'">上轮失败: {{ a.error.slice(0, 30) }}</div>
              </td>
              <td class="mono">{{ a.followers ? fmtFol(a.followers) : '—' }}</td>
              <td class="mono" :style="{color: deltaCls(a.delta_1d)}">{{ deltaText(a.delta_1d) }}</td>
              <td class="mono" :style="{color: deltaCls(a.delta_7d)}">{{ deltaText(a.delta_7d) }}</td>
              <td class="mono">{{ a.updates_1d || '—' }}<span v-if="a.replies_1d" class="muted" style="font-size:11px"> (回复{{ a.replies_1d }})</span></td>
              <td class="mono">{{ a.views_1d ? fmtN(a.views_1d) : '—' }}</td>
              <td style="width:110px">
                <svg v-if="xtSparkPts(a.spark)" viewBox="0 0 100 26" width="100" height="26">
                  <polyline :points="xtSparkPts(a.spark)" fill="none"
                            stroke="var(--accent)" stroke-width="1.5"/>
                </svg>
                <span v-else class="muted">—</span></td>
              <td><span class="switch" :class="{on: a.enabled, busy: xtBusy === a.handle}"
                    role="switch" tabindex="0" :aria-checked="a.enabled ? 'true' : 'false'"
                    :title="a.enabled ? '停用(保留数据, 暂停采集)' : '恢复采集'"
                    @click.stop="xtToggle(a)" @keydown.enter.stop="xtToggle(a)"></span></td>
              <td>
                <span class="act" style="color:var(--accent);cursor:pointer" @click.stop="openXt(a)">曲线</span>
                <span class="act" style="color:var(--red);cursor:pointer;margin-left:8px"
                      @click.stop="xtDel(a)">删除</span>
                <div class="muted" style="font-size:10.5px" v-if="a.days_n">{{ a.days_n }} 天快照</div>
              </td>
            </tr>
            <!-- 行内展开(accordion): 曲线详情嵌在触发行正下方 -->
            <tr v-if="xtSel === a.handle" class="xt-detail-row">
              <td colspan="9">
                <div class="xt-detail">
                  <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap">
                    <img v-if="xtDetail.account && xtDetail.account.avatar" :src="xtDetail.account.avatar" alt=""
                         style="width:34px;height:34px;border-radius:50%">
                    <b>{{ a.name || '@'+a.handle }}</b>
                    <a class="muted" :href="'https://x.com/'+a.handle" target="_blank" rel="noopener">@{{ a.handle }}</a>
                    <span class="mono" style="font-size:14px">粉 {{ fmtN(a.followers) }}</span>
                    <span :style="{color: deltaCls(a.delta_7d)}">近7日 {{ deltaText(a.delta_7d) }}</span>
                    <span class="muted" v-if="a.note">{{ a.note }}</span>
                    <span style="flex:1"></span>
                    <button class="btn" @click.stop="xtSel=''">收起</button>
                  </div>
                  <div class="feed-toolbar" style="margin:10px 0 4px">
                    <span v-for="[m, t] in xtMetrics" :key="m" class="chip" :class="{on: xtChart.metric===m}"
                          @click="xtChart.metric=m">{{ t }}</span>
                    <span style="flex:1"></span>
                    <span v-for="[r, t] in xtRanges" :key="r" class="chip" :class="{on: xtChart.range===r}"
                          @click="xtChart.range=r">{{ t }}</span>
                  </div>
                  <div v-if="xtLatest && !xtDetail.loading" class="mono" style="font-size:12.5px;margin-bottom:4px">
                    最新 {{ xtLatest.date }} · {{ xtLatest.v.toLocaleString() }}
                    <span v-if="xtLatest.delta != null" :style="{color: deltaCls(xtLatest.delta)}">({{ xtLatest.delta >= 0 ? '+' : '' }}{{ fmtN(xtLatest.delta) }})</span></div>
                  <div v-if="xtDetail.loading" class="muted">加载中…</div>
                  <div v-else-if="!xtDetail.series.length" class="muted">暂无快照 — 点右上「立即采集」出数</div>
                  <svg v-else-if="xtGeom" :viewBox="'0 0 '+xtGeom.W+' '+xtGeom.H"
                       style="width:100%;height:auto;display:block">
                    <g v-for="(t, i) in xtGeom.yTicks" :key="'y'+i">
                      <line x1="56" x2="744" :y1="t.y" :y2="t.y" stroke="currentColor" stroke-opacity=".12"/>
                      <text :x="52" :y="t.y+4" text-anchor="end" font-size="11"
                            fill="currentColor" fill-opacity=".55">{{ t.label }}</text>
                    </g>
                    <g v-for="(t, i) in xtGeom.xTicks" :key="'x'+i">
                      <text :x="t.x" y="234" text-anchor="middle" font-size="11"
                            fill="currentColor" fill-opacity=".55">{{ t.label }}</text>
                    </g>
                    <template v-if="xtGeom.bars.length">
                      <line v-if="xtGeom.zeroY != null && xtGeom.zeroY > 16 && xtGeom.zeroY < 212"
                            x1="56" x2="744" :y1="xtGeom.zeroY" :y2="xtGeom.zeroY"
                            stroke="currentColor" stroke-opacity=".3"/>
                      <rect v-for="(b, i) in xtGeom.bars" :key="'b'+i" :x="b.x" :y="b.y" :width="b.w"
                            :height="b.h" rx="2" opacity=".85"
                            :fill="b.neg ? 'var(--red)' : 'var(--green)'"><title>{{ b.title }}</title></rect>
                    </template>
                    <template v-else>
                      <polygon :points="xtGeom.area" fill="var(--accent)" opacity=".12"/>
                      <polyline :points="xtGeom.pts" fill="none" stroke="var(--accent)" stroke-width="2"
                                stroke-linejoin="round"/>
                      <circle v-for="(d, i) in xtGeom.dots" :key="'d'+i" :cx="d.cx" :cy="d.cy" r="2.6"
                              fill="var(--accent)"><title>{{ d.title }}</title></circle>
                    </template>
                  </svg>
                </div>
              </td>
            </tr>
            </template>
            <tr v-if="!xtrackRows.length && !xtrack.loading">
              <td colspan="9" class="muted" style="padding:18px 8px">
                {{ xtrack.count ? '无匹配账号' :
                  '还没有追踪账号 — 上方输入 @handle 添加, 或点「从关注导入」; 添加后点「立即采集」出数' }}</td></tr>
          </tbody>
        </table>
      </div>

    </div>

    <!-- ═══ 模块二: YouTube ═══ -->
    <div v-show="sec==='ytb'">
      <div class="card">
        <h3>YouTube 我的频道({{ chs.length }})
          <span class="muted" style="font-weight:400">只追踪你自己的账号; 与视频页【账号管理】独立</span>
          <span v-if="chMeta && !chMeta.configured" class="muted" style="font-weight:400">
            · 未配 Key, 添加后待解析</span>
          <span style="float:right"><button class="btn" @click="loadChannels">刷新</button></span></h3>
        <div class="feed-toolbar">
          <input type="text" v-model="chForm.input" @keyup.enter="addChannel"
                 placeholder="你自己频道的 youtube.com/@handle 链接或频道名" style="width:300px" :disabled="adding">
          <input type="text" v-model="chForm.note" @keyup.enter="addChannel"
                 placeholder="备注(可选)" style="width:140px" :disabled="adding">
          <button class="btn primary" @click="addChannel" :disabled="adding">{{ adding ? '保存中…' : '添加' }}</button>
          <input type="text" v-model="chQ" placeholder="搜索" style="width:130px">
          <span style="flex:1"></span>
          <button class="btn primary" @click="ytCollectNow" :disabled="ytCollecting"
                  :title="ytCollecting ? '采集进行中' : '拉取全部启用频道的最新统计'">{{ ytCollecting ? '采集中…' : '⟳ 立即采集' }}</button>
        </div>
        <div class="muted" style="margin:6px 0 10px">
          统一采集: 一次拉取全部启用频道的最新统计(计划任务每天一次, 或点「立即采集」)。
          这里只追踪你自己的频道(订阅/增粉/更新/流量曲线); 他人频道的热点采集在视频页【账号管理】——两边独立存储。</div>
        <div v-if="!chs.length" class="muted" style="padding:8px 0">
          尚未添加自己的频道 —— 上方粘贴自己频道的链接或 @handle; 添加后点「立即采集」出数。</div>
        <table v-else class="tbl">
          <thead><tr><th>频道</th><th>订阅</th><th>今日增粉</th><th>今日更新</th>
            <th>最新视频流量</th><th>近7日总流量</th><th>7日流量变化</th><th>采集</th><th>操作</th></tr></thead>
          <tbody>
            <template v-for="c in chRows" :key="c.id">
            <tr :class="{sel: ytbSel === c.channel_id}"
                :style="{opacity: c.enabled !== false ? '' : .5, cursor: 'pointer'}"
                @click="openYtb(c)">
              <td>
                <b>{{ c.title || c.input }}</b>
                <span v-if="c.resolve_status === 'pending'" class="badge" style="margin-left:4px">待解析</span>
                <span v-if="c.resolve_status === 'failed'" class="badge red" style="margin-left:4px"
                      :title="c.resolve_error">解析失败</span>
                <div class="muted mono" style="font-size:10.5px">{{ c.channel_id || '待解析' }}<span v-if="c.note" class="muted" style="font-family:inherit"> · {{ c.note }}</span></div>
                <div v-if="c.resolve_error && c.resolve_status !== 'failed'" class="badge red" style="margin-top:4px;white-space:normal"
                     :title="c.resolve_error">上轮异常: {{ c.resolve_error.slice(0, 30) }}</div></td>
              <td class="mono">{{ c.subs != null ? fmtN(c.subs) + '(≈)' : '—' }}</td>
              <td class="mono" :style="{color: deltaCls((c.stats || {}).subs_delta_1d)}">{{ deltaText((c.stats || {}).subs_delta_1d) }}</td>
              <td class="mono">{{ (c.stats || {}).updates_1d || '—' }}</td>
              <td class="mono" :title="(c.stats || {}).latest_title">{{ (c.stats || {}).latest_views != null ? fmtN(c.stats.latest_views) : '—' }}</td>
              <td class="mono">{{ (c.stats || {}).views_7d != null ? fmtN(c.stats.views_7d) : '—' }}</td>
              <td class="mono" :style="{color: deltaCls((c.stats || {}).views_7d_delta)}">{{ deltaText((c.stats || {}).views_7d_delta) }}</td>
              <td><span class="switch" :class="{on: c.enabled !== false, busy: chBusyId === c.id}"
                    role="switch" tabindex="0" :aria-checked="c.enabled === false ? 'false' : 'true'"
                    :title="(c.enabled === false ? '恢复采集' : '停用(保留数据, 暂停采集)')"
                    @click.stop="toggleCh(c)" @keydown.enter.stop="toggleCh(c)"></span></td>
              <td><span class="act" style="color:var(--accent);cursor:pointer" @click.stop="openYtb(c)">曲线</span>
                <span class="act" style="color:var(--red);cursor:pointer;margin-left:8px"
                      @click.stop="delCh(c)">删除</span></td>
            </tr>
            <!-- 行内展开: 曲线详情(五指标, 对齐 X 追踪 accordion) -->
            <tr v-if="ytbSel === c.channel_id" class="xt-detail-row">
              <td colspan="9">
                <div class="xt-detail ytb-detail">
                  <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap">
                    <b>{{ c.title || c.input }}</b>
                    <a class="muted" v-if="c.handle" :href="'https://youtube.com/'+c.handle" target="_blank" rel="noopener">{{ c.handle }}</a>
                    <span class="mono" style="font-size:14px">订阅 {{ c.subs != null ? fmtN(c.subs) : '—' }}(≈)</span>
                    <span class="muted" v-if="c.note">{{ c.note }}</span>
                    <span style="flex:1"></span>
                    <button class="btn" @click.stop="ytbSel=''">收起</button>
                  </div>
                  <div class="feed-toolbar" style="margin:10px 0 4px">
                    <span v-for="[m, t] in ytbMetrics" :key="m" class="chip" :class="{on: ytbChart.metric===m}"
                          @click="ytbChart.metric=m">{{ t }}</span>
                    <span style="flex:1"></span>
                    <span v-for="[r, t] in ytbRanges" :key="r" class="chip" :class="{on: ytbChart.range===r}"
                          @click="ytbChart.range=r">{{ t }}</span>
                  </div>
                  <div v-if="ytbChart.metric==='latest' && ytbLatestTitle()" class="muted" style="margin-bottom:4px">
                    最新视频: {{ ytbLatestTitle() }}</div>
                  <div v-if="ytbLatest && !ytbDetail.loading" class="mono" style="font-size:12.5px;margin-bottom:4px">
                    最新 {{ ytbLatest.date }} · {{ ytbLatest.v.toLocaleString() }}
                    <span v-if="ytbLatest.delta != null" :style="{color: deltaCls(ytbLatest.delta)}">({{ ytbLatest.delta >= 0 ? '+' : '' }}{{ fmtN(ytbLatest.delta) }})</span></div>
                  <div v-if="ytbDetail.loading" class="muted">加载中…</div>
                  <div v-else-if="!ytbSeries.length || !ytbGeom" class="muted">
                    暂无快照 — 订阅曲线自 2026-09-10 起逐日积累; 流量/更新数据点「立即采集」即出</div>
                  <svg v-else :viewBox="'0 0 '+ytbGeom.W+' '+ytbGeom.H"
                       style="width:100%;height:auto;display:block">
                    <g v-for="(t, i) in ytbGeom.yTicks" :key="'y'+i">
                      <line x1="56" x2="744" :y1="t.y" :y2="t.y" stroke="currentColor" stroke-opacity=".12"/>
                      <text :x="52" :y="t.y+4" text-anchor="end" font-size="11"
                            fill="currentColor" fill-opacity=".55">{{ t.label }}</text>
                    </g>
                    <g v-for="(t, i) in ytbGeom.xTicks" :key="'x'+i">
                      <text :x="t.x" y="234" text-anchor="middle" font-size="11"
                            fill="currentColor" fill-opacity=".55">{{ t.label }}</text>
                    </g>
                    <template v-if="ytbGeom.bars.length">
                      <line v-if="ytbGeom.zeroY != null && ytbGeom.zeroY > 16 && ytbGeom.zeroY < 212"
                            x1="56" x2="744" :y1="ytbGeom.zeroY" :y2="ytbGeom.zeroY"
                            stroke="currentColor" stroke-opacity=".3"/>
                      <rect v-for="(b, i) in ytbGeom.bars" :key="'b'+i" :x="b.x" :y="b.y" :width="b.w"
                            :height="b.h" rx="2" opacity=".85"
                            :fill="b.neg ? 'var(--red)' : 'var(--green)'"><title>{{ b.title }}</title></rect>
                    </template>
                    <template v-else>
                      <polygon :points="ytbGeom.area" fill="var(--accent)" opacity=".12"/>
                      <polyline :points="ytbGeom.pts" fill="none" stroke="var(--accent)" stroke-width="2"
                                stroke-linejoin="round"/>
                      <circle v-for="(d, i) in ytbGeom.dots" :key="'d'+i" :cx="d.cx" :cy="d.cy" r="2.6"
                              fill="var(--accent)"><title>{{ d.title }}</title></circle>
                    </template>
                  </svg>
                </div>
              </td>
            </tr>
            </template>
            <tr v-if="!chRows.length"><td colspan="9" class="muted">无匹配频道</td></tr>
          </tbody>
        </table>
        <p class="muted" style="margin-top:10px">
          口径对齐 X 追踪: 订阅=API 取整值 · 今日增粉=较昨日订阅快照差分(订阅时序自 2026-09-10
          起积累, 首日显示 —) · 今日更新=当日新发布视频数 · 最新视频流量=最新一条视频当前累计播放 ·
          近7日总流量=近7天发布视频的当前累计播放合计 · 7日流量变化=上述视频今日增量合计。
          启停只影响采集范围; 解析与首轮数据在下一轮采集完成(计划任务每天一次,
          或点上方「立即采集」)。频道的热播榜/增减速看板在「视频页 · 热点追踪」。</p>
      </div>
    </div>

    <!-- ═══ 模块三: 发布与通讯录 ═══ -->
    <div v-show="sec==='misc'">
      <div class="card">
        <h3>平台账号通讯录({{ accounts.length }})
          <button class="btn" style="float:right" @click="showForm = !showForm">＋ 添加账号</button></h3>
        <div v-if="showForm" style="margin-bottom:12px;padding:10px;border:1px dashed var(--border);border-radius:8px">
          <div class="form-row"><label>平台</label>
            <select v-model="form.platform"><option v-for="p in platforms">{{ p }}</option></select></div>
          <div class="form-row"><label>账号</label>
            <input type="text" v-model="form.account" placeholder="@账号名 或 主页链接"></div>
          <div class="form-row"><label>备注</label>
            <input type="text" v-model="form.note" placeholder="可选"></div>
          <button class="btn primary" @click="addAccount">保存</button>
        </div>
        <div v-if="!accounts.length" class="muted">尚未添加账号</div>
        <table v-else class="tbl">
          <thead><tr><th>平台</th><th>账号</th><th>备注</th><th>添加于</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="(a, i) in accounts" :key="i">
              <td><span class="badge blue">{{ a.platform }}</span></td>
              <td>{{ a.account }}</td>
              <td class="muted">{{ a.note || '—' }}</td>
              <td class="mono muted" style="font-size:11px">{{ a.added_at }}</td>
              <td><span class="act" style="color:var(--red);cursor:pointer" @click="removeAccount(i)">删除</span></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <h3>已发布内容(账本只读)<span v-if="stats" class="muted" style="margin-left:10px">
          共 {{ stats.records }} 条记录 · 成功 {{ stats.published }} · 失败 {{ stats.failed }} · 待核 {{ stats.uncertain }}</span></h3>
        <div v-if="!published.length" class="muted">暂无已发布记录</div>
        <table v-else class="tbl">
          <thead><tr><th>时间</th><th>平台</th><th>文章</th><th>链接</th></tr></thead>
          <tbody>
            <tr v-for="r in published.slice(0, 50)">
              <td class="mono">{{ r.time }}</td>
              <td><span class="badge blue">{{ r.platform }}</span></td>
              <td>{{ r.article }}</td>
              <td><a :href="r.url" target="_blank" rel="noopener">打开 ↗</a></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>`,
};
