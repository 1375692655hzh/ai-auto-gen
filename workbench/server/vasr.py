"""mimo ASR 客户端(视频制作·音频路线, 2026-09-15)。

官方协议(实测+文档双确认): POST {base}/chat/completions, messages 仅一条 user
消息、content 只放 input_audio part(data URL base64)——**禁止带 text 部分**
(网关注入提示词, 带上 400); asr_options.language 可选 auto/zh/en。
响应 message.content = 纯文本转写稿; 本引擎**不提供任何时间戳**(官方文档明示,
唯一时长 usage.seconds), 时间轴由本地 whisper(align.mjs)另出——见 asr-timeline.mjs。
传输层照抄 vstudio.chat_completions 的代理双路径(系统代理优先, 传输失败强制直连重试)。
"""
import base64
import json
from pathlib import Path


class AsrError(Exception):
    """kind = 面向前端的安全分类(no_key/http_400/http_401/network/bad_response)。"""

    def __init__(self, kind: str, message: str = ""):
        super().__init__(message or kind)
        self.kind = kind
        self.message = (message or kind)[:200]


def _mime_of(path: Path) -> str:
    return "audio/wav" if path.suffix.lower() == ".wav" else "audio/mpeg"


def transcribe_file(path) -> dict:
    """转写本地 mp3/wav → {text, seconds, audio_tokens}; 失败抛 AsrError。"""
    import urllib.error
    import urllib.request

    from . import config

    cfg = config.load().get("asr") or {}
    base = str(cfg.get("base_url") or "").strip().rstrip("/")
    key = str(cfg.get("api_key") or "").strip()
    model = str(cfg.get("model") or "mimo-v2.5-asr").strip() or "mimo-v2.5-asr"
    language = str(cfg.get("language") or "zh").strip()
    if not (base and key):
        raise AsrError("no_key", "ASR 未配置: 设置页「语音识别」填 base_url 与 api_key")
    path = Path(path)
    mime = _mime_of(path)
    data = base64.b64encode(path.read_bytes()).decode()
    payload = {"model": model, "messages": [{"role": "user", "content": [
        {"type": "input_audio",
         "input_audio": {"data": f"data:{mime};base64,{data}",
                         "format": "wav" if mime == "audio/wav" else "mp3"}}]}]}
    if language in ("auto", "zh", "en"):
        payload["asr_options"] = {"language": language}

    def _post():
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            base + "/chat/completions", data=body, method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            return urllib.request.urlopen(req, timeout=300)     # 默认尊重系统代理
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = (e.read().decode("utf-8", "replace") or "")[:200]
            except Exception:
                pass
            raise AsrError(f"http_{e.code}", detail or f"HTTP {e.code}") from None
        except Exception:
            # 传输层失败 → 强制直连重试(系统代理可能拦此域名), 与 chat_completions 同款
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                return opener.open(req, timeout=300)
            except urllib.error.HTTPError as e:
                raise AsrError(f"http_{e.code}", f"直连重试 HTTP {e.code}") from None
            except Exception as e2:
                raise AsrError("network", f"默认/直连两路都不通: {type(e2).__name__}") from None

    response = _post()
    try:
        body = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        raise AsrError("bad_response", f"响应解析失败({type(e).__name__})") from None
    finally:
        try:
            response.close()
        except Exception:
            pass
    try:
        text = str(((body.get("choices") or [{}])[0].get("message") or {}).get("content")
                   or "").strip()
        usage = body.get("usage") or {}
    except Exception as e:
        raise AsrError("bad_response", f"响应结构异常({type(e).__name__})") from None
    if not text:
        raise AsrError("empty", "转写返回空文本(音频无人声或时长过短?)")
    return {"text": text,
            "seconds": usage.get("seconds"),
            "audio_tokens": (usage.get("prompt_tokens_details") or {}).get("audio_tokens")}
