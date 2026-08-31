"""fetchers 独立运行兜底层: 配置与密钥路径解析。

完整仓库内: 指向项目根的 ai-workflow/ 与 auto-publisher/。
单独下载本板块: 回退到 global-news-sources/ 自身(config.yaml / secret.local.json 放板块根)。
被 ai-workflow 驱动时 common 已在 sys.path, 调用方优先 `from common import ...`,
仅当 ImportError(独立运行)才落到本模块。
"""

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent          # fetchers/
BOARD = HERE.parent                              # global-news-sources/


def repo_root() -> Path:
    """向上找含 ai-workflow 或 auto-publisher 的项目根; 找不到按独立使用返回 BOARD。"""
    for p in [BOARD] + list(BOARD.parents):
        if (p / "ai-workflow").is_dir() or (p / "auto-publisher").is_dir():
            return p
    return BOARD


def _autopub_root() -> Path:
    r = repo_root() / "auto-publisher" / "autopub"
    return r if r.is_dir() else BOARD


AUTOPUB_ROOT = _autopub_root()


def load_cfg() -> dict:
    """完整仓库读 ai-workflow/generator/config.yaml; 独立使用读本板块根 config.yaml。"""
    for p in (repo_root() / "ai-workflow" / "generator" / "config.yaml",
              BOARD / "config.yaml"):
        if p.exists():
            try:
                import yaml
                return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except Exception:
                pass
    return {}


def secret_value(key: str) -> str:
    """同名大写环境变量优先, 其次 auto-publisher/autopub/secret.local.json, 兜底板块根。"""
    env = os.environ.get(key.upper())
    if env:
        return env
    for p in (AUTOPUB_ROOT / "secret.local.json", BOARD / "secret.local.json"):
        if p.exists():
            try:
                return str(json.loads(p.read_text(encoding="utf-8")).get(key, "") or "")
            except Exception:
                pass
    return ""
