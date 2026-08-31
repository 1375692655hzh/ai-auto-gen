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

GEN_ROOT = Path(__file__).resolve().parent          # ai-workflow/generator
AIWF_ROOT = GEN_ROOT.parent                          # ai-workflow
PROJ_ROOT = AIWF_ROOT.parent                         # 项目根
AUTOPUB_ROOT = PROJ_ROOT / "auto-publisher" / "autopub"

# 让 generator 下的脚本无论从哪个 cwd 启动都能 import 同目录模块;
# 同时挂上板块一(global-news-sources + fetchers)与板块二根(flows 包)
if str(GEN_ROOT) not in sys.path:
    sys.path.insert(0, str(GEN_ROOT))
_GNS = PROJ_ROOT / "global-news-sources"
for _p in (AIWF_ROOT, _GNS, _GNS / "fetchers"):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.append(str(_p))


# ---------- 生成链统一模型分发 ----------

def gen_default_model() -> str:
    """生成链默认模型: data/config.local.yaml 的 gen_model, 未配置=ark:kimi-k3。
    (2026-08-30 定案: 五条链横评全选 kimi-k3; 此前空 model 会漏进 autopub secret 的 deepseek)"""
    override = Path(PROJ_ROOT / "data" / "config.local.yaml")
    if override.exists():
        try:
            v = (yaml.safe_load(override.read_text(encoding="utf-8")) or {}).get("gen_model", "")
            if v:
                return str(v)
        except Exception:
            pass
    return "ark:kimi-k3"


def kimi_api_key() -> str:
    """Kimi 官方 API key(备用通道): autopub/secret.local.json 的 kimi_api_key 或环境变量 KIMI_API_KEY。未配=空串(通道自动跳过)。"""
    import os
    if os.environ.get("KIMI_API_KEY"):
        return os.environ["KIMI_API_KEY"]
    p = AUTOPUB_ROOT / "secret.local.json"
    if p.exists():
        try:
            return str(json.loads(p.read_text(encoding="utf-8")).get("kimi_api_key", "") or "")
        except Exception:
            pass
    return ""


def kimi_api_complete(user: str, system: str, max_tokens: int) -> str:
    """Kimi 官方 API 直连(OpenAI 兼容)。模型名可被 secret 的 kimi_api_model 覆盖,默认 kimi-k3。"""
    import urllib.request
    key = kimi_api_key()
    if not key:
        raise RuntimeError("kimi api key 未配置")
    model = "kimi-k3"
    p = AUTOPUB_ROOT / "secret.local.json"
    if p.exists():
        try:
            model = str(json.loads(p.read_text(encoding="utf-8")).get("kimi_api_model", "") or model)
        except Exception:
            pass
    body = json.dumps({"model": model, "messages": [
        *( [{"role": "system", "content": system}] if system else [] ),
        {"role": "user", "content": user}],
        "max_tokens": max_tokens, "temperature": 0.3}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.moonshot.cn/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        out = json.loads(r.read().decode("utf-8"))
    text = (out.get("choices") or [{}])[0].get("message", {}).get("content", "")
    if not text:
        raise RuntimeError("kimi api 返回为空")
    return text


def gen_llm(model: str, user: str, system: str, max_tokens: int, temperature: float = 0.4) -> str:
    """生成链统一分发(morning._llm_call 与 daily._llm 的共同实现)。
    回落顺序: ark:<名>(arkcli 订阅) → kimi 官方 API(配了 key 才启用) → 默认通道(最后兜底)。
    空 model = gen_default_model()(即 kimi-k3)。"""
    model = (model or "").strip() or gen_default_model()
    if model.startswith("ark:"):
        try:
            if str(PROJ_ROOT) not in sys.path:
                sys.path.insert(0, str(PROJ_ROOT))
            from flows.steps.morning import _ark_complete
            return _ark_complete(user, system, model[4:], max_tokens=max_tokens)
        except RuntimeError as e:
            print(f"⚠ ark 通道失败({e}), 尝试降级")
        if kimi_api_key():
            try:
                print("↓ 降级 kimi 官方 API")
                return kimi_api_complete(user, system, max_tokens)
            except Exception as e:
                print(f"⚠ kimi api 失败({e}), 降级默认通道")
        return llm_complete(user, system=system, max_tokens=max_tokens, temperature=temperature)
    return llm_complete(user, system=system, max_tokens=max_tokens, temperature=temperature)


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
            "  1. 打开 autopub 网页控制台(python auto-publisher/autopub/webapp/app.py → 127.0.0.1:5001)在「模型 API 设置」里填\n"
            "  2. 设环境变量 AUTOPUB_API_KEY,并在 auto-publisher/autopub/config.yaml 的 model: 段填 provider 和 model\n"
            "  3. 直接编辑 auto-publisher/autopub/secret.local.json(provider/api_key/model/base_url)"
        )
    return llm


def llm_complete(prompt: str, system: str = "", max_tokens: int = 4000,
                 temperature: float = 0.4, timeout: int = 300, retries: int = 3) -> str:
    """生成流程专用:未配置/失败要明确报错;网络类失败自动重试(限流/抖动兜底)。"""
    import time
    llm = llm_require_config()
    last_err = None
    for attempt in range(retries):
        try:
            out = llm._complete_raw(prompt, system, max_tokens, temperature, timeout)
            if not out:
                raise RuntimeError("模型返回为空,请检查模型名与账户额度")
            return strip_thinking(out).strip()
        except RuntimeError:
            raise  # 业务性错误(配置/额度)不重试
        except Exception as e:  # 网络超时/连接类,退避后重试
            last_err = e
            if attempt < retries - 1:
                wait = 15 * (attempt + 1)
                print(f"  ⚠ LLM 调用失败({type(e).__name__}),{wait}s 后重试({attempt + 2}/{retries})")
                time.sleep(wait)
    raise last_err


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
