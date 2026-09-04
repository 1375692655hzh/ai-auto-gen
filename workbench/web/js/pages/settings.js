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
           cloud: { endpoint: "", account: "", sync_enabled: false } },
      hasKey: false, keyTail: "", testResult: null, testing: false,
      tHasKey: false, tKeyTail: "",
      yHasKey: false, yKeyTail: "",
      check: null, saving: false,
    };
  },
  methods: {
    async load() {
      const d = await WB.api.get("/settings");
      this.s = d; this.hasKey = d.source.has_key; this.keyTail = d.source.key_tail;
      this.tHasKey = d.translate.has_key; this.tKeyTail = d.translate.key_tail;
      this.yHasKey = (d.youtube || {}).has_key; this.yKeyTail = (d.youtube || {}).key_tail;
      this.applyTheme();
    },
    async save() {
      this.saving = true;
      try {
        const d = await WB.api.put("/settings", {
          source: { mode: this.s.source.mode, base_url: this.s.source.base_url,
                    api_key: this.s.source.api_key, timeout_s: this.s.source.timeout_s },
          ui: this.s.ui,
          translate: { base_url: this.s.translate.base_url,
                       api_key: this.s.translate.api_key, model: this.s.translate.model },
          youtube: { api_key: (this.s.youtube || {}).api_key || "" },
        });
        this.s.source.api_key = "";                 // 不保留明文
        this.hasKey = d.source.has_key; this.keyTail = d.source.key_tail;
        this.s.translate.api_key = "";
        this.tHasKey = d.translate.has_key; this.tKeyTail = d.translate.key_tail;
        if (this.s.youtube) this.s.youtube.api_key = "";
        this.yHasKey = (d.youtube || {}).has_key; this.yKeyTail = (d.youtube || {}).key_tail;
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

    <!-- 4. YouTube 热点追踪(视频页【热点追踪/追踪账号】数据源, Data API v3) -->
    <div class="card">
      <h3>YouTube 热点追踪 <span class="muted">视频页·热点追踪 · Data API v3</span></h3>
      <div class="form-row"><label>API Key</label>
        <input type="password" v-model="s.youtube.api_key"
               :placeholder="yHasKey ? '已配置(尾号 ' + yKeyTail + '), 留空保持不变' : 'Google Cloud Console → 启用 YouTube Data API v3'"
               style="width:360px">
        <span class="muted">仅存本机服务端, 不回显明文</span></div>
      <button class="btn primary" :disabled="saving" @click="save">保存设置</button>
      <p class="muted" style="margin-top:8px">免费配额 1 万单位/天; 采集由任务计划每天一次执行
        (bin/yttrack_task.bat), 也可在视频页【热点追踪】手动「立即采集」</p>
    </div>

    <!-- 5. 环境自检 -->
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
