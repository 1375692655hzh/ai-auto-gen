"""可配置的模型接口 —— 团队接入自己的模型 API

发布流程里唯一用到大模型的地方是 chart_gap.py(知乎/东财把传不上的图表转成文字说明)。
原来写死走作者本机的 `claude` CLI 订阅账号,别人没有就用不了。
这里抽象成一个统一入口 complete(),团队各自在「设置」里填自己的 API key 即可。

配置来源(后者覆盖前者):
  1. config.yaml 的 model: 段(模板,api_key 留空)
  2. secret.local.json(网页「模型 API 设置」写入,**不分享**,已在 .gitignore)

支持的 provider:
  - openai_compatible : 任何 OpenAI 兼容的 /chat/completions 接口
       适配 OpenAI / DeepSeek / 通义千问 / Moonshot(Kimi) / 智谱 / 本地 Ollama 等
  - claude_cli        : 走本机 `claude` CLI(作者订阅账号,团队一般不用)

对外只暴露 complete(prompt, system=...) -> str;没配好就返回 ""(调用方自行降级)。
"""

import os
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SECRET_FILE = ROOT / "secret.local.json"

# 常见 OpenAI 兼容服务的默认 base_url(网页里选 provider 自动带出,可改)
PRESET_BASE_URLS = {
    "openai":     "https://api.openai.com/v1",
    "deepseek":   "https://api.deepseek.com/v1",
    "qwen":       "https://dashscope.aliyuncs.com/compatible-mode/v1",  # 通义千问
    "moonshot":   "https://api.moonshot.cn/v1",                          # Kimi
    "zhipu":      "https://open.bigmodel.cn/api/paas/v4",                # 智谱 GLM
    "ollama":     "http://localhost:11434/v1",                          # 本地
}


# ---------- 配置读取 ----------

def _load_yaml_model_cfg() -> dict:
    try:
        import yaml
        with open(ROOT / "config.yaml", encoding="utf-8") as f:
            return (yaml.safe_load(f) or {}).get("model", {}) or {}
    except Exception:
        return {}


def _load_secret() -> dict:
    if SECRET_FILE.exists():
        try:
            return json.loads(SECRET_FILE.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
    return {}


def load_config() -> dict:
    """合并后的模型配置: config.yaml(模板) <- secret.local.json(本机密钥)。"""
    cfg = {"provider": "openai_compatible", "base_url": "", "model": "", "api_key": ""}
    cfg.update(_load_yaml_model_cfg())
    cfg.update(_load_secret())          # 本机密钥优先
    # 环境变量兜底(CI / 高级用户)
    if not cfg.get("api_key"):
        cfg["api_key"] = os.environ.get("AUTOPUB_API_KEY", "")
    # provider 选了预设但没填 base_url → 自动补默认
    if not cfg.get("base_url") and cfg.get("provider") in PRESET_BASE_URLS:
        cfg["base_url"] = PRESET_BASE_URLS[cfg["provider"]]
    return cfg


def save_secret(provider: str, api_key: str, model: str, base_url: str = "") -> None:
    """网页「模型 API 设置」保存入口。写到 secret.local.json(不分享)。"""
    data = {
        "provider": provider,
        "api_key": api_key.strip(),
        "model": model.strip(),
        "base_url": (base_url or PRESET_BASE_URLS.get(provider, "")).strip(),
    }
    SECRET_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def is_configured() -> bool:
    cfg = load_config()
    if cfg.get("provider") == "claude_cli":
        return True
    return bool(cfg.get("api_key") and cfg.get("model"))


def status() -> dict:
    """给网页展示用:是否配好 + 脱敏信息(不回传 key 明文)。"""
    cfg = load_config()
    key = cfg.get("api_key", "")
    return {
        "configured": is_configured(),
        "provider": cfg.get("provider", ""),
        "model": cfg.get("model", ""),
        "base_url": cfg.get("base_url", ""),
        "api_key_masked": (key[:4] + "***" + key[-4:]) if len(key) > 8 else ("***" if key else ""),
    }


# ---------- 调用 ----------

def complete(prompt: str, system: str = "", max_tokens: int = 1024,
             temperature: float = 0.3, timeout: int = 90) -> str:
    """统一补全入口。失败/未配置返回 ""(供 chart_gap 优雅降级)。"""
    try:
        return _complete_raw(prompt, system, max_tokens, temperature, timeout)
    except Exception:
        return ""


def _complete_raw(prompt, system, max_tokens, temperature, timeout) -> str:
    """同 complete,但失败会抛异常(给「测试连接」拿真实错误)。"""
    cfg = load_config()
    if cfg.get("provider") == "claude_cli":
        return _call_claude_cli(prompt, timeout=timeout)
    return _call_openai_compatible(cfg, prompt, system, max_tokens, temperature, timeout)


def _call_openai_compatible(cfg, prompt, system, max_tokens, temperature, timeout) -> str:
    import requests
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base or not cfg.get("api_key") or not cfg.get("model"):
        return ""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    r = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {cfg['api_key']}",
                 "Content-Type": "application/json"},
        json={"model": cfg["model"], "messages": messages,
              "max_tokens": max_tokens, "temperature": temperature},
        timeout=timeout,
    )
    if r.status_code != 200:
        # 把服务商返回的真实错误抛出来(401 key 无效 / 400 模型名错 等)
        detail = ""
        try:
            detail = r.json().get("error", {}).get("message", "")
        except Exception:
            detail = r.text[:200]
        raise RuntimeError(f"HTTP {r.status_code}: {detail}")
    data = r.json()
    choice = data["choices"][0]
    if choice.get("finish_reason") == "length" and max_tokens < 8192:
        # 思考型模型(deepseek-r1/GLM思考/o1类)会把 token 先花在思考上,
        # 小额度必截断 —— 自动放大 8 倍重试一次(上限 8192)
        return _call_openai_compatible(cfg, prompt, system,
                                       min(max_tokens * 8, 8192),
                                       temperature, timeout)
    if choice.get("finish_reason") == "length":
        raise RuntimeError("LLM 输出被 max_tokens 截断(finish_reason=length),"
                           " 提高调用方 max_tokens 或精简提示词后重试")
    return (choice["message"]["content"] or "").strip()


def _call_claude_cli(prompt: str, timeout: int = 90) -> str:
    """作者本机 `claude` CLI(订阅账号)。剥代理/key 环境避免冲突。"""
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "HTTPS_PROXY", "HTTP_PROXY",
                        "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy")}
    r = subprocess.run(
        ["claude", "-p", "--model", "sonnet", "--output-format", "text"],
        input=prompt, capture_output=True, text=True, timeout=timeout, env=env)
    return r.stdout.strip() if r.returncode == 0 else ""


def test_connection() -> tuple:
    """网页「测试连接」用。返回 (ok: bool, message: str)。"""
    if not is_configured():
        return False, "尚未配置:请填写 API key 和模型名"
    try:
        out = _complete_raw("请只回复两个字:正常", "", 1024, 0.3, 60)
    except Exception as e:
        return False, f"调用失败:{e}"
    if out:
        return True, f"连接成功 ✅ 模型回复:{out[:30]}"
    return False, "调用失败:模型返回为空,请检查模型名/账户额度"
