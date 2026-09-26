---
name: Bug 报告
about: 某个命令行为不对/报错
labels: bug
about: 某个命令行为不对/报错（Agent 反馈请加 [agent] 前缀）
---

<!-- 提交前请先试一次 `espacenet doctor` 和 `status --json` -->

**环境**
- 操作系统：
- Python 版本：
- espacenet 版本（`--version`）：
- Edge 版本（edge://version）：

**发生了什么**
执行的完整命令（可脱敏检索词，保留语法结构）：
```
espacenet ...
```
期望结果：
实际结果（贴 stderr 完整输出，包含 ✗ [错误码] 行）：
```

```

**频率**：偶发 / 必现。若与限流相关（429/FAIR_USE_REJECTED），请附 `status --json` 中的
`searchBudget` 部分，并说明当时的大致操作节奏。

**附注**：若与数据正确性相关（如命中数与网页不一致），请同时给出在
worldwide.espacenet.com 网页上执行同一检索的截图或命中数。
