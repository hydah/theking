---
name: theking
description: theking：项目知识库 + spec-driven 长程任务工作流。初始化后生成项目级 skill（workflow-governance、knowledge-base），日常开发由项目级 skill 接管。触发词包括 spec-driven、sprint、task、review loop、长程任务、任务拆解、TDD workflow、agent collaboration、SDD、评审闭环、持续 review、项目知识库、知识沉淀、分析文档。
---

# theking

theking 是**安装器**：首次使用时初始化项目的 `.theking/` 知识库和治理体系。初始化完成后，日常开发由两个项目级 skill 接管：

- **workflow-governance** — 开发工作流治理（状态机、硬规则、分流决策、review loop、agent 触发）
- **knowledge-base** — 项目知识沉淀（写入位置、生命周期、PLACEHOLDER 检测与自动填充）

## Bootstrap（唯一职责）

先安装 `workflowctl`。推荐使用独立工具环境，不要依赖系统自带的旧版 `pip`：

```bash
pipx install /path/to/theking
# 或
uv tool install /path/to/theking
```

**必须先运行以下命令**确保项目已初始化。此命令幂等，重复运行不会覆盖已有文件：

```bash
workflowctl ensure --project-dir . --project-slug <PROJECT_SLUG>
```

其中：
- `workflowctl` 是已安装到 PATH 的 theking CLI 命令
- `--project-dir .` 表示你在项目根目录执行命令
- `<PROJECT_SLUG>` 是项目名的 kebab-case 形式

兼容性说明：推荐长期只记住“在项目根目录运行时传 `--project-dir .`”。`--project-dir` 要求项目目录名和 `--project-slug` 精确一致；如果你的目录名和 slug 不一致，继续使用 `--root <项目父目录> --project-slug <slug>`。如果你手上只有 `.theking` 路径，传 `--project-dir .theking` 即可。

例如，对于 `/home/user/code/my-app` 项目：
```bash
cd /home/user/code/my-app
workflowctl ensure --project-dir . --project-slug my-app
```

此命令会：
1. 创建 `.theking/` 目录结构（context、memory、agents、commands、skills、hooks、prompts、verification、workflows）
2. 在 `.theking/agents|commands|skills|hooks|prompts` 下生成共享 authored 资产
3. 生成 `.claude/agents|commands|skills/` 与 `.codebuddy/agents|commands|skills/` 暴露层（优先软链到 `.theking/` 下对应目录，失败回退为复制）
4. 生成 `.github/skills/` 和 `.github/prompts/` 导出层
5. 生成 `.claude/settings.json` 和 `.codebuddy/settings.json`（包含 PreToolUse/PostToolUse hooks）
6. 生成 `CLAUDE.md` / `CODEBUDDY.md` / `AGENTS.md` 入口文件
7. 生成 `project.md`（如果不存在）

## Post-Bootstrap

初始化完成后，检查 `.theking/context/` 下的文件是否包含 `<!-- PLACEHOLDER -->` 标记。如果有，按 knowledge-base skill 的分析流程主动填充。

之后的所有开发工作流和知识沉淀操作，由项目级 skill 接管，不再需要本 skill。

## 初始化产物

```text
<project>/
├── .theking/
│   ├── README.md
│   ├── bootstrap.md          ← 多工具共享入口
│   ├── context/              ← 稳定项目知识
│   ├── memory/               ← 临时补充记忆
│   ├── agents/               ← 10 个 agent 定义（canonical authored source）
│   ├── commands/             ← 共享命令定义
│   ├── skills/               ← 项目级 skill（canonical authored source）
│   │   ├── workflow-governance/SKILL.md
│   │   └── knowledge-base/SKILL.md
│   ├── hooks/                ← hook 脚本 authored source
│   ├── prompts/              ← GitHub Copilot prompt authored source
│   ├── verification/         ← 验证画像
│   ├── runs/                 ← 临时运行产物
│   └── workflows/<slug>/    ← project / sprint / task 工件
├── CLAUDE.md                 ← Claude Code 入口 → .theking/bootstrap.md
├── CODEBUDDY.md              ← CodeBuddy 入口 → .theking/bootstrap.md
├── AGENTS.md                 ← 通用 agent 入口 → .theking/bootstrap.md
├── .claude/
│   ├── agents/               ← runtime 暴露层（优先软链）
│   ├── commands/             ← runtime 暴露层（优先软链）
│   ├── skills/               ← runtime 暴露层（优先软链）
│   └── settings.json
├── .github/
│   ├── prompts/              ← GitHub Copilot 导出层
│   └── skills/               ← GitHub Copilot 导出层
└── .codebuddy/
    ├── agents/               ← runtime 暴露层（优先软链）
    ├── commands/             ← runtime 暴露层（优先软链）
    ├── skills/               ← runtime 暴露层（优先软链）
    └── settings.json
```
