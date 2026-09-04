/* 应用入口: hash 路由 + 全局壳(顶部横向主导航 + 左侧子页面菜单 + 健康灯轮询)。
   布局学火山引擎控制台: 主页面在顶部横排, 子页面选择在左侧竖排;
   子页面菜单由页面组件通过 WB.shell.setSubs 注册(无子页则不显示左栏)。 */
(function () {
  const PAGES = [
    { hash: "/news", title: "资讯", comp: WB.pages.news },
    { hash: "/article", title: "图文", comp: WB.pages.article },
    { hash: "/video", title: "视频", comp: WB.pages.video },
    { hash: "/track", title: "追踪", comp: WB.pages.track },
    { hash: "/settings", title: "设置", comp: WB.pages.settings },
  ];

  const app = Vue.createApp({
    data() {
      return {
        pages: PAGES, route: "/news", health: null, storeStatus: "",
        /* 左侧子页面菜单: [{id,title,icon?,cnt?,onPick?}], sub=当前选中 id */
        subs: [], sub: "",
      };
    },
    computed: {
      current() {
        return PAGES.find((p) => p.hash === this.route) || PAGES[0];
      },
      currentPage() { return this.current.comp; },
      currentTitle() { return this.current.title; },
      healthClass() {
        if (!this.health) return "warn";
        return this.health.source && this.health.source.ok ? "ok" : "err";
      },
      healthText() {
        if (!this.health) return "连接中…";
        const s = this.health.source;
        return s && s.ok ? "数据站已连接" : "数据站未连接";
      },
      healthTip() {
        const s = this.health && this.health.source;
        if (s && s.ok) return "数据站正常(" + s.ms + "ms)";
        return "数据站不可达 —— 请先 python cli.py sources serve, 或到设置页检查地址";
      },
    },
    methods: {
      onHash() {
        const h = location.hash.replace(/^#/, "") || "/news";
        const next = PAGES.some((p) => p.hash === h) ? h : "/news";
        if (next !== this.route) { this.subs = []; this.sub = ""; }  // 切主页面清子菜单, 等新页注册
        this.route = next;
      },
      pickSub(s) {
        this.sub = s.id;
        if (s.onPick) s.onPick();
      },
      async refreshHealth() {
        try {
          this.health = await WB.api.get("/health");
          const s = this.health.source;
          if (s && s.ok && s.store && s.store.items != null)
            this.storeStatus = s.store.items + " 条";
        } catch (e) { this.health = { source: { ok: false } }; }
      },
    },
    created() {
      /* 必须在 created 注册: 子组件 mounted 早于父组件 mounted,
         页面 mounted 里调 WB.shell.setSubs 时通道得已存在 */
      WB.shell = {
        setSubs: (list, activeId) => {
          this.subs = list || [];
          if (activeId != null) this.sub = activeId;
          else if (this.subs.length && !this.subs.some((s) => s.id === this.sub))
            this.sub = this.subs[0].id;
        },
        setSub: (id) => { this.sub = id; },
      };
      WB.theme && WB.theme.syncFromServer();   // 启动即用权威设置校正主题(含首屏)
    },
    mounted() {
      window.addEventListener("hashchange", this.onHash);
      this.onHash();
      this.refreshHealth();
      setInterval(this.refreshHealth, 30000);   // 30s 轮询健康灯
    },
  });
  app.mount("#app");
})();
