"""工作流基类:所有财经内容工作流的统一骨架。

能力:
- 步骤声明:子类定义 steps() 返回 [(名称, 函数, 是否审核点)]
- 断点续跑:每步产物存档到 output/workflows/<工作流>/<日期>/<步骤>.json,
  重跑同日期默认复用已完成的步骤(--fresh 强制重来,--from 从指定步骤重跑)
- 审核点:标记 review=True 的步骤完成后暂停,人工确认后继续(--auto 跳过)
- 运行统计:各步耗时、LLM/搜索调用次数汇总
"""

import json
import sys
import time
from pathlib import Path

from common import GEN_ROOT, today


class WorkflowBase:
    name = "base"            # 工作流标识(注册名)
    title = "未命名工作流"     # 展示名
    description = ""

    def __init__(self, date: str | None = None):
        self.date = date or today()
        self.run_dir = GEN_ROOT / "output" / "workflows" / self.name / self.date
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.ctx = {}         # 步骤间传递的上下文
        self.stats = {"steps": {}, "llm_calls": 0, "search_calls": 0}

    # ---- 子类实现 ----

    def steps(self) -> list:
        """返回 [(步骤名, 执行函数, 是否审核点)],函数签名 f(ctx) -> dict(并入 ctx)。"""
        raise NotImplementedError

    # ---- 存档/续跑 ----

    def _ckpt_path(self, step: str) -> Path:
        return self.run_dir / f"{step}.json"

    def _load_ckpt(self, step: str):
        p = self._ckpt_path(step)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def _save_ckpt(self, step: str, data) -> None:
        """存档要可 JSON 化:步骤函数返回 dict 时其中不可序列化的对象自行转好。"""
        self._ckpt_path(step).write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # ---- 执行 ----

    def run(self, auto: bool = False, from_step: str | None = None,
            fresh: bool = False, only: str | None = None) -> dict:
        if fresh:
            for p in self.run_dir.glob("*.json"):
                p.unlink()
        step_list = self.steps()
        names = [s[0] for s in step_list]
        if from_step and from_step not in names:
            raise SystemExit(f"未知步骤 {from_step},可选: {', '.join(names)}")
        if only and only not in names:
            raise SystemExit(f"未知步骤 {only},可选: {', '.join(names)}")

        started = False
        for step_name, fn, is_review in step_list:
            if from_step and step_name != from_step and not started:
                # 未到起点:装载存档继续传递上下文
                ck = self._load_ckpt(step_name)
                if ck is not None:
                    self.ctx.update(ck)
                continue
            if from_step:
                started = True
            if only and step_name != only:
                # --only:目标步骤之前的存档也装载,保证上下文完整
                if step_list.index((step_name, fn, is_review)) < [s[0] for s in step_list].index(only):
                    ck = self._load_ckpt(step_name)
                    if ck is not None:
                        self.ctx.update(ck)
                continue

            if getattr(fn, "is_skip", False):
                # 条件跳过的步骤: 不执行也不落存档(否则换参数重跑会被空存档卡住)
                continue

            # 断点复用(非 --from/--only 重跑时,已有存档的步骤直接跳过)
            replay = bool(from_step or only or fresh)
            if not replay:
                ck = self._load_ckpt(step_name)
                if ck is not None:
                    self.ctx.update(ck)
                    print(f"[{self.name}] {step_name}: 已有存档,跳过(重跑加 --from {step_name})")
                    continue

            t0 = time.time()
            print(f"\n[{self.name}] ▶ 步骤 {step_name} ...")
            out = fn(self.ctx) or {}
            self.ctx.update(out)
            self._save_ckpt(step_name, out)
            dt = time.time() - t0
            self.stats["steps"][step_name] = round(dt, 1)
            print(f"[{self.name}] ✓ {step_name} 完成({dt:.0f}s)")

            if is_review and not auto:
                import os
                non_tty = (not sys.stdin.isatty()
                           or os.environ.get("AAG_NONINTERACTIVE") == "1")
                if non_tty:
                    # 非交互环境(agent/CI): 不阻塞, 挂起等外部审核后重跑续跑
                    self._on_review_pause(step_name)
                    print(f"\n⏸ 审核点[{step_name}] 挂起(非交互): 产物在 {self.run_dir}\n"
                          f"   人工检查/修改后重跑同一命令自动续跑(存档已复用, 不重复花钱)")
                    raise SystemExit(2)
                try:
                    ans = input(f"\n⏸ 审核点[{step_name}]:产物在 {self.run_dir}\n"
                                "   检查/修改后回车继续(r=从本步重跑,q=退出): ").strip().lower()
                except EOFError:
                    self._on_review_pause(step_name)
                    print(f"\n⏸ 审核点[{step_name}] 挂起(stdin 关闭): 产物在 {self.run_dir}")
                    raise SystemExit(2)
                if ans == "q":
                    print("已退出。重跑: python generator/main.py run "
                          f"{self.name} --from {step_name}")
                    raise SystemExit(0)
                if ans == "r":
                    self._ckpt_path(step_name).unlink()
                    return self.run(auto=False, from_step=step_name)
        return self.ctx

    def _on_review_pause(self, step_name: str) -> None:
        """审核点在非交互环境挂起时的钩子(子类可覆盖, 如写 run.json)。默认无操作。"""
        return

    def summary(self) -> str:
        secs = sum(self.stats["steps"].values())
        return (f"{self.title} | {self.date} | 总耗时 {secs:.0f}s | "
                f"步骤: {', '.join(f'{k}({v}s)' for k, v in self.stats['steps'].items())}")
