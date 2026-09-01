"""腾讯文档 OpenAPI 轻客户端 —— 纯 Python, 不依赖 mcporter/npm/skill

直连 https://docs.qq.com/openapi/mcp (MCP-over-HTTP)。实测该端点支持
无状态单次 tools/call POST(无需 initialize 握手), 鉴权就是
Authorization: <Token> 头, 所以一个 urllib 就够。

Token: 一次授权长期使用(过期重新授权即可), 存本目录 secret.local.json
的 tdoc_token 字段(该文件在 .gitignore, 不随仓库分发)。

授权 = OAuth 三步: 本地随机 code → 浏览器扫码授权 → 轮询
GET https://docs.qq.com/oauth/v2/mcp/token/get?code=<code> 拿 Token。

用法:
  py tdoc_client.py auth          # 命令行一键授权向导
  py tdoc_client.py status        # 查看授权状态
  from tdoc_client import TDocClient, load_token
"""

import json
import secrets as _secrets
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SECRET_FILE = ROOT / "secret.local.json"
MCP_URL = "https://docs.qq.com/openapi/mcp"
TOKEN_URL = "https://docs.qq.com/oauth/v2/mcp/token/get"
AUTH_PAGE = "https://docs.qq.com/scenario/open-claw.html"


class TDocError(RuntimeError):
    pass


def load_token() -> str:
    try:
        return (json.loads(SECRET_FILE.read_text(encoding="utf-8"))
                .get("tdoc_token") or "")
    except Exception:
        return ""


def save_token(token: str) -> None:
    d = {}
    try:
        d = json.loads(SECRET_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    d["tdoc_token"] = token
    SECRET_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                           encoding="utf-8")


class TDocClient:
    def __init__(self, token: str):
        if not token:
            raise TDocError("未授权: 请先运行 py tdoc_client.py auth")
        self.token = token

    def call(self, tool: str, arguments: dict) -> dict:
        """调一个 OpenAPI 工具, 返回其 JSON 结果; 出错抛 TDocError。"""
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": tool, "arguments": arguments or {}}}
        req = urllib.request.Request(
            MCP_URL, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Accept": "application/json",
                     "Authorization": self.token})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                d = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # 400006=Token 失效(见 tencent-docs skill 错误码表)
            raise TDocError(f"HTTP {e.code}: Token 失效或无权限, 请重新授权"
                            f"(py tdoc_client.py auth)") from e
        if d.get("error"):
            raise TDocError(f"{tool}: {d['error']}")
        try:
            inner = json.loads(d["result"]["content"][0]["text"])
        except Exception:
            raise TDocError(f"{tool}: 返回结构异常: {str(d)[:200]}")
        if inner.get("error"):
            raise TDocError(f"{tool}: {inner['error']}")
        return inner


# ---------- OAuth 授权 ----------

def make_auth_code() -> str:
    return _secrets.token_hex(8)


def auth_url(code: str) -> str:
    return f"{AUTH_PAGE}?nlc=1&authType=1&code={code}&mcp_source=desktop"


def poll_token(code: str) -> tuple:
    """轮询一次。返回 ("ok", token) / ("pending", None) / ("error", msg)。"""
    try:
        with urllib.request.urlopen(f"{TOKEN_URL}?code={code}", timeout=15) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return "error", f"token/get 请求失败: {e}"
    tok = ((d.get("data") or {}).get("token")
           or d.get("token") or "")
    if tok:
        return "ok", tok
    # 无 token 但也无异常 → 用户还没在浏览器完成授权, 继续等
    if d.get("error") or d.get("code") in (-1, 1):
        return "error", json.dumps(d, ensure_ascii=False)[:200]
    return "pending", None


def cli_auth():
    code = make_auth_code()
    url = auth_url(code)
    print("🔑 腾讯文档授权")
    print("1) 即将打开浏览器, 请用 QQ/微信 扫码授权")
    print(f"   打不开就手动访问:\n   {url}")
    print("2) 授权链接 5 分钟内有效; 完成后本窗口自动继续")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    for i in range(100):                       # 3s×100 ≈ 5 分钟
        time.sleep(3)
        st, val = poll_token(code)
        if st == "ok":
            save_token(val)
            print("✅ 授权成功, Token 已存 secret.local.json (tdoc_token)")
            print("   现在可以在控制台用'腾讯文档链接导入'了(图文完整导出)")
            return 0
        if st == "error":
            print(f"❌ 授权失败: {val}")
            return 1
        print(f"  等待浏览器完成授权… ({(i + 1) * 3}s)")
    print("❌ 超时(5 分钟)。请重新运行 py tdoc_client.py auth")
    return 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "auth":
        sys.exit(cli_auth())
    # 默认/ status: 查状态(有 Token 就真调一次接口验证)
    tok = load_token()
    if not tok:
        print("❌ 未授权 → 运行: py tdoc_client.py auth")
        sys.exit(1)
    try:
        d = TDocClient(tok).call("manage.folder_list", {"parent_id": ""})
        print("✅ 已授权且有效(能访问文档列表)")
    except TDocError as e:
        print(f"❌ Token 不可用: {e} → 重新运行: py tdoc_client.py auth")
        sys.exit(1)
