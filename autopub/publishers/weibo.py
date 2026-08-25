"""微博(weibo.com)自动发布 —— 占位骨架(风控最严,放最后)

形态:首页发微博框(短文);长文走「头条文章」(card.weibo.com/article)。
风控:navigator.webdriver / 指纹 / 频率检测最严,底座反风控三件套必开,
      发布间隔要更长,日上限更低(config 默认 8)。
计划:校准时确定短文框 or 头条文章编辑器、发布按钮。参照 laohu.py 实现。
"""

from pathlib import Path
from .base import BrowserPublisher


class WeiboPublisher(BrowserPublisher):
    name = "weibo"
    profile_dir = str(Path.home() / ".weibo_chrome_profile")
    compose_url = "https://weibo.com/"                   # [校准] 长文用 card.weibo.com/article
    logged_in_keywords = ["首页", "发微博", "我的主页", "退出"]  # [校准]

    async def publish_one(self, page, article: dict, draft: bool) -> dict:
        raise NotImplementedError("微博适配器待校准:风控最严,最后做;参照 laohu.py 模板")
