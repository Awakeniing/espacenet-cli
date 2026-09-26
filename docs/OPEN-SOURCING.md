# OPEN-SOURCING.md — 开源与合规研究结论

（回答"给人用的网站，工具开源给机器用是否允许"）

## 结论

**可以开源**（建议 Apache-2.0），但必须以"合规内生化"的方式发布：限速默认开启且不
提供无门槛关闭、批量用户引导至官方渠道、声明与本工具的边界。依据如下。

## 1. EPO 的规则是怎么说的

- **[Fair use charter](https://www.epo.org)**（适用 Espacenet 与 OPS）：单个 IP 的阈值是
  **每分钟 10 次检索类动作**；"Automated data retrieval (robots) will be permitted for
  **fair amounts of data** only"（旧版章程原文）；机器人式自动化"不被支持"，超限的
  处置是**技术性限制访问**（限流/封 IP），不是合同违约类追责。
- **[Espacenet 使用条款](https://lp.espacenet.com)**：免费服务条款，重心在公平使用与
  安全要求。
- **官方批量渠道**：[OPS API](https://developers.epo.org)（免费注册、配额制）与
  [EPO bulk data sets](https://data.epo.org)。EPO 对大体的态度是"小量自动化可容忍、
  大批量请走官方接口"。
- 专利文献本身是**公开出版的数据**，EPO 的使命即是传播专利信息；单件 PDF/全文的
  下载与个人研究用途没有额外限制。

## 2. 先例：同类工具早已公开存在

| 项目 | 形态 | 状态 |
|------|------|------|
| [python-epo-ops-client](https://pypi.org/project/python-epo-ops-client/) | 官方 OPS API 客户端 | Apache-2.0，多年公开 |
| [patent-client](https://pypi.org/project/patent-client/) | 聚合 EPO/USPTO/JPO 等的 Python 库 | 开源，面向 AI Agent |
| Apify 商业市场 | Espacenet 检索 actor（网页通道） | 商业化运营 |

没有公开记录显示 EPO 对客户端工具/库有过下架或法律行动；它治理的对象是**滥用流量**
（过频请求），治理手段是限流与封禁。

## 3. 本工具的开源风险清单与对策

| 风险 | 等级 | 对策（已内置于 v0.3.0） |
|------|------|------------------------|
| 用户滥用导致 EPO 收紧匿名通道 | 中 | **检索预算管理器默认强制**（12 突发/8.6 每分回填/自动罚时），批量自动大页减少请求数；不提供无门槛的关闭开关 |
| "绕过反爬"的不当叙事 | 中 | 如实描述：驱动真实浏览器会话、遵守人机验证；文档明确定位为"个人/研究规模的轻量自动化" |
| 大批量用户走网页通道 | 中 | README/SKILL 显著引导：大规模需求请注册 OPS 或用 bulk 数据集 |
| 商标/ affiliation 误解 | 低 | 免责声明：与 EPO 无关联、非官方工具 |
| 协议随网页改版失效 | 低（维护性） | 集中在 `utils/edge_backend.py`，已有测试网兜底 |

## 4. 发布前清单

- [x] Apache-2.0 LICENSE（与上游生态一致）
- [x] README 免责声明 + Fair Use 说明 + OPS 引导
- [x] 限速默认开启；`status` 可查预算；触发限流给出明确恢复时间
- [x] 76 项自动化测试（含真实后端 E2E）+ 真实任务验收记录
- [x] 不含任何凭据/私有数据；Edge profile 与 journal 均在用户本机生成
- [x] 本机产物不入库（`.gitignore` 已覆盖 `acceptance/`、journal、profile、预算/缓存文件）
- [ ] 发布时：初始化 git 仓库并推送 GitHub（README 已含 OPS 引导与免责声明）
