/* 图文页: 素材篮 + 工作流状态回显 + 产物/队列只读浏览; 生成/发布按钮本期为桩。 */
window.WB = window.WB || {};
WB.pages = WB.pages || {};

WB.pages.article = {
  data() {
    return {
      basket: WB.basket.list(),
      flows: [], selFlow: "", runs: [], selRun: null,
      artifacts: [], queue: [], selArt: null, artContent: "", loadingArt: false,
    };
  },
  methods: {
    removeMaterial(id) { WB.basket.remove(id); this.basket = WB.basket.list(); },
    clearBasket() { WB.basket.clear(); this.basket = []; },
    stepClass(v) {
      const s = String(v).toLowerCase();
      return s.includes("waiting") ? "waiting" : (s.includes("done") || s.includes("ok") ? "done" : "");
    },
    async preview(a) {
      this.selArt = a; this.artContent = ""; 
      if (a.kind === "png" || a.kind === "jpg") return;         // 图片直接 <img>
      this.loadingArt = true;
      try {
        const r = await fetch("/wb-api/artifacts/file?path=" + encodeURIComponent(a.path));
        this.artContent = await r.text();
      } catch (e) { this.artContent = "(读取失败)"; }
      this.loadingArt = false;
    },
    artUrl(a) { return "/wb-api/artifacts/file?path=" + encodeURIComponent(a.path); },
    fmtSize(n) { return n > 1048576 ? (n / 1048576).toFixed(1) + "MB" : Math.ceil(n / 1024) + "KB"; },
  },
  async mounted() {
    this.basket = WB.basket.list();
    try { this.flows = (await WB.api.get("/flows")).flows; } catch (e) {}
    try { this.runs = (await WB.api.get("/runs")).runs; } catch (e) {}
    try {
      const d = await WB.api.get("/artifacts");
      this.artifacts = d.artifacts; this.queue = d.queue;
    } catch (e) {}
  },
  template: `
  <div class="three-col">
    <!-- 左: 素材篮 -->
    <div class="card">
      <h3>素材篮({{ basket.length }})</h3>
      <div v-if="!basket.length" class="muted" style="padding:12px 0">
        空 —— 到资讯页点「＋加入素材篮」</div>
      <div v-for="m in basket" :key="m.id" class="list-item">
        <div class="t">{{ m.text || '(无标题)' }}</div>
        <div class="s">{{ m.time }} · {{ m.source }}
          <a style="float:right" @click.stop="removeMaterial(m.id)">移除</a></div>
      </div>
      <button v-if="basket.length" class="btn" style="width:100%;justify-content:center;margin-top:6px"
              @click="clearBasket">清空素材篮</button>
    </div>

    <!-- 中: 工作流区 -->
    <div>
      <div class="card">
        <h3>工作流</h3>
        <div class="form-row">
          <label>选择工作流</label>
          <select v-model="selFlow" style="width:260px">
            <option value="">(请选择)</option>
            <option v-for="fl in flows" :value="fl.name">{{ fl.name }} — {{ fl.title }}</option>
          </select>
        </div>
        <div class="stub-wrap">
          <button class="btn primary stub" disabled>开始生成</button>
          <div class="stub-tip">本期为展示壳; 实际生成请运行
            <code>python cli.py flows run {{ selFlow || '<工作流>' }} --auto</code></div>
        </div>
      </div>

      <div class="card">
        <h3>最近运行(状态机回显)</h3>
        <div v-if="!runs.length" class="muted">暂无运行记录(data/runs/)</div>
        <div v-for="r in runs.slice(0, 10)" :key="r.flow + r.date" class="list-item"
             :class="{sel: selRun === r}" @click="selRun = selRun === r ? null : r">
          <div class="t">{{ r.flow }} @ {{ r.date }}
            <span class="badge" :class="r.status === 'done' ? 'green' : 'yellow'"
                  style="float:right">{{ r.status }}</span></div>
          <div class="s">{{ r.mtime }}<span v-if="r.note"> · {{ r.note }}</span></div>
          <div v-if="selRun === r" style="margin-top:8px">
            <div v-for="(v, k) in r.steps" class="step-line">
              <span class="step-dot" :class="stepClass(v)"></span>{{ k }}: {{ v }}
            </div>
            <div v-for="(v, k) in r.artifacts" class="step-line">{{ k }}: <span class="mono">{{ v }}</span></div>
          </div>
        </div>
      </div>
    </div>

    <!-- 右: 产物与队列 -->
    <div>
      <div class="card">
        <h3>生成产物({{ artifacts.length }})</h3>
        <div v-if="!artifacts.length" class="muted">暂无(generator/output/)</div>
        <div v-for="a in artifacts.slice(0, 20)" :key="a.path" class="list-item"
             :class="{sel: selArt === a}" @click="preview(a)">
          <div class="t">{{ a.name }}</div>
          <div class="s">{{ a.mtime }} · {{ fmtSize(a.size) }}</div>
        </div>
        <div v-if="selArt" style="margin-top:10px">
          <img v-if="['png','jpg'].includes(selArt.kind)" :src="artUrl(selArt)" class="cover-thumb">
          <div v-else class="md-preview">{{ loadingArt ? '读取中…' : artContent }}</div>
        </div>
      </div>

      <div class="card">
        <h3>待发队列({{ queue.length }})</h3>
        <div v-if="!queue.length" class="muted">空(autopub/articles/)</div>
        <div v-for="q in queue" :key="q.name" class="list-item">
          <div class="t">{{ q.name }}</div>
          <div class="s">{{ q.mtime }} · {{ fmtSize(q.size) }}</div>
        </div>
        <div class="stub-wrap" style="margin-top:10px">
          <button class="btn stub" disabled>推入队列</button>
          <button class="btn stub" disabled>发布</button>
          <div class="stub-tip">红线: 发布必须先 <code>python cli.py publish run --draft</code> 验证</div>
        </div>
      </div>
    </div>
  </div>`,
};
