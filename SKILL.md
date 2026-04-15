---
name: theking
description: theking：严格的 spec-driven 长程任务工作流。适用于需要把需求拆成 project、sprint、task、spec、review 层级，并强制执行 planner、tdd-guide、code-reviewer、e2e-runner、security-reviewer 协作的场景。触发词包括 spec-driven、sprint、task、review loop、长程任务、任务拆解、TDD workflow、agent collaboration、SDD、评审闭环、持续 review。
---

# theking

theking 把长程交付压成可执行的固定流程，而不是靠记忆维持纪律。这里要区分两层：skill 负责要求 agent 协作顺序，workflowctl 负责校验 artifact、状态机和 review 约束。

当前项目自身的 canonical KB 位于 `.theking/`，而根目录 `SKILL.md` 是运行时入口。

## 何时使用

- 任务会持续数小时到数天，不能只靠对话上下文维持
- 需要把需求拆成 project、sprint、task、spec、review 多层级
- 需要强制执行 red -> green -> refactor -> review 的节奏
- 需要把 review -> feedback -> modify -> review 变成显式工件

## 不可跳过的硬规则

1. 先规划，再写代码。复杂任务先启动 planner。
2. 先红后绿。实现前先启动 tdd-guide，必要时补 e2e-runner。
3. 每次代码改动都要进入 code-reviewer。触及 auth、input、api 的任务，以及 `backend.http` 画像任务，额外进入 security-reviewer。
4. 没有 spec.md，不进入实现。
5. 没有 resolved review，不进入 done。

## Artifact 合同

每个任务最少有这些文件：

```text
<root>/<project-slug>/
└── .theking/
    ├── context/
    ├── memory/
    ├── verification/
    └── workflows/
        └── <project-slug>/
            ├── project.md
            └── sprints/
                └── sprint-001-<theme>/
                    └── tasks/
                        └── TASK-001-<slug>/
                            ├── task.md
                            ├── spec.md
                            ├── review/
                            └── verification/
                                └── <profile-dir>/
```

task.md 最少包含：

- id
- title
- status
- status_history
- task_type
- execution_profile
- verification_profile
- requires_security_review
- required_agents
- current_review_round

## 操作顺序

### 1. 初始化项目骨架

```bash
python3 scripts/workflowctl.py init-project --root <workflow-root> --project-slug <project-slug>
```

这一步会默认在目标项目根下创建 `.theking/` scaffold。

### 2. 初始化 Sprint

```bash
python3 scripts/workflowctl.py init-sprint --root <workflow-root> --project-slug <project-slug> --theme <theme>
```

### 3. 初始化 Task

```bash
python3 scripts/workflowctl.py init-task --root <workflow-root> --project-slug <project-slug> --sprint <sprint-name> --slug <task-slug> --title <title> --task-type <task-type> --execution-profile <execution-profile>
```

### 4. 执行任务

- 读取 task.md 和 spec.md
- 按 required_agents 顺序推进
- 每次状态变化都更新 status 和 status_history
- 当状态切到 `in_review` 时，把 `current_review_round` 更新到对应轮次

### 5. 校验任务

```bash
python3 scripts/workflowctl.py check --task-dir <task-dir>
```

校验至少会拦住这些问题：

- task.md、spec.md、review 缺失
- verification 缺失或与 execution_profile 不一致
- spec.md 缺少 Acceptance 或 Test Plan
- task_type、execution_profile、verification_profile、requires_security_review、required_agents 不一致
- 状态跳跃，例如 planned 直接 done
- blocked 被当作状态机快捷通道
- ready_to_merge 或 done 前缺少从 round 001 到 current_review_round 的 review 配对文件
- requires_security_review 或 verification_profile 包含 web.browser 但缺少对应 review 配对文件

## Review Loop 约定

- reviewer 产出 review/code-review-round-001.md
- 修改者产出 review/code-review-round-001.resolved.md
- 如果继续下一轮，先进入 `in_review`，并把 `current_review_round` 更新为新轮次
- changes_requested 之后不能直接 done，必须回到 red 或 in_review

## 当前边界

- 当前 CLI 只做 init-project、init-sprint、init-task、check
- review round 文件目前按固定命名校验，尚未自动生成
- 当前 focus 是把 `.theking` scaffold、workflow 骨架和验证约束做实，不直接自动调度 subagent，也不负责 dashboard 和自动汇总