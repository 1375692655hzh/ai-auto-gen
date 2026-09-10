/* 统一 API 客户端: 前端只打同源 /wb-api/*(由 workbench 后端代理/收口, 永不直连 8787)。
   错误规范化: {error, hint} 直接可读; 429 带 retryAfter。 */
window.WB = window.WB || {};

WB.api = (function () {
  async function call(method, path, body) {
    let resp;
    const headers = body ? { "Content-Type": "application/json" } : {};
    if (method !== "GET") {                    // 对外绑定写面鉴权: 本浏览器记住的访问 Key
      try {
        const k = localStorage.getItem("wb_api_key") || "";
        if (k) headers["Authorization"] = "Bearer " + k;
      } catch (e) {}
    }
    try {
      resp = await fetch("/wb-api" + path, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      throw { error: "工作台服务不可达", hint: "请确认 python cli.py workbench serve 已启动" };
    }
    let data = null;
    try { data = await resp.json(); } catch (e) { /* 非 JSON(如文件流) */ }
    if (!resp.ok) {
      throw {
        status: resp.status,
        error: (data && data.error) || ("HTTP " + resp.status),
        hint: (data && data.hint) || "",
        retryAfter: resp.headers.get("Retry-After"),
      };
    }
    return data;
  }
  return {
    get: (p) => call("GET", p),
    post: (p, b) => call("POST", p, b || {}),
    put: (p, b) => call("PUT", p, b || {}),
    del: (p) => call("DELETE", p),
  };
})();

/* 全局 toast */
WB.toast = function (msg) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2600);
};

/* 主题: apply 挂 body.light 并写 localStorage(供 index.html 内联脚本首绘前读);
   syncFromServer 启动时拉 /settings 校正权威值——修复"刷新后回深色, 进设置页才变亮" */
WB.theme = {
  apply(t) {
    document.body.classList.toggle("light", t === "light");
    try { localStorage.setItem("wb_theme", t === "light" ? "light" : "dark"); } catch (e) {}
  },
  syncFromServer() {
    WB.api.get("/settings")
      .then((d) => WB.theme.apply(d && d.ui && d.ui.theme))
      .catch(() => {});                 // 服务端不可达时保持 localStorage 缓存值
  },
};

/* 一键复制(蹭蹭流量/推荐卡通用): clipboard API 优先, execCommand 兜底 */
WB.copyText = async function (text) {
  try {
    await navigator.clipboard.writeText(text || "");
    WB.toast("已复制到剪贴板");
  } catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text || ""; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); WB.toast("已复制到剪贴板"); }
    catch (e2) { WB.toast("复制失败, 请手动选择文本"); }
    ta.remove();
  }
};

/* 素材篮(资讯页加入 → 图文页素材池, localStorage 持久化)
   sel = 是否勾选参与生成(素材池可能积很多, 只有勾选的进生成/草稿);
   新增默认勾选(用户刚点了加入); 旧数据无 sel 字段按已选兼容(matChecked 判 !== false) */
WB.basket = {
  key: "wb_materials",
  list() { try { return JSON.parse(localStorage.getItem(this.key)) || []; } catch (e) { return []; } },
  _save(rows) {                          // 配额防护: 写满 localStorage 时淘汰最旧条目重试
    for (;;) {
      try { localStorage.setItem(this.key, JSON.stringify(rows)); return true; }
      catch (e) {
        if (!rows.length) { WB.toast("浏览器本地存储已满, 素材篮保存失败"); return false; }
        rows.pop();
      }
    }
  },
  add(item) {
    const rows = this.list();
    if (rows.some((r) => r.id === item.id)) { WB.toast("该条已在素材篮"); return; }
    rows.unshift({ id: item.id, time: item.time, source: item.source,
                   text: (item.title || item.text || "").slice(0, 200), url: item.url || "",
                   body: (item.body || "").slice(0, 2000),
                   sel: true });
    if (this._save(rows)) WB.toast("已加入素材篮(图文页可用)");
  },
  setSel(id, sel) {
    const rows = this.list();
    const r = rows.find((x) => x.id === id);
    if (r) { r.sel = !!sel; this._save(rows); }
  },
  remove(id) {
    this._save(this.list().filter((r) => r.id !== id));
  },
  clear() { localStorage.removeItem(this.key); },
};

/* 浏览层按需翻译(2026-09-09): 视口内缺译文卡片自动批量翻。
   两层缓存: localStorage(前端零请求) + 服务端哈希缓存(跨会话); 复用 settings.json translate 段(免费链)。
   用法: 卡片文本元素挂 :ref="el => trRef(el, item)", 渲染后调 WB.trans.scan(容器);
   回填直接写 item.text_zh(Vue 响应式), 展示/复制/加入素材全链路自动吃到译文。 */
WB.trans = (function () {
  const LS_KEY = "wb_trans_cache_v2", LS_MAX = 2000;   // v2: 弃用 v1(日文被误判中文, 原文污染缓存)
  let cache = null, seq = 0;
  const seen = new WeakSet();
  let io = null, timer = 0;
  let pending = [];                    // [{i, el, text}]

  function load() {
    if (cache) return cache;
    try { cache = JSON.parse(localStorage.getItem(LS_KEY) || "{}"); } catch (e) { cache = {}; }
    return cache;
  }
  function persist() {
    try {
      const keys = Object.keys(load());
      if (keys.length > LS_MAX)        // 超上限淘汰最早写入的一半(插入序≈时间序)
        keys.slice(0, keys.length - LS_MAX).forEach((k) => delete cache[k]);
      localStorage.setItem(LS_KEY, JSON.stringify(cache));
    } catch (e) {}
  }
  function zh(text) {                   // 取缓存译文; 无则空串
    if (!text) return "";
    const z = load()[text];
    return typeof z === "string" && z ? z : "";
  }
  function put(text, zhText) {
    if (text && zhText) { load()[text] = zhText; persist(); }
  }
  function flush() {
    if (!pending.length) return;
    const batch = pending; pending = [];
    fetch("/wb-api/translate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: batch.map((b) => ({ i: b.i, text: b.text })) }),
    }).then((r) => r.json()).then((d) => {
      if (d.unconfigured && !sessionStorage.getItem("wb_tr_warned")) {
        sessionStorage.setItem("wb_tr_warned", "1");   // 每次刷新只提醒一次
        if (WB.toast) WB.toast("翻译未配置: 到设置页「翻译模型」填 DeepSeek 等 key(免费位 muse 有云端地区封锁, 大陆网络不可用, 见设置页说明)");
      }
      (d.results || []).forEach((res) => {
        const b = batch.find((x) => x.i === res.i);
        if (!b) return;
        if (!res.native) put(b.text, res.zh);   // 原文(native, 如误判过的日文)不落缓存
        const it = b.el.__trItem;
        if (it && res.zh && !res.native) {
          if (b.onDone) b.onDone(b.el, it, res.zh);
          else if (!it.text_zh) it.text_zh = res.zh;   // Vue 响应式回填, 模板自动刷新
        }
      });
    }).catch(() => {});
  }
  function schedule(el, text, onDone) {
    pending.push({ i: seq++, el, text, onDone });
    clearTimeout(timer);
    timer = setTimeout(flush, 350);     // 去抖: 一屏卡片合成一批
  }
  function observe(el, onDone) {
    if (!("IntersectionObserver" in window)) { schedule(el, el.__trText, onDone); return; }
    if (!io) io = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        if (!en.isIntersecting) return;
        io.unobserve(en.target);
        schedule(en.target, en.target.__trText, en.target.__trOnDone);
      });
    }, { rootMargin: "240px" });        // 预取: 快进视口即翻
    io.observe(el);
  }
  function applyZh(el, item, z) {       // 默认回填: text_zh 优先位
    if (!item.text_zh) item.text_zh = z;
  }
  function scan(root, onDone) {         // 幂等: 渲染后调用, 新元素进观察队列; onDone(el,item,zh) 可定制回填
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll("[data-tr]").forEach((el) => {
      if (seen.has(el) || !el.__trItem || !el.__trText) return;
      seen.add(el);
      const cb = onDone || el.__trOnDone || applyZh;
      const cached = zh(el.__trText);
      if (cached) { cb(el, el.__trItem, cached); return; }
      el.__trOnDone = cb;
      observe(el, cb);
    });
  }
  return { zh, put, scan };
})();
