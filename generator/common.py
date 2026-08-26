"""生成模块公共层:路径/配置/LLM 桥接(复用 autopub 的模型接口)。

LLM 的 provider、api_key、模型名全部沿用 autopub 的配置链
(config.yaml model 段 <- secret.local.json <- AUTOPUB_API_KEY 环境变量),
生成侧不另搞一套,在网页控制台填一次两边共用。
"""

import sys
import re
import json
import datetime
from pathlib import Path

import yaml

GEN_ROOT = Path(__file__).resolve().parent
AUTOPUB_ROOT = GEN_ROOT.parent / "autopub"

# 让 generator 下的脚本无论从哪个 cwd 启动都能 import 同目录模块
if str(GEN_ROOT) not in sys.path:
    sys.path.insert(0, str(GEN_ROOT))


def load_cfg() -> dict:
    with open(GEN_ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def out_dir(key: str) -> Path:
    """按配置解析输出目录并确保存在。key: articles_dir / scripts_dir / research_dir"""
    p = Path(load_cfg()["output"][key])
    if not p.is_absolute():
        p = GEN_ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def today() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d")


def now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def safe_filename(name: str) -> str:
    """主题/标题转安全文件名:去掉 Windows 非法字符与空白。"""
    name = re.sub(r'[\\/:*?"<>|\s]+', "-", name).strip("-.")
    return name[:60] or "untitled"


def save_text(path: Path, text: str) -> Path:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path


# ---------- LLM 桥接 ----------

def _autopub_llm():
    sys.path.insert(0, str(AUTOPUB_ROOT))
    import llm  # autopub/llm.py
    return llm


def llm_require_config():
    llm = _autopub_llm()
    if not llm.is_configured():
        sys.exit(
            "模型 API 未配置。三种方式任选:\n"
            "  1. 打开 autopub 网页控制台(python autopub/webapp/app.py → 127.0.0.1:5001)在「模型 API 设置」里填\n"
            "  2. 设环境变量 AUTOPUB_API_KEY,并在 autopub/config.yaml 的 model: 段填 provider 和 model\n"
            "  3. 直接编辑 autopub/secret.local.json(provider/api_key/model/base_url)"
        )
    return llm


def llm_complete(prompt: str, system: str = "", max_tokens: int = 4000,
                 temperature: float = 0.4, timeout: int = 300) -> str:
    """生成流程专用:未配置/失败要明确报错,不能像 chart_gap 那样静默降级。"""
    llm = llm_require_config()
    out = llm._complete_raw(prompt, system, max_tokens, temperature, timeout)
    if not out:
        raise RuntimeError("模型返回为空,请检查模型名与账户额度")
    return strip_thinking(out).strip()


def strip_thinking(text: str) -> str:
    """剥掉推理模型(如 MiniMax-M3/DeepSeek-R1)混在正文里的 <think> 思考过程。"""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # 未闭合的 think 块(截断时):从头删到 </think> 或保留结尾正文
    if "<think>" in text and "</think>" not in text:
        text = text.split("<think>", 1)[0]
    return text.strip()


def llm_status() -> dict:
    llm = _autopub_llm()
    return llm.status()


# ---------- 杂项 ----------

def parse_llm_list(text: str) -> list:
    """从模型回复中提取 JSON 数组;模型有时会包 ```json 围栏。"""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except Exception:
        return []


def confirm(question: str, default_yes: bool = True) -> bool:
    tip = "[Y/n]" if default_yes else "[y/N]"
    ans = input(f"{question} {tip} ").strip().lower()
    if not ans:
        return default_yes
    return ans in ("y", "yes", "是")
