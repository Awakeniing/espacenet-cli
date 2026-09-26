# 参与贡献 / Contributing

欢迎！这个项目服务的是"需要专利检索的人"——无论你写不写代码，都有重要的贡献方式。
中文为主，英文亦可。

## 你可以做什么（按稀缺度排序）

> **Agent 贡献者**：如果你是 AI Agent 正在替用户工作，你的反馈/PR 流程在
> [AGENTS.md 的贡献协议](AGENTS.md#贡献协议agent如何反馈)——简言之：Issue/PR 加 `[agent]`
> 前缀并声明生成与测试情况；合并由人类维护者终审。以下人类流程同样欢迎你转述给用户。

1. **检索师视角的需求与验收**（不要求会编程）：提出真实检索场景、试用新命令、
   对报告格式提意见、写用例文档。专利检索的经验是这个项目最稀缺的资源。
2. **文档**：修正过时描述、补英文翻译、写教程/案例。
3. **测试**：扩充 E2E 场景、在非 Windows 平台验证（Edge on Linux/macOS 分支已写，
   未经实机验证）。
4. **代码**：Bug 修复、新命令、OPS API 双后端、PyPI 发布流水线。

## 开发环境

```bash
git clone https://github.com/<owner>/espacenet-cli.git
cd espacenet-cli
pip install -e .
pip install pytest

# 跑测试（CI 同款：纯合成数据，无需 Edge/网络）
python -m pytest espacenet_cli/tests/test_core.py espacenet_cli/tests/test_budget.py -v

# 真实后端 E2E（需要本机 Edge + Espacenet 可达，且会消耗真实检索配额——慎跑）
python -m pytest espacenet_cli/tests/ -v -s
```

## 项目结构

```
espacenet-cli/
├── AGENTS.md                    # 给 AI Agent 的操作手册（安装协议/使用/Agent 贡献）
├── setup.py                     # pip install -e . 的安装入口
├── espacenet_cli/               # 包本体
│   ├── cli.py                   # Click 命令 + REPL（入口 espacenet=espacenet_cli.cli:main）
│   ├── core/                    # config/text/search/document/pdf/journal/budget/session
│   ├── utils/edge_backend.py    # 真实后端：Edge 常驻会话 + 页面内 fetch + 限流处理
│   ├── utils/repl_skin.py       # REPL 皮肤（vendored 自 CLI-Anything 插件，勿大改）
│   └── tests/                   # test_core / test_budget（纯合成）+ test_full_e2e（真实后端）
└── docs/ESPACENET-PROTOCOL.md   # 协议分析（端点/请求头/Cloudflare 通道）——改传输层前必读
```

改动约定：

- **传输层**改动只动 `utils/edge_backend.py` 与 `ESPACENET.md`，并同步 `docs/RATELIMIT.md`
  的实测参数；
- **预算参数**（容量/回填/罚时）定义在 `core/budget.py` 顶部常量，调整必须有实测依据
  并更新 `docs/RATELIMIT.md` 与 CHANGELOG；
- 新命令一律挂到 `cli.py` 的 Click 组上，必须支持 `--json`，错误走
  `CliError(code, message, action)`；
- 每个功能配单元测试（合成数据，可进 CI）；网络 E2E 测试要意识到它们消耗真实检索配额。

## 提交与评审

- 一个 PR 一件事；描述里写清楚"怎么复现/怎么验收"；
- CI 必须绿（合成测试矩阵）；涉及网络行为的 PR 需在描述里贴一次真实运行的输出；
- 每次用户可见的变更在 `CHANGELOG.md` 加条目。

## 维护者制度（治理）

目标：让一批真正用这个工具做检索的人长期共同维护。规则刻意保持轻量：

- **角色**：
  - *贡献者*：提交 Issue/PR 的所有人；
  - *协作者（triage）*：有 2 个以上合并 PR、或 5 条以上被采纳的检索师验收意见，由任一
    维护者提名后获得 Issue 分派与标签权限；
  - *维护者*：PR 合并权限。由现有维护者 2/3 同意授予；至少覆盖两个关注方向
    （见下）；
- **关注方向**（每个方向希望 ≥1 位负责人）：① 传输层与协议适配；② 检索业务与报告
  （欢迎纯检索背景）；③ 测试与发布工程；④ 社区与文档；
- **决策**：日常改动 lazy consensus（48 小时无反对即通过）；破坏性变更（预算参数、
  删除命令、依赖变更）需至少两名维护者同意；
- **冲突**：以"检索用户的真实效用 + 对 EPO 服务的长期友好"为最高准则，讨论不成由
  方向负责人投票。

## 行为准则

参见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。摘要：对事不对人，尊重不同经验水平，
维护者有义务对骚扰行为采取行动。

## 安全问题

不要在公开 Issue 里提安全/协议滥用类问题，见 [SECURITY.md](SECURITY.md)。
