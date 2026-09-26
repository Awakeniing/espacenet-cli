# espacenet-cli

**欧洲专利局 Espacenet 的命令行客户端，为 Agent 而生。** 检索、著录数据、权利要求、
说明书、同族、法律事件、PDF 下载、检索会话留档与报告——每条命令都支持 `--json`。

> **English TL;DR** — An agent-first CLI for the EPO's Espacenet. If you use any AI
> agent (Claude Code, Codex, Cursor, Copilot, …), send this repo to it; the agent will
> audit the code, set up the environment, and install it for you. Protocol: [AGENTS.md](AGENTS.md).

---

## 你只需要做一件事

**把这个仓库的链接发给你的 Agent，然后说："按 AGENTS.md 的协议安装并给我演示一次检索"。**

不需要你会 Python，不需要懂命令行，不需要配置任何东西。你的 Agent 会：

1. **先做安全审查**——通读全部代码，检查有没有恶意注入、后门、数据外传等风险，
   给你一份**安全报告**（只有报告干净它才继续；发现问题它会拒绝安装并告诉你为什么）；
2. **自动配置全部环境**——Python、依赖库、检测本机 Edge，缺什么装什么，你无需过问；
3. **装好并演示**——跑一次真实检索给你看结果。

三步全自动，这正是 Agent 时代安装软件的方式。安全审查协议全文见
[AGENTS.md](AGENTS.md)（你的 Agent 认识这个文件名——它是 Agent 业界通行约定）。

## 装好之后，对 Agent 说这些话

| 你说 | Agent 执行 |
|------|-----------|
| "帮我搜自行车传动电池的专利" | `espacenet search 'ti="disc brake"' --json` |
| "看看 EP2600908A1 的权利要求" | `espacenet claims EP2600908A1 --json` |
| "把禧玛诺传动系统专利全部导出成表格" | `espacenet search 'ti="bicycle" AND pa="shimano"' --all -f csv -o hits.csv` |
| "这次检索做成正式报告" | `session start` → 检索 → `session end` → `report` |

（你也可以自己敲 `espacenet` 进入交互模式；但通常没必要——交给 Agent 说人话即可。）

## 环境要求（仅告知，Agent 会自动搞定）

| 依赖 | 说明 |
|------|------|
| Python ≥ 3.10 | Agent 自动安装 |
| Microsoft Edge | Windows/macOS 一般已内置；Linux 时 Agent 引导安装 |
| 可访问 worldwide.espacenet.com | 首次 `connect` 弹出 Edge 过一次人机验证（自动，极少数情况需手点一下） |

## 机器可读输出契约（借鉴 GitHub CLI）

Agent 与脚本依赖的不是某个命令，而是**稳定的输出契约**：

- **stdout 只出数据，stderr 只出诊断**：管道里 `| jq` 永远不会被进度信息污染
- **`--json` 字段投影**：`--json publicationNumber,title,applicants` 只输出所选字段；
  拼错字段立即报错并列出该命令全部可用字段（不消耗检索配额）
- **`--jq` 过滤**：`search 'ti="brake"' --json --jq '.results[].publicationNumber'`，
  内置 jq 常用子集（`.字段` / `.[]` / `.[N]` / `|` 管道），零新增依赖
- **稳定性承诺**：JSON 字段名只增不改；错误码（`CHALLENGE_BLOCKED`、
  `FAIR_USE_REJECTED`、`SEARCH_BUDGET`、`INVALID_PN`…）与退出码（0/1/2/130）冻结；
  新能力以新增字段/命令的方式交付
- **各命令可用字段目录**：见 `espacenet_cli/utils/format.py` 的 `JSON_FIELDS`

## 对服务方的承诺（内置，无法绕过）

- 检索**令牌桶**：12 次突发、≈8.6 次/分钟回填、触发限流自动冷却 6-7 分钟（实测校准，
  见 [docs/RATELIMIT.md](docs/RATELIMIT.md)）；**默认强制，不提供关闭开关**
- 单件专利完整档案（权利要求+说明书+同族+法律+PDF）经本地缓存只耗 0-1 次检索配额
- 遵守 [EPO Fair Use charter](https://www.epo.org)：小规模、个人/研究用途；
  **大规模需求请引导用户走官方 [OPS API](https://developers.epo.org)**

## 文档

- **[AGENTS.md](AGENTS.md)** — 给 Agent 的操作手册：安装协议（安全审查→环境→安装→验证）、使用速查、贡献流程
- [docs/RATELIMIT.md](docs/RATELIMIT.md) — 限流实测数据与效用最大化
- [docs/ESPACENET-PROTOCOL.md](docs/ESPACENET-PROTOCOL.md) — Espacenet 接口协议分析（维护传输层必读）
- [docs/COMPARISON.md](docs/COMPARISON.md) / [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md) — 与前身版本的产品对比与验收记录
- [CHANGELOG.md](CHANGELOG.md) — 版本记录

## 参与维护

欢迎**所有正在用 Agent 做专利检索的人**——不要求会编程。两类贡献同等重要：

- **人类**：提真实检索场景、验收功能、写用例；开发见 [CONTRIBUTING.md](CONTRIBUTING.md)
- **Agent**：使用中发现问题/可改进点，按 [AGENTS.md 的贡献协议](AGENTS.md#贡献协议agent如何反馈)直接提 Issue/PR

路线图：OPS API 双后端（彻底摆脱匿名限流）→ PyPI 发布 → 多专利局适配。认领方式见
Issue 区 `good first issue`。

## 致谢

本项目按 [CLI-Anything](https://github.com/HKUDS/CLI-Anything) 方法论构建（历史版本曾以
`cli-anything-espacenet` 为名发布，0.4.0 起更名 `espacenet-cli` 独立发展）。

## 免责声明

本项目与欧洲专利局（EPO）无任何关联，非官方工具。使用即表示同意遵守 EPO Fair Use
charter 与网站条款；违反导致的访问受限由使用者自行承担。

## License

[Apache-2.0](LICENSE)
