"""flows 步骤库:可复用的工作流积木。

每个步骤签名: fn(ctx: dict, wf, params: dict) -> dict(并入 ctx)
  - ctx: 步骤间上下文(存档断点由引擎管)
  - wf:  工作流实例(提供 date/params)
  - params: YAML 里 with: 传入的参数
注册后即可在任意 workflow.yaml 里 `uses: <名>` 引用。
"""

import sys
from pathlib import Path

GEN = Path(__file__).resolve().parents[2] / "generator"
if str(GEN) not in sys.path:
    sys.path.insert(0, str(GEN))          # 步骤复用 generator 的成熟实现(daily/formats/...)

STEPS = {}


def step(name: str):
    def deco(fn):
        STEPS[name] = fn
        return fn
    return deco


from flows.steps import fetch as _fetch          # noqa: E402,F401  触发注册
from flows.steps import rank as _rank            # noqa: E402,F401
from flows.steps import expand as _expand        # noqa: E402,F401
from flows.steps import assemble as _assemble    # noqa: E402,F401
from flows.steps import formats as _formats      # noqa: E402,F401
from flows.steps import script as _script        # noqa: E402,F401
from flows.steps import video as _video          # noqa: E402,F401
from flows.steps import morning as _morning      # noqa: E402,F401
from flows.steps import image as _image            # noqa: E402,F401
