/* 统一 API 客户端: 前端只打同源 /wb-api/*(由 workbench 后端代理/收口, 永不直连 8787)。
   错误规范化: {error, hint} 直接可读; 429 带 retryAfter。 */
window.WB = window.WB || {};

WB.api = (function () {
  async function call(method, path, body) {
    let resp;
    try {
      resp = await fetch("/wb-api" + path, {
        method,
        headers: body ? { "Content-Type": "application/json" } : {},
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

/* 素材篮(资讯页加入 → 图文页素材池, localStorage 持久化)
   sel = 是否勾选参与生成(素材池可能积很多, 只有勾选的进生成/草稿);
   新增默认勾选(用户刚点了加入); 旧数据无 sel 字段按已选兼容(matChecked 判 !== false) */
WB.basket = {
  key: "wb_materials",
  list() { try { return JSON.parse(localStorage.getItem(this.key)) || []; } catch (e) { return []; } },
  add(item) {
    const rows = this.list();
    if (rows.some((r) => r.id === item.id)) { WB.toast("该条已在素材篮"); return; }
    rows.unshift({ id: item.id, time: item.time, source: item.source,
                   text: (item.title || item.text || "").slice(0, 200), url: item.url || "",
                   sel: true });
    localStorage.setItem(this.key, JSON.stringify(rows));
    WB.toast("已加入素材篮(图文页可用)");
  },
  setSel(id, sel) {
    const rows = this.list();
    const r = rows.find((x) => x.id === id);
    if (r) { r.sel = !!sel; localStorage.setItem(this.key, JSON.stringify(rows)); }
  },
  remove(id) {
    localStorage.setItem(this.key, JSON.stringify(this.list().filter((r) => r.id !== id)));
  },
  clear() { localStorage.removeItem(this.key); },
};
