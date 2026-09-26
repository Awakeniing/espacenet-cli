# 安全策略

## 报告漏洞

请**不要**通过公开 Issue 报告安全漏洞。联系方式（按优先级）：

1. GitHub 私有安全通告（Security → Advisories → New draft security advisory）
2. 维护者邮箱（发布时填写）

我们会在 7 天内确认、30 天内给出修复或缓解方案。

## 范围说明

- 本工具在**用户本机**驱动 Edge 并访问 Espacenet；它不运行任何服务端，不上传数据。
- 属于漏洞范畴：凭据/本机数据泄露（如 profile、journal、缓存的越权读写）、命令注入、
  依赖供应链问题。
- **不属于**漏洞范畴（请到 Issue/Discussion 讨论）：Espacenet 限流策略变化导致的
  可用性问题、Edge 更新导致的会话失效。

## 对服务方（EPO/Cloudflare）的承诺

本项目默认强制检索预算与 Fair Use 合规（见 docs/RATELIMIT.md）。任何试图规避限流、
绕过人机验证于大规模自动化、或分布式压测的 PR/Issue 都会被拒绝并删除。
