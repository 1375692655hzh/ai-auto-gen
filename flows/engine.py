"""flows 引擎:YAML 编排的工作流执行器(P2)。

设计:
  - 复用 generator/workflows/base.py 的 WorkflowBase(存档/断点/--from/--only/统计),
    包装不重写;Python 类工作流逃生舱天然保留(旧注册表照常工作)
  - workflow.yaml 四要素: steps 序列 + with 参数 + when 布尔引用({params.x}) + review 标记
  - 步骤实现全部在 flows/steps/ 注册库(YAML 只做编排, 复杂逻辑下沉 Python)
  - 运行产物与状态: data/runs/<flow>/<date>/<step>.json + run.json
  - 审核点非交互挂起: 写 run.json(status=waiting_review)后 exit 2,
    人工改完产物重跑同一命令自动续跑(存档复用)
"""

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "generator"
if str(GEN) not in sys.path:
    sys.path.insert(0, str(GEN))

from workflows.base import WorkflowBase      # noqa: E402  (generator 的成熟骨架)
from flows.steps import STEPS                # noqa: E402

FLOWS_ROOT = Path(__file__).resolve().parent
RUNS_ROOT = ROOT / "data" / "runs"

_PARAM_REF = re.compile(r"^\{params\.(\w+)\}$")


def discover() -> dict:
    """扫描 builtin/ 与 imports/ 下的工作流包。返回 {id: 包目录}。"""
    out = {}
    for base in ("builtin", "imports"):
        d = FLOWS_ROOT / base
        if not d.exists():
            continue
        for wf_yaml in sorted(d.glob("*/workflow.yaml")):
            out[wf_yaml.parent.name] = wf_yaml.parent
    return out


def load_spec(pack_dir: Path) -> dict:
    spec = yaml.safe_load((pack_dir / "workflow.yaml").read_text(encoding="utf-8"))
    if not spec.get("id"):
        spec["id"] = pack_dir.name
    return spec


def lint(pack_dir: Path) -> list:
    """校验 workflow.yaml:结构/步骤引用/参数引用。返回错误列表(空=通过)。"""
    errs = []
    try:
        spec = load_spec(pack_dir)
    except Exception as e:
        return [f"workflow.yaml 解析失败: {e}"]
    for key in ("id", "title"):
        if not spec.get(key):
            errs.append(f"缺少必填字段: {key}")
    steps = spec.get("steps") or []
    if not steps:
        errs.append("steps 为空")
    ids = set()
    for st in steps:
        sid = st.get("id")
        if not sid:
            errs.append(f"步骤缺少 id: {st}")
            continue
        if sid in ids:
            errs.append(f"步骤 id 重复: {sid}")
        ids.add(sid)
        uses = st.get("uses")
        if uses and uses not in STEPS:
            errs.append(f"[{sid}] 未知步骤类型 uses:{uses} (可用: {sorted(STEPS)})")
        when = st.get("when")
        if when and not _PARAM_REF.match(str(when)):
            errs.append(f"[{sid}] when 只支持 {{params.x}} 形式, 当前: {when}")
        for k, v in (st.get("with") or {}).items():
            if isinstance(v, str) and v.startswith("{") and not _PARAM_REF.match(v):
                errs.append(f"[{sid}] with.{k} 只支持 {{params.x}} 引用, 当前: {v}")
    return errs


class YamlWorkflow(WorkflowBase):
    """由 workflow.yaml 驱动的工作流(继承 generator WorkflowBase 全部断点/审核语义)。"""

    def __init__(self, pack_dir: Path, date: str | None = None, overrides: dict | None = None):
        self.pack_dir = Path(pack_dir)
        self.spec = load_spec(self.pack_dir)
        self.name = self.spec["id"]
        self.title = self.spec.get("title", self.name)
        self.description = self.spec.get("description", "")
        self.params = dict(self.spec.get("params") or {})
        if overrides:
            self.params.update(overrides)
        # run_dir 用新标准位置(旧 Python 类工作流仍在 generator/output/workflows)
        self.run_dir = RUNS_ROOT / self.name / (date or "")
        super().__init__(date)           # 会按 self.name 重建旧位置 run_dir, 再覆盖回新位置
        self.run_dir = RUNS_ROOT / self.name / self.date
        self.run_dir.mkdir(parents=True, exist_ok=True)

    # ---- YAML 四要素求值 ----

    def _resolve(self, v):
        m = _PARAM_REF.match(v) if isinstance(v, str) else None
        return self.params.get(m.group(1)) if m else v

    def _skip_fn(self, step_id, reason):
        def fn(ctx):
            print(f"[{self.name}] · {step_id}: 跳过({reason})")
            return {}
        return fn

    def steps(self):
        out = []
        for st in self.spec.get("steps", []):
            sid = st.get("id", "?")
            when = st.get("when")
            if when and not self._resolve(when):
                out.append((sid, self._skip_fn(sid, f"when:{when}"), False))
                continue
            uses = st.get("uses")
            if uses not in STEPS:
                out.append((sid, self._skip_fn(sid, f"未注册步骤 {uses}"), False))
                continue
            params = {k: self._resolve(v) for k, v in (st.get("with") or {}).items()}
            impl = STEPS[uses]

            def fn(ctx, _impl=impl, _sid=sid, _p=params):
                return _impl(ctx, self, _p) or {}
            out.append((sid, fn, bool(st.get("review"))))
        return out

    # ---- run.json 状态文件 ----

    def run_json(self) -> Path:
        return self.run_dir / "run.json"

    def _write_run(self, status: str, note: str = "") -> None:
        steps = {}
        for name in [s.get("id") for s in self.spec.get("steps", [])]:
            ck = self.run_dir / f"{name}.json"
            steps[name] = ("done" if ck.exists() else "pending")
        for name, secs in self.stats["steps"].items():
            steps[name] = f"done({secs}s)"
        artifacts = {k: v for k, v in self.ctx.items() if k.endswith("_path")}
        self.run_json().write_text(json.dumps(
            {"flow": self.name, "date": self.date, "status": status, "note": note,
             "params": self.params, "steps": steps, "artifacts": artifacts,
             "run_dir": str(self.run_dir)},
            ensure_ascii=False, indent=2), encoding="utf-8")

    def _on_review_pause(self, step_name: str) -> None:
        self._write_run("waiting_review", f"审核点 {step_name} 等待人工确认(改产物后重跑续跑)")

    def run(self, auto=False, from_step=None, fresh=False, only=None):
        try:
            ctx = super().run(auto=auto, from_step=from_step, fresh=fresh, only=only)
        except SystemExit as e:
            self._write_run("waiting_review" if e.code == 2 else "stopped",
                            "审核挂起" if e.code == 2 else f"exit {e.code}")
            raise
        self._write_run("done")
        return ctx


def run_flow(name: str, date=None, auto=False, from_step=None, fresh=False,
             only=None, overrides: dict | None = None):
    packs = discover()
    if name not in packs:
        raise SystemExit(f"未知工作流: {name} (可用: {sorted(packs)})")
    wf = YamlWorkflow(packs[name], date=date, overrides=overrides)
    return wf.run(auto=auto, from_step=from_step, fresh=fresh, only=only)
