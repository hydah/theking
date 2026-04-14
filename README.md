# spec-sprint-workflow

一个严格的流程治理型 skill，用于把长程 agent 任务收敛到项目、Sprint、Task、Spec、Review 的固定结构中。它不是再写一份宣言，而是把最小骨架和校验逻辑脚本化，避免 spec-driven development 只停留在口头约束。

## 目标

- 把 planner -> tdd-guide -> implement -> code-reviewer 显式写进 task.md 的 required_agents，并由 skill 执行时遵守
- 强制每个任务拥有 task.md、spec.md 和 review 目录
- 在 ready_to_merge 或 done 前强制存在成对的 review / resolved review 记录
- 用最小 CLI 提供骨架生成，以及对 artifact、状态机和 review 配对的硬校验

## 目录

```text
skills/spec-sprint-workflow/
├── SKILL.md
├── README.md
├── pyproject.toml
├── scripts/
│   └── workflowctl.py
├── templates/
│   ├── project.md.tmpl
│   ├── sprint.md.tmpl
│   ├── task.md.tmpl
│   ├── spec.md.tmpl
│   ├── code_review_round.md.tmpl
│   └── resolved_code_review_round.md.tmpl
└── tests/
    ├── test_init_project.py
    ├── test_init_task.py
    └── test_check_rules.py
```

## 命令

在 skill 目录下执行：

```bash
python3 scripts/workflowctl.py init-project --root /tmp/workflows --project-slug demo-app
python3 scripts/workflowctl.py init-sprint --root /tmp/workflows --project-slug demo-app --theme foundation
python3 scripts/workflowctl.py init-task --root /tmp/workflows --project-slug demo-app --sprint sprint-001-foundation --slug login-flow --title "Login Flow" --task-type auth
python3 scripts/workflowctl.py check --task-dir /tmp/workflows/demo-app/sprints/sprint-001-foundation/tasks/TASK-001-login-flow
```

## 当前约束

- 状态机固定为 draft -> planned -> red -> green -> in_review -> changes_requested -> ready_to_merge -> done，外加 blocked
- 默认 required_agents 为 planner、tdd-guide、code-reviewer
- frontend/e2e 任务补 e2e-runner
- auth/input/api 任务补 security-reviewer
- check 会校验 task_type 与 requires_e2e、requires_security_review、required_agents 是否一致
- ready_to_merge 或 done 前必须存在 code-review-round-001.md 和对应 resolved 文件
- 标记 requires_security_review 或 requires_e2e 时，会额外要求对应 review 成对文件

## 测试

```bash
python3 -m pytest tests -q
```

## 下一步

- 补充 review round 模板生成命令
- 补充状态推进命令，而不是只靠手工改 task.md
- 扩展到项目级 dashboard 或 traceability 报告
