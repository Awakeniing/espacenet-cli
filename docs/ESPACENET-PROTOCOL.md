# Espacenet 接口协议笔记 —— 维护传输层前必读

目标软件：**Espacenet**（https://worldwide.espacenet.com ，欧洲专利局 EPO 专利检索系统）。
它是 Web 应用而非桌面 GUI，但其"后端引擎"同样是真实软件服务——本项目的设计第一原则是
**调用真实后端，禁止玩具重实现**。这里的"真实软件"= 本机 Microsoft Edge 常驻会话 +
Espacenet 前端同款 REST 服务。

## Phase 1 代码库/目标分析

### 1.1 后端引擎

| 层 | 组件 | 作用 |
|----|------|------|
| 边缘层 | Cloudflare（Turnstile 人机验证 + cf_clearance） | 拦截无浏览器指纹的自动化请求 |
| 前端 | Espacenet SPA（NES 客户端） | 人机界面；同源页面内 fetch 自动携带有效凭据 |
| 服务层 | `/3.2/rest-services/*` | 检索、全文、同族、法律事件、文献图像 |
| 限制 | EPO Fair Use 政策 | 限速；`<error>` XML 响应表示被拒 |

匿名可用的服务端点（从 Espacenet SPA `main.app.js` 还原，公开号斜杠格式 `cc/num/kc`）：

- 检索：`POST /3.2/rest-services/search?lang=en,de,fr&q=<CQL>&qlang=cql`，body
  `{query:{fields:[...],from,size}, filters:{"publications.patent":[{value:["true"]}]}, widgets:{}}`
- 著录数据：无独立端点，用 `PN=<公开号>` 检索反查（searchRaw）
- 权利要求：`GET /3.2/rest-services/claims-tree/family/{fam}/publication/{cc}/{num}/{kc}?locale=en`
  → `claimsMap`；EP 文献后端不支持，需回退
- 全文高亮：`GET /3.2/rest-services/highlight/family/{fam}/publication/{cc}/{num}/{kc}?fields=publications.desc_en|claims_en&q=the`
  → multipart 文本；Accept 须为 `*/*`
- 同族：`GET /3.2/rest-services/family/publication/{cc}/{num}/{kc}.json?buildLinks` → OPS 风格 XML→JSON（`world-patent-data.patent-family`）
- 法律事件：`GET /3.2/rest-services/legal/publication/{cc}/{num}/{kc}.json` → `world-patent-data.patent-document.legal-events`
- 文献图像索引：`GET /3.2/rest-services/images/indexes/pub-ids/entries/{cc}/{num}`（可用 kind code）
- 整册 PDF：`GET /3.2/rest-services/images/documents/{cc}/{num}/{kc}/formats/pdf`

必备请求头：`epo-trace-id`（缺会被拒）、`x-epo-client: NES`、`x-epo-pql-profile: cpci`、
`accept: application/json,application/i18n+xml`。

已知服务限制：
- `claims`/`description` 的匿名全文接口对 **EP** 文献不可用（EPO 后端 OPS 需鉴权）→ 回退同族英文
  成员（优先 WO/US），并在结果中标注 `textFrom`
- 部分文献无整册 PDF → 按图像索引回退（如 A0 首页）

### 1.2 "GUI 动作 → API 调用"映射

| Espacenet 界面动作 | REST 调用 | CLI 命令 |
|--------------------|-----------|----------|
| 智能检索/高级检索 | `POST /3.2/rest-services/search` | `search` |
| 结果列表分页 | 同上（`from`/`size`） | `search -p -s`、`search --all` |
| 点开单件（biblio 标签页） | search 反查 `PN=` | `detail` |
| Claims 标签页 | claims-tree → highlight 回退 | `claims` |
| Description 标签页 | highlight `desc_en` | `description` |
| Family 标签页（INPADOC） | family/publication | `family` |
| Legal events 标签页 | legal/publication | `legal` |
| Original document/PDF 下载 | images/documents + indexes | `pdf` |
| 浏览器打开页面人工浏览 | — | `open` |

### 1.3 数据模型

- 检索响应：`hits[]` 为**同族**，`hit.hits[]` 为族内公开文献；`familiesNumber`/`publicationsNumber`
  为命中计数；字段以 `publications.*` 命名（ti_en/abs_en/pn_docdb/pd/pa_patents/in_patents/ipc_icai/ci_cpci…）
- 归一化结果行：publicationNumber/countryCode/kindCode/title/abstract/publicationDate/filingDate/
  applicants/inventors/ipc/cpc/priority/familyId/familySize
- family/legal 响应为 OPS 风格 JSON（`world-patent-data`，publication-reference 兼容数组/对象两形）
- highlight 响应为 multipart 文本（`key: publications.*` 部件 + 内嵌 XML 片段，需清洗）
- 公开号：`cc(2字母) + num + kind(字母+数字可选)`，如 `EP2600908A1`、`EP2600908`

### 1.4 已有 CLI 工具（先例）

本项目的前身 `espacenet-cli`（Node.js 20 + playwright-core，自定义参数解析，未开源）。
它验证了传输通道（Edge CDP 附加 + 页面内事件桥 fetch + 拟人点击过 Turnstile + 限速/Fair-Use
重试），本 harness 将其作为传输层先例移植为 Python 后端模块，但整体架构按 CLI-Anything 规范重建。

### 1.5 通道的硬约束（决定了后端形态）

1. Cloudflare 拒绝无浏览器指纹的纯 HTTP 客户端 → 必须驱动真实 Edge（硬依赖，如同 Blender之于 bpy）
2. CDP 直发请求会被拦 → 请求必须在**页面上下文**内经事件桥 `fetch` 发出
3. 会话中途令牌失效（403 + text/html）→ 清 cf cookie、强制重验、重试一次
4. Fair Use 限流（403 + `<error>` XML）→ 等 5s 重试一次；默认请求间隔 700ms

## Phase 2 CLI 架构设计

### 2.1 交互模型

**双模式**：子命令 CLI（脚本/管道）+ REPL（交互探索，默认入口，
`invoke_without_command=True`）。REPL 使用统一 ReplSkin（横幅/提示符/表格/消息/退出）。

### 2.2 命令组

| 组 | 命令 | 说明 |
|----|------|------|
| 连接管理 | `connect` `status` `doctor` `edge start\|status\|stop` `logout` | 真实后端（Edge 会话）生命周期 |
| 检索 | `search <检索式>` | CQL/智能检索；`-p -s --all --limit -f -o` |
| 单件数据 | `detail` `claims` `description` `family` `legal` `pdf` `open` | 每个界面对应一个命令 |
| 检索记录 | `session start\|list\|show\|end` `note` `report` | 爱迪生式记录簿：自动留痕→编译报告 |
| 交互 | `repl`（默认） | ReplSkin 交互界面 |
| 状态 | `context`（REPL 内） | 最近检索结果驻留内存，可 `save`/导出 |

### 2.3 状态模型

- **浏览器会话状态**：常驻 Edge 进程 + `%LOCALAPPDATA%\EspacenetCLI\profiles\<name>\edge-endpoint.json`
  （与旧版完全兼容，两者可共享同一常驻 Edge）；启动并发用锁文件防竞态
- **检索记录状态**：`./espacenet-journal/`（`--journal-dir`/`ESPACENET_JOURNAL_DIR` 可改）：
  `auto-log.ndjson` 全量流水、`.active-session` 指针、`sessions/<id>/{session.json,journal.ndjson,results/}`、
  `reports/`；会话元数据保存使用 `_locked_save_json`（文件锁保护的原子写）
- **REPL 内存态**：最近一次检索结果（可另存）
- 一次性变更命令（note/session start/end）**自动落盘**，配 `--dry-run` 预览不写入

### 2.4 输出格式

- 每个命令支持 `--json`（机器可读）；检索类另支持 `-f table|json|csv|ndjson` 与 `-o <file>`
- 进度/提示走 stderr，结果走 stdout，可直接管道
- 错误：结构化 `CliError(code, message, action)`，exit code 语义化（用法错误=2）

### 2.5 依赖

`click>=8`、`prompt-toolkit>=3`、`playwright>=1.40`（仅用其 CDP 客户端，不需下载浏览器）、
`pytest`（测试）。**硬依赖**：本机 Microsoft Edge + worldwide.espacenet.com 网络可达（缺失时
报错并给安装/排查指引，不降级为纯 HTTP 猜测通道）。

### 2.6 与旧版（Node.js espacenet-cli）的有意差异

要点：数据产出与旧版一致（同一套传输协议）；稳定性（429 退避、预算罚时）与
Agent 可用性（结构化错误、每命令 --json）更强。
