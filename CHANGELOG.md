# CHANGELOG — espacenet-cli

## 0.5.0 — gh 式机器可读输出（字段投影 + jq 子集）

借鉴 GitHub CLI 的 Exporter 模式，把"给 Agent 消费"做到管道级：

- **`--json` 字段投影**：`--json` 裸用行为不变（完整 JSON）；`--json publicationNumber,title`
  只输出所选字段——列表命令（search/family/session list）投影为行数组，对象命令
  （detail/claims/description/legal/pdf/session show）投影顶层键。字段表拼错**在触达
  Edge/检索配额之前**快速失败，报错列出该命令全部可用字段（兼当文档）。字段目录见
  `utils/format.py` 的 `JSON_FIELDS`。
- **`--jq` 过滤器**：内置纯 Python 实现的 jq 常用子集（`.字段` / `.[]` / `.[N]`（含负数
  下标）/ `|` 管道），如 `search ... --json --jq '.results[].publicationNumber'`；
  多结果各占一行，字符串原样输出。**零新增依赖**（遵守 AGENTS.md 贡献纪律）；
  复杂 jq 语法明确报错并提示子集范围。`--jq` 隐含 JSON 输出。
- **输出契约成文**（README「机器可读输出契约」一节）：JSON 字段名只增不改、错误码表
  冻结、退出码语义不变——后端（Edge 页面上下文）越脆弱，前端契约越要稳。
- 测试 60 → 67（+7：字段解析/校验/投影、jq 路径管道下标边界、CLI fail-fast）。

## 0.4.0 — 独立命名与 Agent 优先定位

- **更名**：`cli-anything-espacenet` → **`espacenet-cli`**（命令 `espacenet`，包
  `espacenet_cli`，标准 Python 布局）。定位从"CLI-Anything harness"转为独立的
  Agent 时代 Espacenet 客户端；CLI-Anything 方法论致谢保留于 README。
- **新增 `AGENTS.md`**（Agent 业界通行约定）：安装协议——**安全审查先行**（代码审计
  清单与放行标准，审计不过拒绝安装）→ 环境自检 → 安装验证 → 交付；使用速查与
  行为契约；**Agent 贡献协议**（`[agent]` 前缀 Issue/PR、声明生成与测试情况、
  人类维护者终审、三类改动仅限人类实测）。
- **README 重写为 Agent 优先**：用户主路径 = 把仓库链接发给 Agent；环境要求仅作告知
  （Agent 自动配置）；对服务方的 Fair Use 承诺前置。

## 0.3.0 — 速度平衡版（v3）

- `--all` 批量拉取自动使用大页（≥50 条/页）：同样的结果集请求数减半以上。
  实测：197 条禧玛诺传动系统全量拉取 4 页 8.2 秒完成（v0.1.0 同任务 10 页 25-40 秒），
  检索预算仅消耗约 4 枚。
- 页间隔按实测校准 1.2s。综合效果：**比 v1 更快、且远低于限流线**。

## 0.2.0 — 限流内生化（v2）

依据 RATELIMIT.md 实测把限流规则固化进 CLI：

- **检索预算管理器**（`core/budget.py`）：跨进程持久令牌桶——容量 12（实测突发
  ~20 留余量）、回填 1 枚/7s（≈8.6 次/分 < 官方 10 次/分钟）、罚时 400s（实测恢复
  5 分 18 秒/6 分 03 秒 + 余量）；状态存 profile 目录，所有命令共享。
- **撞墙即记录**：真实 429/403 记入罚时并给出精确恢复时间，替代 v1 的 30s/90s 盲重试
  （实测盲重试只会延长 Cloudflare 处罚）。
- **文献解析缓存**：`claims/description/family/legal/pdf` 共享公开号解析（进程内 +
  持久化 7 天 TTL）。查一件专利的完整档案从 4-5 次检索降为 **0-1 次**；
  `--refresh` 强制刷新。
- `--await-budget`：无人值守任务配额不足时自动排队（默认快速失败并报恢复时间）。
- `status` 显示预算余量/罚时/缓存条目数。

## 0.1.0 — CLI-Anything 流水线首版

Node.js 旧版（`espacenet-cli/`）的 Python 重写：Click + 默认 REPL + 每命令 `--json`、
Edge 常驻会话传输层（Cloudflare 自动验证、Fair Use 处理）、检索会话记录簿与报告、
76 项测试（49 单元 + 11 预算/缓存 + 16 E2E）。
