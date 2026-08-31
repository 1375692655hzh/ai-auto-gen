# auto-publisher — 板块三：自动发布

双引擎多平台发布：**autopub**（Python + Playwright，浏览器自动化）+ **adapters-kit**（Node.js，API 优先）+ **publish**（平台矩阵门面）。

## 结构

```
autopub/            浏览器发布引擎(10 平台, CDP 接管用户日常 Chrome)
  publish_all.py    一键发全部启用平台(幂等账本, 自动归档)
  publish_video.py  B站/抖音视频投稿
  login.py          一键登录(弹浏览器人工扫码)
  webapp/           Flask 本地控制台(127.0.0.1:5001, 模型配置/账本/队列)
  state.json        发布账本(防重发唯一依据, 原子写+损坏熔断, 不手编)
  articles/         待发队列(发完全平台自动归档 _done/)
adapters-kit/       Node API 适配器(搜狐/头条/网易/值得买; 92 单测)
publish/            平台矩阵门面(targets.yaml: 14 平台×引擎×验证状态)
```

## 用法（完整仓库内，经根 cli.py）

```bash
python cli.py publish status          # 待发队列 + 账本
python cli.py publish targets         # 平台矩阵
python cli.py publish login [平台]    # 一键登录
python cli.py publish run --draft     # 草稿验证(真发需人工确认后去掉 --draft)
python cli.py publish run-video --video <mp4> --title <标题> --draft
```

## 独立使用（只下载本文件夹）

```bash
cd auto-publisher/autopub
pip install -r requirements.txt
playwright install chromium
python webapp/app.py          # 网页控制台填模型 key(最省事)
python publish_all.py --draft # 草稿试发
```

## 安全红线

1. 发布命令先 `--draft` 验证，人工确认后才真发
2. **不手编 `autopub/state.json`**——已点发布未确认(uncertain)的条目禁止自动重试，须人工到平台后台核实
3. Chrome 调试模式（9222）接管的是日常浏览器：发布期间勿手动操作该浏览器
4. B站/抖音上传框是多文件累加队列——绝不重复 set_input_files（适配器已有防重逻辑）
5. `adapters-kit/` 源自脱敏学习包，见 [adapters-kit/NOTICE.md](adapters-kit/NOTICE.md)，仅限授权学习使用
