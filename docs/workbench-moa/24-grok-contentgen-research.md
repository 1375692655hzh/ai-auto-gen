# 24-grok-contentgen-research — 阶段二 grok 统一联网调研 + 主控定稿 + 实现验证

> 三家清单汇总后由 grok 独家联网核实(用户指定"不要3个人一起查"), 2026-09-06。
> grok 执行备注: 模块3/4 结论来自 Grok Build 联网核实; 模块1/2 因 Grok 无头模式丢最终答复, 由 grok 岗 agent 经 GitHub API + 接口实测直接核实。原始日志 data/grok-m3.log / data/grok-m4.log。

## grok 调研结论(原文)

### 模块1 快照抓取·行情图
**数据源拍板：东财 push2his 裸接口（采用）+ yfinance（备选）+ akshare（A股备选）**
- 东财 push2his（采用）：实测免 key 直连返回真实日线——`105.NVDA` 与 `1.600519` 均出 OHLCV（secid 前缀：美股105/港股116/A股1或0），一个接口通吃三市场。风险：无官方 SLA、有 IP 风控，须限流+本地缓存。
- yfinance（备选）：25.2k★，Apache-2.0，2026-08-27 活跃，免 key，README 明示"仅限个人用途"ToS。美股覆盖好但 Yahoo 风控史多，作降级通道。
- akshare（备选）：22.4k★，MIT，2026-09-02 活跃，内部封装东财/新浪。A/港股省心但依赖链重，与裸接口二选一即可。
- stooq+pandas-datareader（弃用为主、留兜底）：3.2k★；免费层深度不足，仅作第三兜底。

**渲染拍板：mplfinance（采用）**——4.4k★，BSD，纯 matplotlib 离线出 PNG，Windows py3.11 兼容。注意：最后发布 2023-08、最后提交 2024-08 已停更，但功能成熟，K线场景够用，长远需 fork 自持。echarts SSR（备选）：v5.3+ 官方支持 node 端 SVG/经 node-canvas 出 PNG，美化上限高但引 Node 依赖链。klinecharts / lightweight-charts+playwright 截图（弃用）：浏览器依赖、页面脆弱。

### 模块2 技术分析·支撑阻力
**拍板：自实现 scipy.signal.argrelextrema 局部极值 + 价格带聚类（采用）**——专项库核实全部不达标：arabacibahadir/sup-res 仅 185★、GPL-3.0、2023 停更、偏 crypto；Stock_Support_Resistance_ML 115★、无 license、2021 停更。要"具体价位"而非信号的库没有维护中的，自实现约 30 行、零新增重依赖，是主流做法。
- pandas-ta 原仓库 twopirllc/pandas-ta 已 404，社区续作 xgboosted/pandas-ta-classic 429★、MIT（备选，提供 pivot 类指标但价位仍须自算）。
- bukosabino/ta 5.2k★、stockstats 1.5k★：只出指标不出价位（本用途弃用）。

### 模块3 聚合分析
**FactReach：弃用，名实不符。** 实际为 `simonlin1212/FactReach`：17★、MIT、2026-09-04 提交、仅 5 次提交；README 定位是 Agent 互联网搜索 Skill（23 渠道采集），系 Panniantong/Agent-Reach（78k★）的再发行，**不是**事实核查也不是观点汇总，无检索-验证 prompt、无多智能体编排，对本场景无可借鉴结构。

**投行分析师观点一期通路**：美股=Finnhub 免费 key（/stock/recommendation + /stock/price-target，60 次/分，仅覆盖美股）；A股=东财 reportapi.eastmoney.com 研报列表+评级（免 key，须限流）；港股免费通路不够，一期不承诺。OpenBB（72.7k★）仅在已有供应商 key 时作封装；FinGPT/FinRobot 可参考 bull/bear 辩论结构但不作数据源；共识/分歧汇总层自写 LLM。

### 模块4 X 平台风格与字数规则
**规则核实（2026-09 仍准确）**：免费 280 加权字符、CJK/emoji 计 2（纯中文≈140 字）、URL 恒计 23（t.co）、NFC 规范化（docs.x.com/fundamentals/counting-characters）；Premium/Basic 长文 25000 上限未变（help.x.com/en/using-x/types-of-posts），时间线仍在 ~280 处折叠。

**计数拍板：自实现 v3 加权规则（采用）**——拉丁=1/CJK=2/URL=23/NFC；规则自 2018 冻结，权重出处 twitter-text `config/v3.json`（defaultWeight 200/scale 100）。官方库无 Python 版且实质停更；Python port twitter-text-parser 已 2024-08 归档，仅在需边界完全对齐时一次性 vendoring（备选）。

**财经帖风格清单**：①首行 hook=结论+$代码，折叠前必须能停滑 ②短句换行 ③hashtag 0–1 个（官方建议≤2）④$TICKER 少而准（2026 Smart Cashtags 已带行情卡）⑤thread 优于长文（长文被折叠），每条独立 280、1/n 编号、首帖自洽 ⑥数字+方向先于形容词 ⑦链接放末尾并按 23 字符预留。

## 主控定稿(综合三家 + grok 调研, 不偏离用户规划)

| 项 | 拍板 | 依据 |
|---|---|---|
| 架构 | 端点零外呼 + spawn CLI(`workbench gen-post`) + 轮询 gen-jobs | 三家一致, vstudio 先例 |
| 行情源 | **yfinance 主力 → 东财 push2his 降级**(与 grok 建议主备互换) | grok 云端实测东财通, 但主控本机实测 TLS 被掐(curl/urllib 同现), 以本机为准 |
| 渲染 | mplfinance 离线 PNG(蜡烛+量+支撑阻力线) | 三家一致, 已装 0.12.10b0 |
| 支撑阻力 | 自实现摆动极值+±1.5% 价位带聚类+昨日枢轴(零新依赖, 不用 scipy) | grok 核实专项库全不达标; 补"趋势市上方无摆点"兜底(窗口极值+枢轴R1/R2) |
| 聚合分析 | FactReach 弃用; 大V/机构分组走站内数据池 + 一次 LLM 归并; Finnhub 可选增强(settings.json 配 finnhub.api_key 即启用, 一期仅美股) | grok 核实 FactReach 名实不符 |
| X 计权 | 自实现(拉丁1/CJK2/emoji2/URL23), 前端 JS 镜像实时计数, 后端硬闸+超限 LLM 压缩修复(60s 限时)失败硬截 | grok 核实规则 2026-09 仍准确 |
| 风格 | X 财经帖铁律进 system prompt(hook=结论+$代码/短段/hashtag≤2/链接末尾预留23) | grok 风格清单 |
| LLM | 复用设置页翻译链(vstudio chat_completions), 不另建密钥 | 同视频脚本生成, 零新配置 |
| 复制 | 复制文字(WB.copyText) + 复制图片(ClipboardItem image/png) + 复制图文(双 MIME, 降级提示) | codex/gemini 一致 |

## 实现与验证(2026-09-06)
- 新增 `workbench/server/gcompose.py`(编排+job+产物), `cli.py workbench gen-post`, app.py 四端点(/gen-compose /gen-jobs /gen-posts/{id} /gen-assets/{id}/{file}), drafts 白名单 +gen 字段
- 前端 article.js: 素材池通高加长(mat-pool calc(100vh-320px))、四选择器(平台/语种/账号类型/成稿模板)、加权计数器、开始生成(2s轮询进度)、成稿卡(图/标签/复制)
- 单测: 计权(CJK/emoji/URL) ✓; S/R(NVDA 阻力235×3触/支撑227.4/189.9) ✓; 画图 37KB PNG ✓; 后缀映射 ✓
- CLI 端到端(台积电2330.TW 真素材): 全文锚定→聚合(大V+机构)→LLM成稿 280/280 达标 ✓
- 浏览器端到端: 选择器渲染 ✓ 进度条 ✓ 成稿入编辑器(266/280) ✓ 复制文字→剪贴板实测 ✓
- 事故与修复: 免费池(muse)压缩修复调用滴流挂起 9 分钟 → 修复调用改 60s 超时+失败硬截断保底
- 清场: 测试素材/测试成稿产物已删, gen_jobs 重置, 8788 在跑(新代码已加载)
