---
name: aag-x-register
description: X(Twitter) 财经账号批量录入数据源池(twitter_pool.yaml)的固化 SOP——2026-09-17/19 录入 61 号四类事故(放错层/拼错号/非法handle/重复)的防复发流程。当用户给一批 X 账号要"录入/进池/收录"时使用。
---

# X 账号录入 SOP（数据源池 twitter_pool.yaml）

规范原文: `global-news-sources/docs/X账号录入规范.md`（登记卡/定位表/防坑清单/账号总表）。
工具: `scripts/xpool_intake.py`（提取/校验/去重/验号/预分类/写池自动化）。
Windows 用 `py -3.11`，仓库根目录运行。退出码: `0` 完成｜`2` 失败清单待用户核实｜`3` 限流熔断/硬失败（重跑幂等续传）。

## 第0步 去向确认（红线，事故1防复发）

用户给清单，先明确问一句"进哪层"，**绝不擅自归类**：

- **数据源池（默认，本 SOP 管的）**：`twitter_pool.yaml`，供早报/图文生成按 role 分流抓取；
- **飞书 1min 监控池**：云端 `config.local.yaml` 的 `watch.handles`，手工配置，本 SOP 不覆盖；
- **账号追踪（x_track）**：工作台图文页【账号追踪】自选清单，工作台内操作。

用户明说或确认默认数据源池后才继续。

## 第1步 存清单跑 intake（dry-run，不写池）

用户原始粘贴**原样**存文件（保真不改写，任何格式：裸 handle/@handle/名字@handle 混排/链接均可）：

```
py -3.11 scripts/xpool_intake.py <清单文件>
```

把报告三张单给用户：**新号（含 uid/显示名/粉丝/预分类草稿）**、**重复跳过（清单内重复/与池重复/uid 撞车）**、**失败清单**。

## 第2步 失败清单交用户核实

- 404 = 注销或拼错（事故2: MichealDell→MichaelDell 就是靠逐号验号暴露的），**不猜修正**；
- 非法 handle 原样退回（事故3: `Jack Kellogg@Jackaroo Trades` 带空格，X 不存在这种号）；
- 帖子链接不替用户解析作者；用户给候选 handle → 更新清单文件重跑实测。

## 第3步 用户确认后写池

```
py -3.11 scripts/xpool_intake.py <清单文件> --apply
```

（uid 撞车自动拒绝录入；写池 = 文本级块尾追加 + 原子写 + 写后 yaml 自查，重复重跑幂等跳过。）

## 第4步 字段回填

```
py -3.11 scripts/backfill_xpool_profile.py --handles <新号csv>
```

（positioning 用纯 bio 口径、tags 用 10 桶词表——均为用户裁决口径，**不擅自改**； followers/bio 一并补齐。）

## 第5步 同步 seed

```
py -3.11 scripts/sync_seeds.py
```

## 第6步 文档登记

`global-news-sources/docs/X账号录入规范.md` 末尾追加批次小节 + 账号总表行（手写，含验号所得 **uid**、粉丝量级、预分类、备注）——参照第九节 2026-09-17 批次的格式。

## 第7步 git 提交推送 + 云端同步

```
git add <池文件/文档/改动文件> && git commit -m "..." && git push
ssh ubuntu@43.135.25.178 'cd ~/ai-auto-gen && git pull --ff-only'
```

## 第8步 验证入库

下一轮 `sources refresh` 后抽查新号条目入库；或直接单号实测：

```
python cli.py sources fetch twitter_kol_views --limit 3 --json
```

单号实测（`fetch_twitter_kol` 无 --handles 参数，用 7 天窗口抓全池后按 handle 过滤）：

```
py -3.11 -c "import sys; sys.path.insert(0,'global-news-sources'); from fetchers.basic import fetch_twitter_kol; rows=fetch_twitter_kol({'hours':168},mode='views'); hits=[r for r in rows if '<新handle>' in str(r).lower()]; print(len(rows),'条 |',len(hits),'命中 |',str(hits[0])[:160] if hits else '')"
```

## 红线（四类事故的防，违者必复盘）

1. **去向未确认不动手**——数据源池/飞书监控池/x_track 三层，绝不擅自归类（事故1）。
2. **uid 撞车拒绝录入**——同 uid 不同 handle = 疑似改名/同人，先人工合并再录。
3. **404/作者不符不猜**——绝不替用户"修正"拼写；候选一律实测验证后由用户确认（事故2）。
4. **非法 handle 原样退回**——X 只允许 1-15 位 `[A-Za-z0-9_]`，带空格的不存在（事故3）。
5. **重复三道闸**——清单内大小写去重 + 池 handle 查重 + 验号后 uid 查重，一道都不少（事故4）。
6. **词表与口径不擅改**——tags 10 桶词表、positioning 纯 bio 口径是用户裁决，改前必须问。
7. **池文件必须文本级写入 + 写后 yaml 自查**——不走整文件重排，写坏即拦截。
