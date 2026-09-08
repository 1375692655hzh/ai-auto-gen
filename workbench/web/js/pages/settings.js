/* 设置页: 信息源连接(本期核心, 真实可用) + 界面偏好 + 环境自检 + 云端同步预留桩。 */
window.WB = window.WB || {};
WB.pages = WB.pages || {};

WB.pages.settings = {
  data() {
    return {
      s: { source: { mode: "local", base_url: "http://127.0.0.1:8787", api_key: "", timeout_s: 15 },
           ui: { theme: "dark", page_size: 100, remember_filters: true },
           translate: { base_url: "", api_key: "", model: "" },
           youtube: { api_key: "" },
           gemini: { api_key: '', model: 'gemini-3.6-flash' },
           analysis_paths: { paths: ["", "", "", ""] },
           compose: { base_url: "", api_key: "", model: "" },
           finnhub: { api_key: "" },
           market: { source_pref: "auto" },
           gen_defaults: { lang: "en", tier: "free", template: "catalyst-take" },
           tts: { default: { provider_id: "edge", voice: "zh-CN-XiaoxiaoNeural" }, providers: [] },
           cloud: { endpoint: "", account: "", sync_enabled: false } },
      hasKey: false, keyTail: "", testResult: null, testing: false,
      tHasKey: false, tKeyTail: "",
      yHasKey: false, yKeyTail: "",
      gHasKey: false, gKeyTail: "",
      cHasKey: false, cKeyTail: "", composeExtra: "",
      fHasKey: false, fKeyTail: "",
      llmTest: false, llmTestResult: null,
      ttsRemoved: [], ttsTests: {}, ttsTesting: "",
      // 与 article.js genTpls 同步维护
      genTpls: [{ v: "catalyst-take", t: "事件快评 · 单票突发催化(默认)" },
                { v: "earnings-print", t: "业绩拆解 · 财报/指引解读" },
                { v: "macro-print", t: "数据读数 · CPI/NFP 等宏观打印" },
                { v: "policy-call", t: "政策纪要 · 央行决议/监管" },
                { v: "tape-recap", t: "盘面综述 · 开收盘/盘中扫描" },
                { v: "thesis-note", t: "深度观点 · 非事件驱动论点" },
                { v: "risk-flag", t: "风险提示 · 预警/证伪" },
                { v: "news-flash", t: "资讯速递 · 单条重点资讯快报", zero: 1 },
                { v: "fact-sheet", t: "披露卡 · 公告/财报要点陈列", zero: 1 },
                { v: "week-ahead", t: "一周日历 · 下周财经事件表", zero: 1 },
                { v: "earnings-watch", t: "财报前瞻 · 本周财报票+关注点", zero: 1 },
                { v: "funding-trail", t: "融资脉络 · 历轮融资时间线", zero: 1 }],
      check: null, saving: false,
    };
  },
  methods: {
    async load() {
      const d = await WB.api.get("/settings");
      d.market = { source_pref: "auto", ...(d.market || {}) };
      d.gen_defaults = { lang: "en", tier: "free", template: "catalyst-take", ...(d.gen_defaults || {}) };
      this.s = d; this.hasKey = d.source.has_key; this.keyTail = d.source.key_tail;
      this.tHasKey = d.translate.has_key; this.tKeyTail = d.translate.key_tail;
      this.yHasKey = (d.youtube || {}).has_key; this.yKeyTail = (d.youtube || {}).key_tail;
      this.gHasKey = (d.gemini || {}).has_key; this.gKeyTail = (d.gemini || {}).key_tail;
      const ap = ((d.analysis_paths || {}).paths || []).slice(0, 4);
      while (ap.length < 4) ap.push("");
      this.s.analysis_paths = { paths: ap };
      this.cHasKey = (d.compose || {}).has_key; this.cKeyTail = (d.compose || {}).key_tail;
      const ebl = (d.compose || {}).extra_body;
      this.composeExtra = ebl && Object.keys(ebl).length ? JSON.stringify(ebl) : "";
      this.fHasKey = (d.finnhub || {}).has_key; this.fKeyTail = (d.finnhub || {}).key_tail;
      const tts = d.tts || {};
      this.s.tts = {
        default: { provider_id: "edge", voice: "zh-CN-XiaoxiaoNeural", ...(tts.default || {}) },
        providers: (tts.providers || []).map((p) => ({
          id: p.id, name: p.name, engine: p.engine, enabled: !!p.enabled,
          api_key: "", base_url: p.base_url || "", model: p.model || "",
          style: p.style || "", format: p.format || "",
          voices: (p.voices || []).map((v) => ({ id: v.id, name: v.name })),
          has_key: !!p.has_key, key_tail: p.key_tail || "", locked: true,
        })),
      };
      this.ttsRemoved = [];
      this.applyTheme();
    },
    async save() {
      let extraBody = {};
      if ((this.composeExtra || "").trim()) {
        try { extraBody = JSON.parse(this.composeExtra); }
        catch (e) { WB.toast("厂商私有参数不是合法 JSON, 未保存"); return; }
        if (!extraBody || typeof extraBody !== "object" || Array.isArray(extraBody)) {
          WB.toast("厂商私有参数必须是 JSON 对象"); return;
        }
      }
      const ids = [];
      for (const p of this.s.tts.providers || []) {
        if (!this.ttsIdOk(p.id)) { WB.toast("供应商 id 只能是字母数字下划线或短横线: " + (p.id || "(空)")); return; }
        if (ids.includes(p.id)) { WB.toast("供应商 id 重复: " + p.id); return; }
        ids.push(p.id);
        if ((p.voices || []).some((v) => v.id && !this.ttsIdOk(v.id))) {
          WB.toast(p.name + " 有非法音色 id"); return;
        }
      }
      this.saving = true;
      try {
        const d = await WB.api.put("/settings", {
          source: { mode: this.s.source.mode, base_url: this.s.source.base_url,
                    api_key: this.s.source.api_key, timeout_s: this.s.source.timeout_s },
          ui: this.s.ui,
          translate: { base_url: this.s.translate.base_url,
                       api_key: this.s.translate.api_key, model: this.s.translate.model },
          youtube: { api_key: (this.s.youtube || {}).api_key || "" },
          gemini: { api_key: (this.s.gemini || {}).api_key || '',
                    model: (this.s.gemini || {}).model || 'gemini-3.6-flash' },
          analysis_paths: { paths: (this.s.analysis_paths || {}).paths || ["", "", "", ""] },
          compose: { base_url: (this.s.compose || {}).base_url || "",
                     api_key: (this.s.compose || {}).api_key || "",
                     model: (this.s.compose || {}).model || "",
                     extra_body: extraBody },
          finnhub: { api_key: (this.s.finnhub || {}).api_key || "" },
          market: { ...this.s.market },
          gen_defaults: { ...this.s.gen_defaults },
          tts: this.ttsPayload(),
        });
        this.s.source.api_key = "";                 // 不保留明文
        this.hasKey = d.source.has_key; this.keyTail = d.source.key_tail;
        this.s.translate.api_key = "";
        this.tHasKey = d.translate.has_key; this.tKeyTail = d.translate.key_tail;
        if (this.s.youtube) this.s.youtube.api_key = "";
        this.yHasKey = (d.youtube || {}).has_key; this.yKeyTail = (d.youtube || {}).key_tail;
        if (this.s.gemini) this.s.gemini.api_key = '';
        this.gHasKey = (d.gemini || {}).has_key; this.gKeyTail = (d.gemini || {}).key_tail;
        if (this.s.compose) this.s.compose.api_key = "";
        this.cHasKey = (d.compose || {}).has_key; this.cKeyTail = (d.compose || {}).key_tail;
        if (this.s.finnhub) this.s.finnhub.api_key = "";
        this.fHasKey = (d.finnhub || {}).has_key; this.fKeyTail = (d.finnhub || {}).key_tail;
        this.applyTtsPublic(d.tts);
        this.applyTheme();
        WB.toast("设置已保存");
        this.$root.refreshHealth && this.$root.refreshHealth();
      } catch (e) { WB.toast("保存失败: " + e.error); }
      this.saving = false;
    },
    async testConn() {
      this.testing = true; this.testResult = null;
      try {                                  // 先保存再测, 保证测的是表单里的新值
        await WB.api.put("/settings", { source: { mode: this.s.source.mode,
          base_url: this.s.source.base_url, api_key: this.s.source.api_key,
          timeout_s: this.s.source.timeout_s } });
        this.s.source.api_key = "";
        const d = await WB.api.get("/v1/health");
        this.testResult = { ok: true, text: "连接正常 · 库内 " +
          JSON.stringify(d.store && d.store.items != null ? d.store.items : d.store) +
          " 条" + (d.snapshot && d.snapshot.built_at ? " · 快照 " + d.snapshot.built_at : "") };
      } catch (e) {
        this.testResult = { ok: false, text: e.error + (e.hint ? " — " + e.hint : "") };
      }
      this.testing = false;
    },
    async testLlm() {
      this.llmTest = true; this.llmTestResult = null;
      try {
        let eb = {};
        if ((this.composeExtra || "").trim()) {
          try { eb = JSON.parse(this.composeExtra); } catch (e) { eb = undefined; }
          if (eb === undefined) { WB.toast("厂商私有参数不是合法 JSON"); this.llmTest = false; return; }
        }
        const saved = await WB.api.put("/settings", { compose: { ...this.s.compose, extra_body: eb } });
        this.s.compose.api_key = "";
        this.cHasKey = (saved.compose || {}).has_key;
        this.cKeyTail = (saved.compose || {}).key_tail;
        const d = await WB.api.post("/test-llm", {});
        this.llmTestResult = { ok: d.ok, text: d.ok ? "连接正常 · " + d.model : d.error };
      } catch (e) {
        this.llmTestResult = { ok: false, text: e.error || "连接测试失败" };
      } finally { this.llmTest = false; }
    },
    ttsIdOk(v) { return /^[\w-]+$/.test(String(v || "")); },
    engineVoices(engine) {
      return engine === "dashscope"
        ? [{ id: "longanlufeng", name: "陆锋 · 男声" }, { id: "longanlingxin", name: "灵欣 · 女声" }]
        : [{ id: "zh-CN-XiaoxiaoNeural", name: "晓晓 · 女声" },
           { id: "zh-CN-YunxiNeural", name: "云希 · 男声" },
           { id: "zh-CN-YunyangNeural", name: "云扬 · 男声·新闻" }];
    },
    ttsDefaultVoices() {
      const p = (this.s.tts.providers || []).find((p) => p.id === this.s.tts.default.provider_id);
      return (p && p.voices) || [];
    },
    ttsPayload() {
      return {
        default: { provider_id: this.s.tts.default.provider_id || "",
                   voice: this.s.tts.default.voice || "" },
        providers: (this.s.tts.providers || []).map((p) => ({
          id: p.id, name: p.name, engine: p.engine, enabled: !!p.enabled,
          api_key: p.api_key || "", base_url: p.base_url || "", model: p.model || "",
          style: p.style || "", format: p.format || "",
          voices: (p.voices || []).filter((v) => this.ttsIdOk(v.id))
            .map((v) => ({ id: v.id, name: v.name || v.id })),
        })),
        remove_ids: this.ttsRemoved.slice(),
      };
    },
    applyTtsPublic(tts) {
      const pub = tts || {};
      const byId = {};
      (pub.providers || []).forEach((p) => { byId[p.id] = p; });
      (this.s.tts.providers || []).forEach((p) => {
        p.api_key = "";
        p.locked = true;
        const row = byId[p.id] || {};
        p.has_key = !!row.has_key; p.key_tail = row.key_tail || "";
      });
      if (pub.default) this.s.tts.default = { ...this.s.tts.default, ...pub.default };
      this.ttsRemoved = [];
    },
    addTtsProvider() {
      const ids = new Set((this.s.tts.providers || []).map((p) => p.id));
      let n = 1, id = "custom";
      while (ids.has(id)) { n += 1; id = "custom-" + n; }
      this.s.tts.providers.push({
        id, name: "自定义供应商", engine: "edge", enabled: true,
        api_key: "", base_url: "", voices: this.engineVoices("edge").map((v) => ({ ...v })),
        has_key: false, key_tail: "", locked: false,
      });
      this.ttsRemoved = this.ttsRemoved.filter((x) => x !== id);
    },
    removeTtsProvider(p) {
      if (!confirm("删除供应商「" + (p.name || p.id) + "」？已保存的 Key 会一并丢掉。")) return;
      this.s.tts.providers = this.s.tts.providers.filter((x) => x.id !== p.id);
      if (!this.ttsRemoved.includes(p.id)) this.ttsRemoved.push(p.id);
      if (this.s.tts.default.provider_id === p.id) {
        const next = this.s.tts.providers.find((x) => x.enabled) || this.s.tts.providers[0];
        this.s.tts.default.provider_id = next ? next.id : "";
        this.s.tts.default.voice = next && next.voices[0] ? next.voices[0].id : "";
      }
    },
    onTtsEngine(p) {
      p.voices = this.engineVoices(p.engine).map((v) => ({ ...v }));
      if (this.s.tts.default.provider_id === p.id)
        this.s.tts.default.voice = (p.voices[0] && p.voices[0].id) || "";
    },
    addTtsVoice(p) { p.voices.push({ id: "", name: "" }); },
    removeTtsVoice(p, i) {
      p.voices.splice(i, 1);
      if (this.s.tts.default.provider_id === p.id
          && !p.voices.some((v) => v.id === this.s.tts.default.voice))
        this.s.tts.default.voice = (p.voices[0] && p.voices[0].id) || "";
    },
    onTtsDefaultProvider() {
      const v = this.ttsDefaultVoices();
      if (!v.some((x) => x.id === this.s.tts.default.voice))
        this.s.tts.default.voice = (v[0] && v[0].id) || "";
    },
    async detectTtsVoices(p) {
      this.ttsTesting = p.id;
      try {
        const d = await WB.api.post("/tts-voices-detect",
          { base_url: p.base_url, api_key: p.api_key, model: p.model });
        if (d.ok) {
          if (d.model && !p.model) p.model = d.model;
          const have = new Set((p.voices || []).map(v => v.id));
          const add = (d.voices || []).filter(v => v.id && !have.has(v.id));
          p.voices.push(...add);
          WB.toast(`检测到 ${d.voices.length} 个音色, 新增 ${add.length} 个(保存后生效)`
            + (d.hint ? " · " + d.hint : ""));
        } else WB.toast((d.error || "检测失败") + (d.hint ? " · " + d.hint : ""));
      } catch (e) { WB.toast(e.error || "检测失败"); }
      this.ttsTesting = "";
    },
    async testTts(p) {
      const voice = (this.s.tts.default.provider_id === p.id && this.s.tts.default.voice)
        || ((p.voices || []).find((v) => this.ttsIdOk(v.id)) || {}).id;
      if (!this.ttsIdOk(p.id) || !voice) { WB.toast("供应商 id 与至少一个音色都要填写"); return; }
      this.saving = true;
      try {
        const saved = await WB.api.put("/settings", { tts: this.ttsPayload() });
        this.applyTtsPublic(saved.tts);
      } catch (e) { WB.toast("保存失败: " + e.error); this.saving = false; return; }
      this.saving = false;
      this.ttsTesting = p.id;
      this.ttsTests = { ...this.ttsTests, [p.id]: { testing: true } };
      try {
        const d = await WB.api.post("/test-tts", { provider_id: p.id, voice });
        this.ttsTests = { ...this.ttsTests, [p.id]: { ok: true, text: "连接正常 · " + voice, url: d.url + "?t=" + Date.now() } };
      } catch (e) {
        this.ttsTests = { ...this.ttsTests, [p.id]: { ok: false, text: e.error + (e.hint ? " — " + e.hint : "") } };
      }
      this.ttsTesting = "";
    },
    applyTheme() {
      WB.theme ? WB.theme.apply(this.s.ui.theme)
               : document.body.classList.toggle("light", this.s.ui.theme === "light");
    },
    async loadCheck() {
      try { this.check = await WB.api.get("/selfcheck"); } catch (e) {}
    },
  },
  mounted() { this.load(); this.loadCheck(); },
  template: `
  <div style="max-width:760px">
    <!-- 1. 信息源连接 -->
    <div class="card">
      <h3>信息源连接</h3>
      <div class="key-guide">
        <b>注册来源:</b> 无需注册 —— 本机(127.0.0.1)模式免密直连;
        局域网/云端模式向数据站管理员索取 Key(管理员在
        <code>global-news-sources/config/api_keys.local.json</code> 创建, 可设每分钟/每日配额)。<br>
        <b>说明:</b> 本工作台全部资讯/推荐数据都从数据站读取, 这一栏不通则资讯页为空。
      </div>

      <div class="form-row"><label>连接模式</label>
        <div class="radio-group">
          <label><input type="radio" value="local" v-model="s.source.mode"> 本机(127.0.0.1)</label>
          <label><input type="radio" value="lan" v-model="s.source.mode"> 局域网数据站</label>
          <label style="opacity:.45"><input type="radio" value="cloud" disabled> 云端(未来开放)</label>
        </div>
      </div>
      <div class="form-row"><label>数据源地址</label>
        <input type="text" v-model="s.source.base_url" placeholder="http://127.0.0.1:8787">
        <span class="muted">sources serve 的地址</span></div>
      <div class="form-row"><label>API Key</label>
        <input type="password" v-model="s.source.api_key"
               :placeholder="hasKey ? '已配置(尾号 ' + keyTail + '), 留空保持不变' : '本机免密可留空'">
        <span class="muted">仅存本机服务端, 不回显明文</span></div>
      <div class="form-row"><label>超时(秒)</label>
        <input type="text" v-model.number="s.source.timeout_s" style="width:80px"></div>
      <div class="form-row">
        <button class="btn" :disabled="testing" @click="testConn">{{ testing ? '测试中…' : '测试连接' }}</button>
        <button class="btn primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存设置' }}</button>
      </div>
      <div v-if="testResult" class="test-result" :class="testResult.ok ? 'ok' : 'fail'">
        {{ testResult.ok ? '✓ ' : '✗ ' }}{{ testResult.text }}</div>
      <p class="muted" style="margin-top:8px">本机数据站启动: <code class="mono">python cli.py sources serve</code>;
        数据刷新由任务计划每 30 分钟自动执行(sources refresh)</p>
    </div>

    <!-- 2. 界面偏好 -->
    <div class="card">
      <h3>界面偏好</h3>
      <div class="form-row"><label>主题</label>
        <div class="radio-group">
          <label><input type="radio" value="dark" v-model="s.ui.theme"> 暗色</label>
          <label><input type="radio" value="light" v-model="s.ui.theme"> 亮色</label>
        </div></div>
      <div class="form-row"><label>每页条数</label>
        <input type="text" v-model.number="s.ui.page_size" style="width:80px">
        <span class="muted">资讯页 limit(≤1000)</span></div>
      <div class="form-row"><label>筛选记忆</label>
        <label><input type="checkbox" v-model="s.ui.remember_filters"> 记住上次筛选条件</label></div>
      <button class="btn primary" :disabled="saving" @click="save">保存设置</button>
    </div>

    <!-- 3. 翻译模型(蹭蹭流量推文翻译, OpenAI 兼容 /chat/completions) -->
    <div class="card">
      <h3>翻译模型 <span class="muted">蹭蹭流量推文翻译 · 采集轮自动补译</span></h3>
      <div class="key-guide">
        <b>注册来源:</b>
        <a href="https://platform.deepseek.com" target="_blank" rel="noopener">DeepSeek 开放平台</a>
        → 注册 → 充值 → 「API keys」创建( sk- 开头); 任意 OpenAI 兼容服务也可
        (月之暗面/硅基流动等, 换 base_url + model 即可)。<br>
        <b>说明:</b> 只服务蹭蹭流量推文翻译(采集轮自动补译, 每轮 ≤60 条);
        配置仅存本工作台(data/workbench/settings.json), 由工作台自己的采集任务执行——
        <b>只单独部署工作台、没有数据站的用户, 照常在此配置即可生效</b>(蹭蹭流量的 RSS 源不依赖数据站)。
      </div>

      <div class="form-row"><label>接口地址</label>
        <input type="text" v-model="s.translate.base_url" placeholder="https://api.deepseek.com"
               style="width:320px"></div>
      <div class="form-row"><label>API Key</label>
        <input type="password" v-model="s.translate.api_key"
               :placeholder="tHasKey ? '已配置(尾号 ' + tKeyTail + '), 留空保持不变' : 'sk-...'"
               style="width:320px">
        <span class="muted">仅存本机服务端, 不回显明文</span></div>
      <div class="form-row"><label>模型</label>
        <input type="text" v-model="s.translate.model" placeholder="deepseek-v4-flash"
               style="width:220px"></div>
      <button class="btn primary" :disabled="saving" @click="save">保存设置</button>
    </div>

    <!-- 4. 成稿模型(内容生成专用 LLM, 独立于翻译链, 不动翻译额度) -->
    <div class="card">
      <h3>成稿模型 <span class="muted">内容生成页·开始生成专用 · 独立计费</span></h3>
      <div class="key-guide">
        <b>注册来源:</b> 同翻译模型 ——
        <a href="https://platform.deepseek.com" target="_blank" rel="noopener">DeepSeek 开放平台</a>
        或任意 OpenAI 兼容服务。<br>
        <b>说明:</b> 只服务内容生成页「开始生成」的成稿环节, 独立计费不动翻译额度;
        配置仅存本工作台, 单独部署工作台的用户照常可用。
      </div>

      <div class="form-row"><label>接口地址</label>
        <input type="text" v-model="s.compose.base_url" placeholder="OpenAI 兼容接口, 如 https://api.deepseek.com"
               style="width:320px"></div>
      <div class="form-row"><label>API Key</label>
        <input type="password" v-model="s.compose.api_key"
               :placeholder="cHasKey ? '已配置(尾号 ' + cKeyTail + '), 留空保持不变' : 'sk-...'"
               style="width:320px">
        <span class="muted">仅存本机服务端, 不回显明文</span></div>
      <div class="form-row"><label>模型</label>
        <input type="text" v-model="s.compose.model" placeholder="如 deepseek-v4-flash"
               style="width:220px"></div>
      <div class="form-row"><label>私有参数</label>
        <input type="text" v-model="composeExtra" style="width:420px"
               placeholder='选填 JSON, 如智谱推理模型 {"thinking": {"type": "disabled"}} 防思考吃光字数'>
        <span class="muted">原样并入请求体, 一般用不上</span></div>
      <p class="muted">未配置时「开始生成」报配置缺失, 不回落翻译链</p>
      <button class="btn" :disabled="llmTest || saving" @click="testLlm">{{ llmTest ? '测试中…' : '测试连接' }}</button>
      <div v-if="llmTestResult" class="test-result" :class="llmTestResult.ok ? 'ok' : 'fail'">
        {{ llmTestResult.ok ? '✓ ' : '✗ ' }}{{ llmTestResult.text }}</div>
      <button class="btn primary" :disabled="saving" @click="save">保存设置</button>
    </div>

    <!-- 5. Finnhub(内容生成·聚合分析增强, 投行评级/目标价, 仅美股) -->
    <div class="card">
      <h3>Finnhub <span class="muted">内容生成·聚合分析增强 · 投行评级/目标价(仅美股)</span></h3>
      <div class="key-guide">
        <b>注册来源:</b>
        <a href="https://finnhub.io/register" target="_blank" rel="noopener">finnhub.io 注册</a>
        (邮箱即可, 免费 60 次/分), 注册后 Dashboard → API Key 复制。<br>
        <b>说明:</b> 只增强内容生成·聚合分析的美股投行评级/目标价; 留空则该环节自动跳过。
      </div>

      <div class="form-row"><label>API Key</label>
        <input type="password" v-model="s.finnhub.api_key"
               :placeholder="fHasKey ? '已配置(尾号 ' + fKeyTail + '), 留空保持不变' : 'finnhub.io 免费注册即得(60 次/分)'"
               style="width:360px">
        <span class="muted">仅存本机服务端, 不回显明文; 留空则聚合分析跳过投行数据</span></div>
      <button class="btn primary" :disabled="saving" @click="save">保存设置</button>
    </div>

    <div class="card">
      <h3>内容生成 · 行情源</h3>
      <div class="form-row"><label>行情数据源</label>
        <select v-model="s.market.source_pref">
          <option value="auto">自动(yfinance 主力, 东财兜底·默认)</option>
          <option value="em_first">东财优先(yfinance 兜底)</option>
          <option value="yf_only">仅用 yfinance</option>
        </select></div>
      <p class="muted">快照抓取/技术分析的行情数据源, 换网络环境时切换</p>
      <button class="btn primary" :disabled="saving" @click="save">保存设置</button>
    </div>

    <div class="card">
      <h3>内容生成 · 默认参数</h3>
      <div class="form-row"><label>默认语种</label>
        <select v-model="s.gen_defaults.lang">
          <option value="en">英语</option><option value="zh-CN">简中</option>
          <option value="zh-TW">繁中</option><option value="ja">日语</option><option value="yue">粤语</option>
        </select></div>
      <div class="form-row"><label>默认账号类型</label>
        <select v-model="s.gen_defaults.tier">
          <option value="free">免费(free)</option><option value="paid">付费(paid)</option>
        </select></div>
      <div class="form-row"><label>默认模板</label>
        <select v-model="s.gen_defaults.template">
          <option v-for="t in genTpls" :key="t.v" :value="t.v">{{ t.t }}</option>
        </select></div>
      <button class="btn primary" :disabled="saving" @click="save">保存设置</button>
    </div>

    <!-- 4. YouTube 热点追踪(视频页【热点追踪/追踪账号】数据源, Data API v3) -->
    <div class="card">
      <h3>YouTube 热点追踪 <span class="muted">视频页·热点追踪 · Data API v3</span></h3>
      <div class="key-guide">
        <b>注册来源:</b>
        <a href="https://console.cloud.google.com/apis/library/youtube.googleapis.com" target="_blank" rel="noopener">Google Cloud Console</a>
        → 启用 YouTube Data API v3 → 「凭据」→ 创建凭据 → API 密钥(AIzaSy 开头)。<br>
        <b>说明:</b> 只服务视频页热点追踪; 免费配额 1 万单位/天, 每天一次采集约消耗 100 单位, 免费够用。
      </div>

      <div class="form-row"><label>API Key</label>
        <input type="password" v-model="s.youtube.api_key"
               :placeholder="yHasKey ? '已配置(尾号 ' + yKeyTail + '), 留空保持不变' : 'Google Cloud Console → 启用 YouTube Data API v3'"
               style="width:360px">
        <span class="muted">仅存本机服务端, 不回显明文</span></div>
      <button class="btn primary" :disabled="saving" @click="save">保存设置</button>
      <p class="muted" style="margin-top:8px">免费配额 1 万单位/天; 采集由任务计划每天一次执行
        (bin/yttrack_task.bat), 也可在视频页【热点追踪】手动「立即采集」</p>
    </div>

    <!-- 5. 视频分析(Gemini) -->
    <div class="card">
      <h3>视频分析 (Gemini) <span class="muted">视频工坊·看片分析 · Google AI Studio</span></h3>
      <div class="key-guide">
        <b>注册来源:</b>
        <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">Google AI Studio</a>
        → Get API key(AIzaSy 开头), Google 账号登录即得, 有免费额度。<br>
        <b>说明:</b> 只服务视频工坊「分析视频」—— Gemini 直接看 YouTube 视频出内容证据,
        再转分镜/脚本; 免费额度有限, 配额用完当日会失败, 次日恢复。
      </div>

      <div class="form-row"><label>API Key</label>
        <input type="password" v-model="s.gemini.api_key"
               :placeholder="gHasKey ? '已配置(尾号 ' + gKeyTail + '), 留空保持不变' : 'Google AI Studio 的 Gemini API Key；用于视频分析看片通道'"
               style="width:420px"></div>
      <div class="form-row"><label>模型</label>
        <input type="text" v-model="s.gemini.model" placeholder="gemini-3.6-flash" style="width:260px"></div>
      <p class="muted">仅存服务端打码回显</p>
      <button class="btn primary" :disabled="saving" @click="save">保存设置</button>
    </div>

    <!-- 语音合成(视频制作配音, Edge 免费 / DashScope 可选, 可增删供应商) -->
    <div class="card">
      <h3>语音合成 <span class="muted">视频制作·配音 · 可配置多个供应商</span></h3>
      <div class="key-guide">
        <b>注册来源:</b> Edge TTS 免费免 Key;
        DashScope 走
        <a href="https://dashscope.console.aliyun.com/" target="_blank" rel="noopener">阿里云百炼</a>
        → API-KEY(sk- 开头)。可添加多套同一引擎(例如两把 DashScope Key)。<br>
        <b>说明:</b> 只服务视频制作「语音」段; 配置仅存本工作台。视频页只列出已启用且至少有一个音色的供应商。<br>
        <b>自定义供应商:</b> 填 url/api_key/model 后点「检测预设语音」自动拉音色(端点不支持则手动加音色)。<br>
        <b>mimo(小米)填写规则:</b> url=<code>https://api.xiaomimimo.com/v1</code> · model=<code>mimo-v2.5-tts</code> ·
        key 从 <a href="https://api.xiaomimimo.com" target="_blank" rel="noopener">api.xiaomimimo.com</a> 创建;
        音色=mimo_default/冰糖/茉莉/苏打/白桦/Mia/Chloe/Milo/Dean(检测可自动拉取); 可选「风格提示」控制语气。<br>
        <b>MiniMax 填写规则:</b> url=<code>https://api.minimax.io/v1</code>(国内 <code>https://api.minimaxi.com/v1</code>) ·
        model=<code>speech-2.8-hd</code>(或 speech-2.8-turbo) ·
        key 从 <a href="https://platform.minimaxi.com" target="_blank" rel="noopener">platform.minimaxi.com</a>
        「账户管理→API密钥」创建; 音色走 MiniMax 语音库(get_voice 自动检测),
        如 male-qn-qingse/female-shaonv/audiobook_male_1; 音频为 mp3 输出。
      </div>
      <div class="form-row"><label>默认供应商</label>
        <select v-model="s.tts.default.provider_id" @change="onTtsDefaultProvider" style="max-width:280px">
          <option value="">未指定</option>
          <option v-for="p in s.tts.providers" :key="p.id" :value="p.id">{{ p.name }} · {{ p.id }}</option>
        </select></div>
      <div class="form-row"><label>默认音色</label>
        <select v-model="s.tts.default.voice" style="max-width:280px">
          <option value="">未指定</option>
          <option v-for="v in ttsDefaultVoices()" :key="v.id" :value="v.id">{{ v.name || v.id }}</option>
        </select></div>
      <div v-for="p in s.tts.providers" :key="p.id"
           style="margin:12px 0;padding:10px;border:1px dashed var(--border);border-radius:8px">
        <div class="form-row"><label>标识</label>
          <input type="text" v-model="p.id" :readonly="p.locked" placeholder="edge / dashscope / custom"
                 style="width:180px">
          <span class="muted">{{ p.locked ? '已保存的标识不可改' : '保存后锁定' }}</span></div>
        <div class="form-row"><label>显示名</label>
          <input type="text" v-model="p.name" style="width:220px"></div>
        <div class="form-row"><label>引擎</label>
          <select v-model="p.engine" @change="onTtsEngine(p)">
            <option value="edge">Edge TTS（免费）</option>
            <option value="dashscope">DashScope（阿里云）</option>
            <option value="custom">自定义（OpenAI 兼容 /audio/speech）</option>
          </select>
          <label><input type="checkbox" v-model="p.enabled"> 启用</label></div>
        <div class="form-row"><label>API Key</label>
          <input type="password" v-model="p.api_key"
                 :placeholder="p.has_key ? '已配置(尾号 ' + p.key_tail + '), 留空保持不变' : (p.engine==='edge' ? 'Edge 可留空' : 'sk-...')"
                 style="width:320px">
          <span class="muted">仅存本机服务端, 不回显明文</span></div>
        <div class="form-row" v-if="p.engine==='dashscope'"><label>接口地址</label>
          <input type="text" v-model="p.base_url" placeholder="可留空, 默认官方地址" style="width:320px"></div>
        <div class="form-row" v-if="p.engine==='custom'"><label>接口地址</label>
          <input type="text" v-model="p.base_url" placeholder="必填, 如 https://api.xxx.com/v1" style="width:320px"></div>
        <div class="form-row" v-if="p.engine==='custom'"><label>模型</label>
          <input type="text" v-model="p.model" placeholder="必填, 如 gpt-4o-mini-tts / ark tts 模型" style="width:280px">
          <button class="btn" :disabled="ttsTesting===p.id || !p.base_url" @click="detectTtsVoices(p)">
            {{ ttsTesting===p.id ? '检测中…' : '检测预设语音' }}</button></div>
        <div class="form-row" v-if="p.engine==='custom'"><label>风格提示</label>
          <input type="text" v-model="p.style" placeholder="可选, 语气风格指令(chat 音频模态端点生效)" style="width:420px"></div>
        <div class="form-row" v-if="p.engine==='custom'"><label>音频格式</label>
          <select v-model="p.format" style="width:120px">
            <option value="">mp3(默认)</option><option value="wav">wav</option>
          </select></div>
        <p class="muted" style="margin:6px 0 4px">音色清单</p>
        <div v-for="(v,i) in p.voices" :key="i" class="form-row">
          <label>音色 {{ i+1 }}</label>
          <input type="text" v-model="v.id" placeholder="id, 如 zh-CN-XiaoxiaoNeural" style="width:220px">
          <input type="text" v-model="v.name" placeholder="显示名" style="width:160px">
          <button class="btn" @click="removeTtsVoice(p,i)">删除音色</button></div>
        <div class="form-row">
          <button class="btn" @click="addTtsVoice(p)">＋ 音色</button>
          <button class="btn" :disabled="ttsTesting===p.id || saving" @click="testTts(p)">
            {{ ttsTesting===p.id ? '测试中…' : '测试连接' }}</button>
          <button class="btn" @click="removeTtsProvider(p)">删除供应商</button>
        </div>
        <div v-if="ttsTests[p.id]" class="test-result" :class="ttsTests[p.id].ok ? 'ok' : 'fail'">
          {{ ttsTests[p.id].ok ? '✓ ' : '✗ ' }}{{ ttsTests[p.id].text }}</div>
        <audio v-if="ttsTests[p.id] && ttsTests[p.id].url" :src="ttsTests[p.id].url" controls
               style="display:block;margin-top:8px;max-width:100%;height:34px"></audio>
      </div>
      <div class="form-row">
        <button class="btn" @click="addTtsProvider">＋ 添加供应商</button>
        <button class="btn primary" :disabled="saving" @click="save">保存设置</button>
      </div>
    </div>

    <!-- 视频分析路径(本地文件分析扫描根) -->
    <div class="card">
      <h3>视频分析路径 <span class="muted">视频工坊·本地文件分析 · 4 个扫描根</span></h3>
      <div class="form-row"><label>路径 1</label>
        <input type="text" v-model="s.analysis_paths.paths[0]" style="width:520px"
               placeholder="如微信文件接收目录, 留空禁用"></div>
      <div class="form-row"><label>路径 2</label>
        <input type="text" v-model="s.analysis_paths.paths[1]" style="width:520px" placeholder="可选"></div>
      <div class="form-row"><label>路径 3</label>
        <input type="text" v-model="s.analysis_paths.paths[2]" style="width:520px" placeholder="可选"></div>
      <div class="form-row"><label>路径 4</label>
        <input type="text" v-model="s.analysis_paths.paths[3]" style="width:520px" placeholder="可选"></div>
      <div class="key-guide">
        <b>说明:</b> 视频工坊「分析视频」切到「本地文件」方式时, 递归扫描这些目录下的
        视频文件(mp4/mov/mkv/webm/avi 等, 最多 200 个); 只允许分析这些目录内的文件,
        目录外路径会被拒绝。留空 = 禁用该槽位。
      </div>
      <button class="btn primary" :disabled="saving" @click="save">保存设置</button>
    </div>

    <!-- 6. 环境自检 -->
    <div class="card">
      <h3>环境自检 <button class="btn" style="float:right" @click="loadCheck">刷新</button></h3>
      <div v-if="check">
        <div class="form-row"><label>工作流包</label><span>{{ check.flows_count }} 个</span></div>
        <div class="form-row"><label>待发队列</label><span>{{ check.queue_count }} 篇</span></div>
        <div class="form-row"><label>发布账本</label><span>{{ check.ledger_records }} 条记录</span></div>
        <div class="form-row"><label>视频项目</label><span>{{ check.video_projects }} 个</span></div>
        <div class="form-row"><label>运行记录</label><span>{{ check.runs_count }} 次</span></div>
        <p class="muted mono" style="margin-top:8px">产物: {{ check.paths.output }}<br>
           队列: {{ check.paths.queue }}<br>账本: {{ check.paths.ledger }}</p>
      </div>
      <div v-else class="muted">读取中…</div>
      <p class="muted" style="margin-top:6px">完整体检: <code class="mono">python cli.py doctor</code></p>
    </div>

    <!-- 4. 账号与云同步(预留) -->
    <div class="card" style="opacity:.65">
      <h3>账号与云同步(预留)</h3>
      <p class="muted" style="margin-bottom:10px">当前为个人单机纯本地版; 未来登录后可将工作台配置与追踪账号同步到云端。</p>
      <div class="form-row"><label>云端网关</label>
        <input type="text" v-model="s.cloud.endpoint" disabled placeholder="https://(未来开放)"></div>
      <div class="form-row"><label>账号</label>
        <input type="text" disabled placeholder="登录/注册(未来开放)"></div>
      <div class="stub-wrap">
        <button class="btn stub" disabled>登录 / 同步</button>
        <div class="stub-tip">接口已定型: <code>POST /wb-api/cloud/login|sync</code>(本期返回 501);
          API Key 等私密信息永不同步</div>
      </div>
    </div>
  </div>`,
};
