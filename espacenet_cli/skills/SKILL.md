---
name: "espacenet-cli"
description: "Espacenet（欧洲专利局 worldwide.espacenet.com）专利检索 CLI：CQL/智能检索、著录数据、权利要求、说明书、同族、法律事件、PDF 下载、检索会话留档与报告，全部命令支持 --json。适用于 AI Agent 的专利检索自动化。"
---

# espacenet-cli

`worldwide.espacenet.com`（欧专局 Espacenet）的 AI 可用命令行客户端，按
[CLI-Anything](https://github.com/HKUDS/CLI-Anything) harness 规范构建：
Click 子命令 + 默认 REPL + 每个命令 `--json` + PEP 420 命名空间包。

## 前置条件（硬依赖，不降级）

- Python ≥ 3.10；`pip install espacenet`（或源码目录 `pip install -e .`）
- **本机安装 Microsoft Edge**：CLI 以专用 profile 启动常驻 Edge，经 CDP 复用；
  请求在 Espacenet 页面上下文内发出以通过 Cloudflare 人机验证（Turnstile 自动点击，
  连续失败时需人工点一次复选框）
- **网络可达 worldwide.espacenet.com**，遵守 EPO Fair Use（默认请求间隔 700ms；
  触发限流自动等待重试，持续 429 时冷却几分钟到几小时）

## 安装与首次连接

```bash
cd espacenet-cli          # 仓库根目录
pip install -e .
espacenet connect     # 启动/复用共享 Edge 并完成人机验证
```

## 命令一览

| 组 | 命令 | 说明 |
|----|------|------|
| 连接 | `connect` `status` `doctor` `edge start\|status\|stop` `logout --yes` | 真实后端（Edge 会话）生命周期 |
| 检索 | `search <检索式>` | CQL 或智能检索文本；`-p 页 -s 大小 --all --limit N -f table\|json\|csv\|ndjson -o 文件 --json` |
| 单件 | `detail <PN>` | 著录数据 + 摘要（检索反查） |
| | `claims <PN>` | 权利要求；EP 自动回退同族英文成员（`textFrom` 标注来源） |
| | `description <PN>` | 说明书全文；同样带 EP 回退 |
| | `family <PN>` | INPADOC 扩展同族成员 |
| | `legal <PN>` | 法律事件 |
| | `pdf <PN> --dir <目录>` | 整册 PDF；无整册时按图像索引回退并说明 |
| | `open <检索式\|PN>` | 在 Edge 中打开页面（人工浏览） |
| 记录 | `session start <标题> --goal <目的>` / `list` / `show` / `end` | 检索会话：开题→自动留档→归档（start/end 支持 `--dry-run`） |
| | `note <文字> --kind 背景\|思路\|调整\|分析\|结论\|备注` | 检索备注（需活跃会话） |
| | `report [会话id] [-o 文件]` | 编译体系化 Markdown 检索报告（含检索调整 diff、统计、复现命令） |
| 交互 | （无参数）`repl` | REPL 内另有 `save <文件>`（保存最近检索结果）、`context`、`help`、`quit` |

公开号写法：`EP2600908A1`、`EP2600908`（kind code 可省略）、`US11234567B2`。

## 检索式语法（qlang=cql，与 Espacenet 高级检索一致）

`ti=` 标题、`abs=` 摘要、`cl=` 权利要求、`desc=` 说明书、`pa=` 申请人、`in=` 发明人、
`pn=` 公开号、`ap=` 申请号、`pr=` 优先权、`cpc=`/`ipc=` 分类号、`pd within "2024"` 公开日；
布尔 `AND/OR/NOT`、通配 `*`、邻近 `NEAR`、引号短语。无字段代码纯文本按智能检索处理。

## 示例

```bash
# 检索（JSON 供 Agent 解析）
espacenet search 'ti="bicycle" AND pa="shimano"' --json

# 全量抓取为 CSV（自动留档）
espacenet search 'cpc=A61K38/00 AND pd within "2024"' --all --limit 2000 -f csv -o hits.csv

# 单件数据
espacenet detail EP2600908A1 --json
espacenet claims EP2600908 --json
espacenet pdf EP2600908A1 --dir ./pdfs

# 检索会话 → 报告
espacenet session start "禧玛诺传动系统检索" --goal "摸清技术布局"
espacenet search 'ti="bicycle" AND pa="shimano"' --all -f csv -o hits.csv
espacenet note "改用英文词命中更全" --kind 调整
espacenet session end
espacenet report -o 报告.md

# 交互 REPL
espacenet
```

## Agent 使用要点

1. **一律加 `--json`**（或 `-f json`）获得可解析输出；结果在 stdout，进度/提示在 stderr
2. **返回码**：0 成功；2 用法错误；1 运行失败（stderr 输出 `✗ [CODE] 消息` + `→ 建议动作`）
3. 检索配额内置令牌桶（12 突发 / 约 8.6 次/分钟回填 / 限流自动冷却 6-7 分钟，`status` 可查）；单件命令带本地解析缓存（7 天），查同一件专利的完整档案只花 0-1 次检索；批量用 `--all --limit 200` 分批，无人值守加 `--await-budget`。常见错误码：`CHALLENGE_BLOCKED`（先 `connect`，人工点一次复选框）、
   `FAIR_USE_REJECTED`（放慢：`--pacing 2000`、减小 `-s`、少用 `--all`）、
   `PDF_UNAVAILABLE`（改用 `open <PN>` 按页查看）、`INVALID_PN`（公开号格式）
4. 大批量抓取先 `session start` 开会话——检索/单件/失败尝试自动留档，
   结束 `report` 直接得到体系化检索报告
5. 进度信息（`[espacenet] …`）在 stderr，管道时不会污染结果

## 检索记录簿位置

默认 `./espacenet-journal/`（`--journal-dir` 或环境变量 `ESPACENET_JOURNAL_DIR` 可改）：
`auto-log.ndjson` 全量流水；`sessions/<会话>/journal.ndjson` 会话事件 + `results/` 数据集；
`reports/` 报告。

## 版本

0.5.0
