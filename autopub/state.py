"""侧车发布账本(state.json)

不改用户原文,单独记录每篇文章在每个平台的发布状态:
{
  "2026Q1_xxx.md": {
    "laohu":  {"status": "published", "time": "...", "url": "...", "note": ""},
    "weibo":  {"status": "failed",    "time": "...", "url": "",    "note": "风控未过"}
  }
}
status ∈ published / failed / uncertain(已点发布但结果未确认,禁止自动重试,需人工核实)

安全设计(防重发):
  - 原子写(临时文件 + os.replace),进程中途被杀不会留下截断 JSON
  - 账本损坏时备份 .corrupt-<ts> 并抛异常中止发布(而不是静默清零重发全部)
  - 每次 mark 前重新读盘合并(跨进程并发写不互相覆盖)
"""

import os
import json
from pathlib import Path
from datetime import datetime

# uncertain/publishing 视同"可能已发",一律跳过不自动重试
SKIP_STATUSES = ("published", "uncertain")


class StateCorruptError(RuntimeError):
    pass


class State:
    def __init__(self, path):
        self.path = Path(path)
        self._data = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as e:
                bak = self.path.with_suffix(
                    self.path.suffix + f".corrupt-{datetime.now():%Y%m%d%H%M%S}")
                try:
                    os.replace(self.path, bak)
                except Exception:
                    pass
                # 账本不可信时绝不能当空账本继续(会把全部历史文章重发一遍)
                raise StateCorruptError(
                    f"发布账本 {self.path} 损坏({e}),已备份到 {bak.name}。"
                    "请人工核对后恢复,再继续发布。") from e

    def is_published(self, article_id: str, platform: str) -> bool:
        return self._data.get(article_id, {}).get(platform, {}).get("status") == "published"

    def is_skip(self, article_id: str, platform: str) -> bool:
        """已发或结果未确认 → 跳过(防重复发布)。"""
        return (self._data.get(article_id, {}).get(platform, {})
                .get("status") in SKIP_STATUSES)

    def get(self, article_id: str, platform: str) -> dict:
        return self._data.get(article_id, {}).get(platform, {})

    def mark(self, article_id: str, platform: str, status: str,
             url: str = "", note: str = "") -> None:
        rec = {
            "status": status,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "url": url,
            "note": note,
        }
        # 跨进程安全: 读盘-合并-原子写(两个进程同时发布也不互相覆盖)
        data = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data.setdefault(article_id, {})[platform] = rec
        self._data = data
        self._flush()

    def _flush(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def summary(self) -> dict:
        return self._data
