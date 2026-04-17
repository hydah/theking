# theking

theking 是一个严格的流程治理型 skill，用于把长程 agent 任务收敛到项目、Sprint、Task、Spec、Review 的固定结构中。它不是再写一份宣言，而是把最小骨架和校验逻辑脚本化，避免 spec-driven development 只停留在口头约束。

## Canonical Source

- 当前项目自身的 canonical KB 在 `.theking/`
- `.theking/agents/`、`.theking/commands/`、`.theking/skills/`、`.theking/hooks/`、`.theking/prompts/` 是生成项目内 AI 协作资产的 canonical source
- 根目录 `README.md`、`SKILL.md`、`scripts/`、`templates/`、`tests/` 继续作为 runtime exposure 与工程入口保留
- `workflowctl` 为目标项目默认生成 `.theking/` 目录，而不是把工件直接散落在项目根

## 目标

- 把 planner -> tdd-guide -> implement -> code-reviewer 的执行顺序固定下来；其中 task.md 的 required_agents 只记录需要调用的 agents
- 强制每个任务拥有 task.md、spec.md 和 review 目录
- 在 ready_to_merge 或 done 前强制存在成对的 review / resolved review 记录
- 用最小 CLI 提供骨架生成，以及对 artifact、状态机和 review 配对的硬校验

## 目录

```text
skills/theking/
├── .theking/
│   ├── context/
│   ├── agents/
│   ├── commands/
│   ├── skills/
│   ├── hooks/
│   ├── prompts/
│   ├── verification/
│   └── workflows/
├── SKILL.md
├── README.md
├── pyproject.toml
├── scripts/
│   ├── constants.py
│   ├── validation.py
│   └── workflowctl.py
├── templates/
│   ├── agents/
│   ├── commands/
│   ├── hooks/
│   ├── scaffold/
│   ├── skills/
│   └── workflow/
└── tests/
    ├── test_init_project.py
    ├── test_init_sprint_plan.py
    ├── test_sprint_check.py
    ├── test_init_task.py
    └── test_check_rules.py
```

## 安装

推荐把 `workflowctl` 当成独立 CLI 安装，不要依赖系统自带的旧版 `pip` 或旧版 Python。

```bash
pipx install /path/to/theking
# 或
uv tool install /path/to/theking
```

如果你只是想一次性试跑，不想先安装到 PATH：

```bash
uv tool run --from /path/to/theking workflowctl --help
```

要求：Python >= 3.10。

## Quickstart

在目标项目根目录执行，优先把 `--project-dir` 传当前项目根目录 `.`：

```bash
cd /tmp/demo-app
workflowctl ensure --project-dir . --project-slug demo-app
workflowctl init-sprint --project-dir . --project-slug demo-app --theme foundation
workflowctl init-task --project-dir . --project-slug demo-app --sprint sprint-001-foundation --slug login-flow --title "Login Flow" --task-type auth --execution-profile backend.http
workflowctl advance-status --task-dir .theking/workflows/demo-app/sprints/sprint-001-foundation/tasks/TASK-001-login-flow --to-status planned
# 编辑 .theking/.../spec.md，补全 Scope / Non-Goals / Acceptance / Test Plan / Edge Cases
workflowctl advance-status --task-dir .theking/workflows/demo-app/sprints/sprint-001-foundation/tasks/TASK-001-login-flow --to-status red
workflowctl advance-status --task-dir .theking/workflows/demo-app/sprints/sprint-001-foundation/tasks/TASK-001-login-flow --to-status green
workflowctl init-review-round --task-dir .theking/workflows/demo-app/sprints/sprint-001-foundation/tasks/TASK-001-login-flow
workflowctl check --task-dir .theking/workflows/demo-app/sprints/sprint-001-foundation/tasks/TASK-001-login-flow
```

兼容性说明：推荐长期只记住“在项目根目录运行时传 `--project-dir .`”。`--project-dir` 要求项目目录名和 `--project-slug` 精确一致；如果你的目录名和 slug 不一致，继续使用 `--root <项目父目录> --project-slug <slug>`。如果你手上只有 `.theking` 路径，传 `--project-dir .theking` 即可。

## 工作流底线

- 先做上下文初勘，再决定完整流程还是轻量流程。至少查看相关代码、测试、文档、报错或接口契约中的直接证据。
- 轻量流程只减少规划开销，不减少交付要求。spec、TDD、build/lint/type/unit、执行画像验证、code review、check/sprint-check 都不能跳过。
- `init-task` 生成的 `spec.md` 是占位稿。任务可以先停在 `draft` 或 `planned`，但进入 `red` 之前必须补全 Scope、Non-Goals、Acceptance、Test Plan、Edge Cases 五段内容。

不要让 AI 输出这种偷懒判断：

```text
👑 [decree] 此旨意走轻量流程。
理由：改动不大，应该只改 1-2 个文件。
```

至少要先输出这种基于证据的初勘，再做分流：

```text
👑 [decree] 上下文初勘：
- 已查看：<代码/测试/文档/报错>
- 影响面：<模块/接口/用户流程>
- 风险标签：<无 / auth / input / api / web.browser / ...>
- 未决问题：<无 / 列表>

👑 [decree] 此旨意走<完整|轻量>流程。
理由：<基于已查看证据的判断>
```

生成到项目里的权威说明见 `.theking/bootstrap.md` 和 `.theking/skills/workflow-governance/SKILL.md`。

## Compact Recovery

如果会话被 compact、切换到新的 AI 工具，或你不确定 decree 现在做到哪一步，先恢复 durable 状态，而不是重新猜：

```bash
workflowctl status --project-dir . --project-slug demo-app
```

如果已经完成分流，但还没创建 sprint / task，把下一步动作写进 decree checkpoint：

```bash
workflowctl checkpoint --project-dir . --project-slug demo-app --phase phase-2-triage --flow full --summary "修复上传鉴权问题" --next-step "基于 planner 输出创建 sprint 与 tasks"
```

恢复顺序是：先看 `status` 输出的 active task / latest unfinished task；只有它们都不存在时，再回退到 decree checkpoint。只有当它明确显示没有恢复目标时，才开启新的 decree。

## 开发这个仓库

仓库开发和测试建议直接用 `uv`：

```bash
uv run workflowctl --help
uv run --with pytest pytest tests -q
```

生成到目标项目中的运行时文档和 prompt 不会写死本机绝对路径；它们统一假设你在项目根目录，通过已安装的 `workflowctl` 命令执行治理操作。

## 当前约束

- 状态机固定为 draft -> planned -> red -> green -> in_review -> changes_requested -> ready_to_merge -> done，外加 blocked
- 默认 required_agents 为 planner、tdd-guide、code-reviewer
- `web.browser` 任务补 e2e-runner
- `backend.http` 任务，以及 auth/input/api 任务补 security-reviewer
- `init-project` 默认生成 `.theking/README.md`、`bootstrap.md`、`context/`、`memory/`、`agents/`、`commands/`、`skills/`、`hooks/`、`prompts/`、`verification/`、`workflows/`、`runs/`
- check 会校验 task_type、execution_profile、verification_profile、requires_security_review、required_agents 是否一致
- `advance-status` 负责非首次进入 review 的状态推进；若目标是 `in_review`，必须使用 `init-review-round`
- `init-review-round` 会把任务推进到 `in_review`，递增 `current_review_round`，并按任务画像脚手架 code/security/e2e review 文件
- ready_to_merge 或 done 前必须存在从 round 001 到 current_review_round 的全部 review pair
- 标记 requires_security_review 或 verification_profile 包含 `web.browser` 时，会额外要求对应 review 成对文件

## 测试

```bash
uv run --with pytest pytest tests -q
```

## 下一步

- 扩展到项目级 dashboard 或 traceability 报告
