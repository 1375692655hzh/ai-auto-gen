"""同花顺(10jqka)自动发布 —— 占位骨架

形态:同花顺圈子 / 股吧发帖(t.10jqka.com.cn 等)。需登录。
计划:校准时确定发帖入口、标题/正文/发布 selector。参照 laohu.py 实现。
"""

from pathlib import Path
from .base import BrowserPublisher


class TonghuashunPublisher(BrowserPublisher):
    name = "tonghuashun"
    profile_dir = str(Path.home() / ".tonghuashun_chrome_profile")
    compose_url = "https://t.10jqka.com.cn/"             # [校准]
    logged_in_keywords = ["我的", "发布", "退出"]         # [校准]

    async def publish_one(self, page, article: dict, draft: bool) -> dict:
        raise NotImplementedError("同花顺适配器待校准:先跑通老虎,再按 laohu.py 模板实现")
