# auto-publisher

独立的「读取固定文件夹里的文章 → 自动发到多个平台」系统。

从 `stock-media-v2` 的雪球/知乎自动发经验抽出来的通用框架,本身不依赖那个项目。

> **团队成员请先看 [使用指南.md](使用指南.md)**(零门槛网页操作 + 首次登录说明)。
> 这是一份**空白模板**:不含任何人的登录信息/文章,每个人首次使用需自己登录各平台、填自己的模型 API。

## 最快上手:网页控制台

```bash
pip3 install flask playwright pyyaml python-docx requests
python3 -m playwright install chromium
python3 webapp/app.py        # 打开 http://127.0.0.1:5001
```

网页里:① 填自己的模型 API(可选) ② 上传文章 ③ 勾选平台 ④ 一键发。详见 [使用指南.md](使用指南.md)。

## 目标平台

| 平台 | 适配器 | 状态 |
|---|---|---|
| 老虎社区 laohu8 | `publishers/laohu.py` | 🔧 待真站校准 |
| 东方财富股吧 | `publishers/eastmoney.py` | ⏳ 占位 |
| 同花顺 | `publishers/tonghuashun.py` | ⏳ 占位 |
| 微博 | `publishers/weibo.py` | ⏳ 占位(风控最严) |
| 雪球 xueqiu | `publishers/xueqiu.py` | ✅ 已验证(stock-media-v2 移植) |
| 知乎 zhihu | `publishers/zhihu.py` | ✅ 已验证(stock-media-v2 移植) |

## 用法

```bash
# 把待发文章放进 articles/(每个 .md 一篇;第一行非空行=标题,其余=正文)

# 单平台发布(真发)
python publish.py --platform laohu

# 校准模式:只打开页面、填内容、截图,不真发(看排版/对选择器)
python publish.py --platform laohu --draft

# 限制本次最多发几篇
python publish.py --platform laohu --limit 3

# 看每篇在各平台的发布状态
python publish.py --status
```

## 复用的核心底座(7 件套)

1. Playwright 启**本机真 Chrome** + **每平台独立 profile**(`~/.{platform}_chrome_profile`),登录态持久化,首次手动登录一次
2. 反风控三件套:`--disable-blink-features=AutomationControlled` + 去掉 `enable-automation` + 抹掉 `navigator.webdriver`
3. 登录态检测(页面关键词 / URL)+ 轮询等你手动登录
4. 验证码 / 安全验证:检测到就截图 + 暂停等你手动过
5. 内容处理:markdown 扁平化(`content.py`)+ 平台特有的股票标签处理
6. 幂等:`state.json` 侧车账本记录每篇在每个平台发没发过(**不改你的原文**)
7. 节流熔断:日上限 + 篇间隔 + 连续失败 3 次停

## 加一个新平台

写 `publishers/{name}.py`,继承 `BrowserPublisher`,填 4 样东西即可:
- `name` / `profile_dir` / `compose_url` / `logged_in_keywords`
- 实现 `publish_one(page, article, draft)`(填标题/正文 → 点发布 → 验证)

然后在 `publishers/__init__.py` 注册。
```
