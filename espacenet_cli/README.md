# espacenet

`worldwide.espacenet.com`（欧洲专利局 Espacenet）的 AI 可用命令行客户端，按
[CLI-Anything](https://github.com/HKUDS/CLI-Anything) harness 规范构建：
Click 子命令 + 默认 REPL + 每个命令 `--json` + PEP 420 命名空间包。

> **Fair Use / 免责声明**：本工具与 EPO 无关联。它内置检索预算管理（默认 12 次
> 突发、≈8.6 次/分钟回填、限流自动冷却 6-7 分钟），请遵守
> [EPO Fair Use charter](https://www.epo.org)。**大规模/商业化数据需求请使用官方
> [OPS API](https://developers.epo.org)（免费注册）或 [bulk 数据集](https://data.epo.org)**。
> 限流实测与用法详见仓库 `docs/RATELIMIT.md`。

## 硬依赖（真实后端，不降级）

- **Microsoft Edge**：CLI 以专用 profile 启动常驻 Edge 并经 CDP 复用，请求在 Espacenet
  页面上下文内发出以通过 Cloudflare 人机验证（Turnstile 自动点击，必要时人工点一次）。
- **网络可达 worldwide.espacenet.com**，并遵守 EPO Fair Use（默认请求间隔 700ms）。
- Python ≥ 3.10；`pip install -e .` 会装 click / prompt-toolkit / playwright
  （仅用其 CDP 客户端，不需要下载浏览器内核）。

## 安装

```powershell
cd espacenet-cli
pip install -e .
espacenet --help
```

## 首次使用

```powershell
espacenet connect      # 弹出专属 Edge 窗口，自动通过人机验证
```

## 命令一览

| 组 | 命令 |
|----|------|
| 连接 | `connect` `status`（含检索预算/缓存状态） `doctor` `edge start\|status\|stop` `logout --yes` |
| 检索 | `search <检索式> [-p 页] [-s 大小] [--all --limit N] [-f table\|json\|csv\|ndjson] [-o 文件] [--json] [--await-budget]` |
| 单件 | `detail` `claims` `description` `family` `legal` `pdf` `open`（均支持 `--refresh` 跳过本地缓存） |
| 记录 | `session start\|list\|show\|end`（start/end 支持 `--dry-run`） `note <文字> --kind 类型` `report [会话id]` |
| 交互 | 无参数直接进入 REPL；REPL 内另有 `save` / `context` / `help` / `quit` |

## 检索配额（内置，防触发限流）

- 检索走**令牌桶**：12 次突发、约 8.6 次/分钟回填、触发服务端限流自动冻结 6-7 分钟；
  多次命令共享同一份预算（`status` 可查）。
- `claims/description/family/legal/pdf` 的公开号解析有本地缓存（7 天），查同一件专利的
  完整档案只花 1 次甚至 0 次检索；这些命令的文献数据端点实测不限流。
- 批量：`--all` 自动用大页（≥50 条/页）减少请求数；配额不足报 `SEARCH_BUDGET` 并给出
  恢复时间，无人值守加 `--await-budget` 自动排队。

示例：

```powershell
espacenet search 'ti="bicycle" AND pa="shimano"' --json
espacenet search 'pa="shimano"' --all --limit 2000 -f csv -o hits.csv
espacenet detail EP2600908A1
espacenet claims EP2600908 --json
espacenet pdf EP2600908A1 --dir ./pdfs
espacenet                                   # 进入 REPL
```

检索式语法与 Espacenet 高级检索一致：`ti= abs= cl= desc= pa= in= pn= ap= pr= cpc= ipc= pd=`
+ 布尔 `AND/OR/NOT`、通配 `*`、邻近 `NEAR`；无字段代码的纯文本按智能检索处理。

## 检索记录簿

- 全量流水：`./espacenet-journal/auto-log.ndjson`（`--journal-dir` / `ESPACENET_JOURNAL_DIR` 可改）
- 会话：`session start <标题> --goal <目的>` 后，检索/单件/失败尝试自动留档
  到 `sessions/<会话>/`；检索结果数据集落在 `results/`；`report` 编译为体系化
  Markdown 检索报告（含检索调整 diff 与统计）。

## 与旧版共享常驻 Edge

endpoint 文件与 profile 布局和旧 Node.js 版 `espacenet-cli` 完全兼容
（`%LOCALAPPDATA%\EspacenetCLI\profiles\<名称>`），两个 CLI 可复用同一个常驻
Edge 会话与人机验证凭据。

## 测试

```powershell
cd espacenet-cli
python -m pytest espacenet_cli/tests/ -v
# 须真实调用后端的 E2E（连接 Espacenet）：
CLI_ANYTHING_FORCE_INSTALLED=1 python -m pytest espacenet_cli/tests/ -v -s
```
