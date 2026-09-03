/* 追踪页: 账号清单真实增删(落盘 data/workbench/tracked_accounts.json) +
   指标区留桩 + 已发布内容清单(读发布账本, 只读)。 */
window.WB = window.WB || {};
WB.pages = WB.pages || {};

WB.pages.track = {
  data() {
    return {
      accounts: [], published: [], stats: null,
      form: { platform: "雪球", account: "", note: "" },
      platforms: ["雪球", "东方财富", "富途", "长桥", "微博", "B站", "抖音",
                  "知乎", "公众号", "头条", "X", "Threads", "YouTube", "其他"],
      showForm: false,
    };
  },
  methods: {
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
    try { this.accounts = (await WB.api.get("/track/accounts")).accounts; } catch (e) {}
    try {
      const d = await WB.api.get("/ledger");
      this.published = d.published; this.stats = d.stats;
    } catch (e) {}
  },
  template: `
  <div>
    <div class="notice">粉丝/流量指标采集器将在后续版本接入 —— 本期可管理追踪账号清单,
      下方「已发布内容」为账本真实数据(只读)。</div>

    <div class="card">
      <h3>追踪账号({{ accounts.length }})
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
      <div v-if="!accounts.length" class="muted">尚未添加追踪账号</div>
      <div class="acct-grid">
        <div v-for="(a, i) in accounts" :key="i" class="acct-card">
          <div class="plat">{{ a.platform }}</div>
          <div class="name">{{ a.account }}</div>
          <div class="muted">{{ a.note || '—' }} · 添加于 {{ a.added_at }}</div>
          <div class="spark">粉丝/流量曲线 · 待采集器接入</div>
          <div style="margin-top:8px;text-align:right">
            <a style="font-size:12px" @click="removeAccount(i)">删除</a></div>
        </div>
      </div>
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
  </div>`,
};
