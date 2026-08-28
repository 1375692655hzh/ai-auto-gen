# 工作流的改法与分享（生成工具手册）

工作流包 = `flows/builtin/<名>/` 或 `flows/imports/<名>/` 一个自包含目录：

```
morning-paper/
├── workflow.yaml    # 编排(唯一必需): steps 序列 + with 参数 + when 开关 + review 审核点
├── prompts/*.md     # LLM 提示词(可选, 覆盖 flows/prompts/ 同名): rank_user/rank_system/expand/voice
└── templates/image/*.yaml  # 长图版式(可选): 标题/尾注/分类色板
```

## 四级自定义（由易到难）

| 级 | 改什么 | 怎么改 |
|---|---|---|
| **L1 参数** | 条数/开关 | `cli flows run morning-paper --set items=10 --set with_video=true`（当次）；或不改包直接跑 |
| **L2 文风/版式** | 提示词、长图标题/配色/尾注 | `cli flows new my-paper`（复制包）→ 改 `my-paper/prompts/voice.md`、`templates/image/morning-card.yaml` → `cli flows run my-paper` |
| **L3 流程** | 增删步骤、换参数、移审核点 | 编辑包内 `workflow.yaml` 的 steps（`cli flows lint my-paper` 校验） |
| **L4 新能力** | 新步骤类型/新素材形态 | 在 `flows/steps/` 加 `@step("名")` 函数（Python），YAML 里 `uses: 名` 引用 |

## workflow.yaml 四要素（超出这个范围请写 Python 步骤，不要把 YAML 变成脚本语言）

```yaml
steps:
  - id: assemble           # 步骤名(存档文件名, 断点续跑的键)
    uses: assemble_daily   # flows/steps/ 里注册的步骤类型(cli flows lint 可查全部)
    with: {no_voice: false}# 传给步骤的参数; "{params.x}" 引用包级参数
    when: "{params.x}"     # 可选: 布尔开关(仅支持 {params.x} 引用)
    review: true           # 可选: 审核点(产物落盘后暂停等人工确认)
```

## 常用命令

```bash
python cli.py flows list                    # 全部工作流(builtin + imports) + lint 状态
python cli.py flows run morning-paper --auto          # 全自动跑
python cli.py flows run morning-paper                 # 跑到审核点挂起(改产物后重跑续跑)
python cli.py flows status morning-paper              # 看步骤进度/产物路径
python cli.py flows new my-paper --from morning-paper # 复制包开始自定义
python cli.py flows export my-paper -o 分享包.zip     # 导出分享
python cli.py flows import 分享包.zip                 # 同事导入即用(拒绝含代码的包)
python cli.py flows lint my-paper                     # 校验编排引用
```

## 运行产物与断点

- 每步产物：`data/runs/<工作流>/<日期>/<步骤>.json`（存在即跳过=断点续跑，不重复花 LLM 钱）
- 运行状态：`data/runs/<工作流>/<日期>/run.json`（status: done / waiting_review / stopped）
- 审核点在非交互环境（agent/CI）自动挂起（exit 2），人工改完产物**重跑同一命令**即续跑
- `--from 步骤名` 从指定步骤重跑；`--only 步骤名` 只跑某步；`--fresh` 清当日存档重跑

## 分享安全

- 导入的包**只允许** YAML/模板/提示词（纯数据），含 `.py` 的包会被拒绝安装
- 导出永远只打包包目录本身，不含任何密钥/产物/登录态
