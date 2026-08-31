"""工作流注册表:新工作流在这里 import 即可被 `run` 命令发现。"""

from workflows.base import WorkflowBase
from workflows.morning_paper import MorningPaperWorkflow

WORKFLOWS = {
    MorningPaperWorkflow.name: MorningPaperWorkflow,
}


def get_workflow(name: str):
    if name not in WORKFLOWS:
        raise SystemExit(f"未知工作流 {name},可选: {', '.join(WORKFLOWS)}\n"
                         "新增:在 generator/workflows/ 写子类并在 __init__.py 注册")
    return WORKFLOWS[name]
