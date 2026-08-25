"""侧车发布账本(state.json)

不改用户原文,单独记录每篇文章在每个平台的发布状态:
{
  "2026Q1_xxx.md": {
    "laohu":  {"status": "published", "time": "...", "url": "...", "note": ""},
    "weibo":  {"status": "failed",    "time": "...", "url": "",    "note": "风控未过"}
  }
}
status ∈ published / failed
"""

import json
from pathlib import Path
from datetime import datetime
from threading import Lock

_LOCK = Lock()


class State:
    def __init__(self, path):
        self.path = Path(path)
        self._data = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}

    def is_published(self, article_id: str, platform: str) -> bool:
        return self._data.get(article_id, {}).get(platform, {}).get("status") == "published"

    def get(self, article_id: str, platform: str) -> dict:
        return self._data.get(article_id, {}).get(platform, {})

    def mark(self, article_id: str, platform: str, status: str,
             url: str = "", note: str = "") -> None:
        with _LOCK:
            self._data.setdefault(article_id, {})[platform] = {
                "status": status,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "url": url,
                "note": note,
            }
            self._flush()

    def _flush(self) -> None:
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def summary(self) -> dict:
        return self._data
