"""平台适配器注册表。新增平台 = 写一个模块 + 在这里登记。"""

from .laohu import LaohuPublisher
from .eastmoney import EastmoneyPublisher
from .xueqiu import XueqiuPublisher
from .zhihu import ZhihuPublisher
from .tonghuashun import TonghuashunPublisher
from .weibo import WeiboPublisher
from .futu import FutuPublisher
from .changqiao import ChangqiaoPublisher
from .bilibili import BilibiliPublisher
from .douyin import DouyinPublisher
from .weixin import WeixinPublisher

REGISTRY = {
    "laohu": LaohuPublisher,
    "eastmoney": EastmoneyPublisher,
    "xueqiu": XueqiuPublisher,
    "zhihu": ZhihuPublisher,
    "tonghuashun": TonghuashunPublisher,
    "weibo": WeiboPublisher,
    "futu": FutuPublisher,
    "changqiao": ChangqiaoPublisher,
    "bilibili": BilibiliPublisher,
    "douyin": DouyinPublisher,
    "weixin": WeixinPublisher,
}


def get_publisher(name, config, state, logger):
    if name not in REGISTRY:
        raise KeyError(f"未知平台: {name};已注册: {list(REGISTRY)}")
    return REGISTRY[name](config, state, logger)
