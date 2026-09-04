/* 运维页: 数据站 24/7 控制台——常驻进程 / 开机自启任务 / 最近刷新轮 / 存储与日志。
   状态 15s 轮询; 动作走 /wb-api/ops/action 白名单(后端 subprocess, 不直写三板块)。 */
window.WB = window.WB || {};
WB.pages = WB.pages || {};

WB.pages.ops = {
  data() {
    return { d: null, busy: "", err: "" };
  },
  methods: {
    async load() {
      try { this.d = await WB.api.get("/ops/status"); this.err = ""; }
      catch (e) { this.err = e.error || "状态读取失败"; }
    },
    async act(target, op, label) {
      if (this.busy) return;
      this.busy = target + op;
      try {
        const r = await WB.api.post("/ops/action", { target, op });
        WB.toast((r.ok ? "✓ " : "✗ ") + (r.output || label));
      } catch (e) { WB.toast("✗ " + (e.error || "动作失败")); }
      this.busy = "";
      setTimeout(this.load, 2500);          // 进程起停有秒级延迟, 2.5s 后刷新状态
    },
    fmtTask(t) {
      if (!t.registered) return "未注册";
      return t.state + (t.next_run ? " · 下次 " + t.next_run : "") +
             (t.interval_min ? " · 每" + t.interval_min + "分钟" : " · 登录时");
    },
  },
  mounted() { this.load(); this._t = setInterval(this.load, 15000); },
  unmounted() { clearInterval(this._t); },
  template: `
  <div style="max-width:820px">
    <div v-if="err" class="card"><span class="muted">✗ {{ err }}</span></div>
    <template v-if="d">

    <!-- 1. 常驻进程 -->
    <div class="card">
      <h3>常驻进程 <button class="btn" style="float:right" @click="load">刷新</button></h3>
      <table class="tbl">
        <thead><tr><th>进程</th><th>端口</th><th>状态</th><th>PID</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="p in d.procs" :key="p.key">
            <td>{{ p.name }}<div class="muted" style="font-size:12px">{{ p.note }}</div></td>
            <td class="mono">{{ p.port }}</td>
            <td><span class="dot" :class="p.up ? 'ok' : 'err'"></span>
                {{ p.up ? '运行中' : '未运行' }}</td>
            <td class="mono">{{ p.pid || '—' }}</td>
            <td>
              <template v-if="p.key === 'workbench'">
                <span class="muted" style="font-size:12px">本页面所在进程</span>
              </template>
              <template v-else>
                <button class="btn" :disabled="busy" v-if="!p.up"
                        @click="act(p.key, 'start', '启动')">启动</button>
                <button class="btn" :disabled="busy" v-else
                        @click="act(p.key, 'stop', '停止')">停止</button>
                <button class="btn" :disabled="busy" v-if="p.up"
                        @click="act(p.key, 'stop', '重启'); act(p.key, 'start', '重启')">重启</button>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="muted" style="margin-top:8px">OmniRoute 未运行时翻译链自动落付费位(无缝), 无事故;
        桌面「数据站控制台」快捷方式可在全灭时一键拉起本页。</p>
    </div>

    <!-- 2. 开机自启与计划任务 -->
    <div class="card">
      <h3>任务计划</h3>
      <table class="tbl">
        <thead><tr><th>任务</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="t in d.tasks" :key="t.name">
            <td class="mono">{{ t.name }}</td>
            <td :class="t.registered ? '' : 'muted'">
              <span class="dot" :class="t.registered ? 'ok' : 'err'"></span>
              {{ fmtTask(t) }}</td>
          </tr>
        </tbody>
      </table>
      <div class="form-row" style="margin-top:10px">
        <button class="btn" :disabled="busy" @click="act('refresh', 'start', '刷新一轮')">立即刷新一轮</button>
        <button class="btn" :disabled="busy" @click="act('xsurge', 'start', 'X采集一轮')">立即X采集一轮</button>
        <span class="muted">与计划任务并存, 幂等可重跑</span>
      </div>
    </div>

    <!-- 3. 最近刷新轮 -->
    <div class="card">
      <h3>最近刷新轮</h3>
      <template v-if="d.last_round.sources">
        <div class="form-row"><label>主站刷新</label>
          <span>{{ d.last_round.sources.started }} → {{ d.last_round.sources.finished }}</span></div>
        <div class="form-row"><label>结果</label>
          <span>{{ d.last_round.sources.ok }} 源成功 / {{ d.last_round.sources.fail }} 失败 /
                新入库 {{ d.last_round.sources.new }} 条</span></div>
      </template>
      <template v-if="d.last_round.xsurge">
        <div class="form-row"><label>X 起爆帖</label>
          <span class="mono" style="font-size:12px">{{ JSON.stringify(d.last_round.xsurge) }}</span></div>
      </template>
      <p v-if="!d.last_round.sources && !d.last_round.xsurge" class="muted">暂无轮次记录</p>
    </div>

    <!-- 4. 存储与日志 -->
    <div class="card">
      <h3>存储与日志</h3>
      <div class="form-row"><label>items.db</label>
        <span>{{ d.storage.items_db_mb }} MB</span>
        <span class="muted">保留窗自清: flash 48h / 其他 7d</span></div>
      <div class="form-row"><label>磁盘剩余</label><span>{{ d.storage.disk_free_gb }} GB</span></div>
      <table class="tbl" style="margin-top:6px">
        <thead><tr><th>日志</th><th>体积</th></tr></thead>
        <tbody>
          <tr v-for="f in d.storage.logs" :key="f.name">
            <td class="mono" style="font-size:12px">data/{{ f.name }}</td>
            <td>{{ f.mb == null ? '—' : f.mb + ' MB' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <p class="muted" style="font-size:12px">状态每 15s 自动刷新 · {{ d.at }}</p>
    </template>
    <div v-else class="card"><span class="muted">读取中…</span></div>
  </div>`,
};
