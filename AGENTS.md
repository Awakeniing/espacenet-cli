# AGENTS.md — 给 AI Agent 的操作手册

本文件遵循 AGENTS.md 社区约定。任何 AI Agent（ZCode、Claude Code、Codex、Cursor、
Copilot 等）在收到"安装/使用/贡献这个仓库"的指令时，**按本协议执行**。

**你的用户可能完全不懂编程。** 全程说人话汇报进度；技术细节放报告里，不要吓到他们。

---

## 安装协议（强制顺序，不得跳步）

### 第 1 步：安全审查（先于一切安装动作）

用户把陌生代码交给你运行，信任的是你。**先审计，后安装；审计不过，拒绝安装。**

逐项检查并向用户出具安全报告（保存为 `security-report.md` 或直接展示）：

| 检查项 | 方法 | 判定 |
|--------|------|------|
| 代码执行风险 | 全仓搜索 `eval(` `exec(` `__import__`（注意 `re.compile` 是正则编译，属正常）：仅允许测试文件中出现 | eval/exec 出现在产品代码=拒绝 |
| 网络端点 | 全仓搜索 http(s) URL / socket：**仅允许** `worldwide.espacenet.com`、`127.0.0.1`（本机 Edge CDP）、pip 官方源 | 出现其他外传端点=拒绝 |
| 子进程调用 | 检查所有 `subprocess`/`Popen`：仅允许启动本机 `msedge`（显式路径探测）与 `tasklist/taskkill`（进程管理） | 隐式 shell、下载执行=拒绝 |
| 文件写入 | 检查写路径：仅 `%LOCALAPPDATA%\EspacenetCLI`（profile/预算/缓存）、用户指定的输出文件、`./espacenet-journal` | 写系统敏感位置=拒绝 |
| 凭据/外传 | 搜索 telemetry、analytics、上传、加密流量到第三方 | 任何外传=拒绝 |
| 依赖供应链 | `setup.py` 仅 3 个知名依赖（click/prompt-toolkit/playwright），无 post-install 脚本 | 陌生源/安装钩子=拒绝 |
| 混淆 | 检查 base64 大块、十六进制串、动态拼装的代码 | 无法解释的混淆=拒绝 |

**本仓库的预期结论**（供你交叉验证，不要照抄，自己查）：全部 Python 代码约 4000 行
（产品约 3000 行 + 测试约 900 行），
无 eval/exec、无第三方端点、子进程仅启动 Edge、写入仅限上述本地目录。

报告结论二选一：
- ✅ **通过** → 向用户简述"查了什么、没发现问题"，继续第 2 步；
- ❌ **拒绝** → 说明发现的具体文件/行号与风险，**停止安装**，建议用户到仓库提 Issue 核实。

### 第 2 步：环境自检与自动配置

```
python --version          # 需要 ≥ 3.10；缺失则先为用户安装 Python（winget/brew/apt）
pip install -e .          # 在仓库根执行；安装 3 个依赖（click/prompt-toolkit/playwright）
espacenet doctor          # 检查 Edge 可执行文件与 profile；缺 Edge 时引导用户安装
```

### 第 3 步：安装验证（必做，向用户证明可用）

```
espacenet --version                        # 应输出 0.5.0
python -m pytest espacenet_cli/tests/test_core.py espacenet_cli/tests/test_budget.py -q
                                           # 应 67 passed（纯本地合成数据，不联网）
espacenet connect                          # 首次连接：弹出 Edge，自动过人机验证
espacenet search 'ti="bicycle"' -s 3 --json    # 真实检索冒烟
```

connect 弹出的 Edge 窗口若停在人机验证页，请用户手点一次复选框（之后长期免验证）。

### 第 4 步：向用户交付

汇报三件事：安全报告结论、装了什么、演示一次真实检索的结果。

## 使用速查

```
espacenet search '<CQL 检索式>' [--all --limit N] [-f csv|json|ndjson] [-o 文件] [--json]
espacenet search 'ti="brake"' --json publicationNumber,title,applicants   # 只取所选字段（拼错即报错并列出可用字段，不耗配额）
espacenet search 'ti="brake"' --json --jq '.results[].publicationNumber'  # jq 子集：.字段 / .[] / .[N] / | 管道
espacenet detail|claims|description|family|legal|pdf <公开号> [--refresh]
espacenet session start "标题" --goal "目的" → …检索… → session end → espacenet report
espacenet status --json      # 含检索预算余量
```

行为契约（对你）：
- 一律 `--json` 拿结构化输出；错误是 `✗ [CODE] 消息` + `→ 建议`，按建议自纠
- **配额语义**：检索 12 次突发/约 8.6 次每分钟回填；`SEARCH_BUDGET` = 本地预算拦停（等它
  说的时间，别硬重试）；`FAIR_USE_REJECTED` = 服务端限流（冷却 6-7 分钟，期间文献类命令不受影响）
- 批量：`--all --limit 200` 分批；无人值守加 `--await-budget` 自动排队
- 大规模数据需求（>几千条/商业用途）：**不要硬抓**，告知用户申请 EPO OPS API（免费注册）

## 开发与测试（改代码时）

```
pip install -e . && pip install pytest
python -m pytest espacenet_cli/tests/test_core.py espacenet_cli/tests/test_budget.py -q  # 本地合成，进 CI
python -m pytest espacenet_cli/tests/ -v -s    # 含真实后端 E2E：需本机 Edge + 消耗真实检索配额，慎跑
```

布局：`espacenet_cli/cli.py`（命令+REPL）· `core/`（search/document/pdf/journal/budget）
· `utils/edge_backend.py`（传输层，改前读 docs/ESPACENET-PROTOCOL.md）· `tests/`。
约定：新命令必须 `--json` + `CliError(code, msg, action)`；预算参数在 `core/budget.py`
顶部常量，改动需实测依据并更新 docs/RATELIMIT.md 与 CHANGELOG。

## 贡献协议（Agent 如何反馈）

你在使用中发现的一切可改进点——命令报错语义不清、某类检索式解析不对、文档与行为
不符、想到了新命令——都欢迎反馈，**无需等人类用户发起**：

1. **Issue（轻量反馈）**：用 Bug/Feature 模板；标题加前缀 `[agent]`；正文注明
   「由 <Agent 名/型号> 在执行 <什么任务> 时发现」+ 完整命令与输出。你会得到与人类
   Issue 完全相同的处理。
2. **PR（代码贡献）**：可以提，但有三条硬规则——
   - 标题加 `[agent]`，PR 描述**首段声明**：改动由 Agent 生成、已跑过哪些测试、
     涉及网络行为的改动附真实运行输出；
   - 不改预算参数/不加依赖/不动传输层端点（这三类改动只接受人类维护者实测后合并）；
   - 合并仍需人类维护者按 CONTRIBUTING.md 评审——**Agent 提 PR，人类终审**，责任
     边界清晰。
3. **安全相关**：按 SECURITY.md 走私下渠道，不发公开 Issue。
