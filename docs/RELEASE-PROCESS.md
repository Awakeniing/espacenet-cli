# RELEASE-PROCESS.md — 发布流程与隐私规程

> 本文档定义"内部验证 → 公开发布"的两阶段流程、人机分工（维护者 vs AI Agent），
> 以及隐名维护的隐私规程。首次发布和日常迭代都按此执行。

## 一、总体设计：一个私有主库，验证后公开

```
本地仓库（已匿名化）
   │ ① push（日常都可推）
   ▼
GitHub 私有仓库 espacenet-cli（内部验证库）      ← 只有你能看到
   │ ② 你在 Web UI 逐项验收（清单见下）
   │ ③ 验收通过：Settings → General → Danger Zone
   │      → Change repository visibility → Public   ← 一次性动作
   ▼
GitHub 公开仓库 espacenet-cli                    ← 全世界可见
```

**为什么这样设计**：私有库先承接全部历史，验收清单过一遍后一次性 flip 公开——
不需要维护两个仓库、历史从第一个 commit 起就是干净的（匿名化在首次提交前完成）。
公开后的日常迭代直接在公开库进行（开源项目正常模式）；需要保密的探索期工作留在
**private 分支**（GitHub 分支可设私有可见性范围内操作）或本地，成熟后再合入。

## 二、分工表：你做什么，Agent 做什么

| 环节 | 你（人类维护者） | AI Agent（如 Claude Code/Codex） |
|------|------------------|----------------------------------|
| 代码/文档/测试改动 | 提需求、验收结果、终审合并 | 编写、自测、提交 commit |
| 匿名化检查 | 抽查敏感词 | **每次 commit 前跑全仓敏感词扫描**（清单见第四节） |
| 推送 private | 执行 `git push`（或授权 Agent 执行） | 准备好待推的 commit 与变更摘要 |
| 私有库验收 | 按"验收清单"逐项检查 | 提供验收证据（测试输出、CI 状态链接） |
| flip 公开 | **只有你**（GitHub 页面操作） | 不操作 |
| Issue/PR 处理 | 终审、合并 | 起草回复/修复 PR（标 `[agent]`，见 AGENTS.md） |

**硬规则**：涉及「公开」的动作（flip visibility、公开 release/tag、对外声明）一律由
人类执行，Agent 永远不代替。

## 三、首次发布步骤（当前状态：本地已就绪）

**你做的（一次性，约 10 分钟）：**

1. 安装 git（若未装）：`winget install Git.Git`，重开终端；
2. 配置**匿名** git 身份（全局或本仓库均可，本仓库优先）：

   ```powershell
   cd <仓库本地路径>            # 进入 espacenet-cli 仓库目录
   git config user.name  "你的笔名"          # 不要用真名
   git config user.email "<数字ID>+<用户名>@users.noreply.github.com"
   ```

   noreply 邮箱在 GitHub → Settings → Emails → "Keep my email addresses private"
   处可查（形如 `12345678+yourname@users.noreply.github.com`）。**绝不用真实邮箱提交**；
3. GitHub 上新建仓库：名称 `espacenet-cli`，**Private**，不要勾选任何初始化
   （不建 README/.gitignore/license）；
4. 推送（本地仓库已 init 并 commit 好）：

   ```powershell
   git remote add origin https://github.com/<你的用户名>/espacenet-cli.git
   git branch -M main
   git push -u origin main
   ```

5. **私有库验收清单**（在 GitHub Web UI 逐项确认）：
   - [ ] 仓库文件列表与本地一致，无 `acceptance/`、`espacenet-journal/`、`*.egg-info`（.gitignore 生效）
   - [ ] 点开 README / AGENTS.md / docs/ 渲染正常，链接有效
   - [ ] Actions 页 CI 绿（首次 push 自动触发：Win+Ubuntu × Py3.10/3.12）
   - [ ] 任意文件 blame/history：commit 作者显示笔名 + noreply 邮箱
   - [ ] 全库搜索第四节敏感词清单：零命中（GitHub 仓库页搜索框）
   - [ ] 用你**另一个**浏览器/无痕窗口模拟外人视角：看不到任何个人信息
6. 验收通过 → Danger Zone → 改为 Public；之后在仓库 About 填描述与 topics
   （`patents` `espacenet` `cli` `ai-agents`）。

## 四、隐私规程（每次对外可见的变更前执行）

**Agent 在每次 commit 前跑敏感词扫描**。具体关键词清单由维护者保存在本地
`blocked-words.txt`（**不入库**，.gitignore 已排除），仓库内只记录扫描类别：

| 类别 | 说明 |
|------|------|
| 真实研究方向词 | 维护者实际研究/检索过的技术主题与相关公司名（含中英文变体） |
| 真实检索过的公开号 | 维护者真实研究涉及的具体专利公开号 |
| 个人标识 | 真名、本机用户名、云盘路径、`C:\Users\`、真实邮箱、手机号 |
| 本机环境 | 绝对盘符路径、内网主机名 |

扫描方式：`git grep -i -E "$(paste -sd'|' blocked-words.txt)" HEAD` 命中即阻止提交。

原则：

- 示例一律用**中性公开物**（已验证可用的：US5960411A 亚马逊一键下单、EP2600908A1、
  `ti="bicycle"` 系列检索式）；
- 检索记录簿（`espacenet-journal/`）、验收原始产物（`acceptance/`）永远留在本机，
  .gitignore 已排除——**不要**为了"留证据"把它们提交进仓库；
- Issue/PR/讨论里贴终端输出时，先检查无本地路径（`cd` 提示符、云盘路径）；
- commit message 只写技术内容，不写时间地点等生活信息（时间戳本身会带时区，属可接受粒度）；
- 若 GitHub 账号注册时用了真名昵称，考虑启用可改的 Display Name 或专用小号。

## 五、日常迭代流程（公开之后）

1. Agent 在本地完成改动 + 测试 + 敏感词扫描 → commit；
2. 你 `git push`（或授权 Agent 推）；小改动直接进 main，大改动走分支 + PR（自审+你终审）；
3. 每个用户可见变更在 `CHANGELOG.md` 加条目；版本号语义化（patch/feature/breaking）；
4. 发布 release：打 tag（`git tag v0.x.y && git push --tags`）→ GitHub Releases 写说明，
   **发布动作由你执行**；
5. 外部贡献按 CONTRIBUTING.md / AGENTS.md 的协议处理（含 `[agent]` 前缀 PR 的终审）。
