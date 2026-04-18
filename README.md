# theking

theking 是一个严格的流程治理型 skill，用于把长程 agent 任务收敛到项目、Sprint、Task、Spec、Review 的固定结构中。它不是再写一份宣言，而是把最小骨架和校验逻辑脚本化，避免 spec-driven development 只停留在口头约束。

theking 采用「皇帝下旨 · 群臣办事」的朝廷隐喻组织流程：`/decree` 是皇帝发起的旨意，中书令（planner）起草方略，门下侍中（tdd-guide）封驳审核，御史大夫（code-reviewer）独立监察，六部按职责分工。隐喻是为了让人读起来有代入感，而真正的技术锚点（`spec.md` / `TDD red/green` / `build-lint-type-unit` / `review pair` / `check` / `sprint-check`）在文档正文中原样保留，保证 AI 精准识别。

## Canonical Source

- 当前项目自身的 canonical KB 在 `.theking/`
- `.theking/agents/`、`.theking/commands/`、`.theking/skills/`、`.theking/hooks/`、`.theking/prompts/` 是生成项目内 AI 协作资产的 canonical source
- 根目录 `README.md`、`SKILL.md`、`scripts/`、`templates/`、`tests/` 继续作为 runtime exposure 与工程入口保留
- `workflowctl` 为目标项目默认生成 `.theking/` 目录，而不是把工件直接散落在项目根

## 目标

- 把「planner → tdd-guide → implement → code-reviewer」的执行顺序固定下来；task.md 的 required_agents 只记录需要调用的 agents
- 强制每个任务拥有 task.md、spec.md 和 review 目录
- 在 ready_to_merge 或 done 前强制存在成对的 review / resolved review 记录
- 用最小 CLI 提供骨架生成，以及对 artifact、状态机和 review 配对的硬校验
- `/decree` 作为从需求到交付的编排入口，匹配完整/轻量两种流程，支持 compact 后从 checkpoint 续行
- `workflowctl upgrade` 按 manifest 指纹幂等升级项目内 runtime，不盲覆用户修过的文件

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

如果你是直接把这个仓库 clone 到本地，推荐优先使用仓库自带的 home 安装器：

```bash
./install.sh
```

默认行为：

- 安装一个受管理的副本到 `~/.agents/skills/theking`
- 安装 `workflowctl` 到 `~/.local/bin/workflowctl`
- 安装 helper wrapper 到 PATH：`theking-install`（自更新入口）
- 如果检测到你已经有 `~/.claude` 或 `~/.codebuddy`，会询问是否也把 skill 暴露到对应的 `skills/theking` 目录
- **不会**自动修改 `~/.zshrc` / `~/.bashrc`；如果 `~/.local/bin` 不在 PATH 中，脚本会打印提示

常用参数：

```bash
./install.sh --yes
./install.sh --targets agents,claude
./install.sh --bin-dir ~/.local/bin
./install.sh --force
```

如果你更偏好独立工具安装，也仍然可以把 `workflowctl` 当成独立 CLI 安装，不依赖系统自带的旧版 `pip` 或旧版 Python：

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

## 升级已初始化项目

theking 本身升级后（例如模板更新、agent 说明变更、hooks 调整），用 `workflowctl upgrade` 把目标项目里的 runtime 文件同步到新版本。manifest 放在 `.theking/.manifests/runtime.json`，按 sha256 指纹区分“用户改过”和“theking 自己写过的内容”，不会盲目覆盖用户编辑。

```bash
# 先预览：看哪些 runtime 文件会被刷新、哪些出现 drift
workflowctl upgrade --project-dir . --project-slug demo-app --dry-run

# 确认没问题后执行
workflowctl upgrade --project-dir . --project-slug demo-app

# 用户手改过的文件默认会被标为 drift 并原样保留；两种处理方式：
#   --force   覆盖，并把原文件备份到 .theking/.backups/<时间戳>/
#   --adopt   保留用户改动，把当前内容当作新的 baseline 写回 manifest
workflowctl upgrade --project-dir . --project-slug demo-app --force
workflowctl upgrade --project-dir . --project-slug demo-app --adopt
```

管辖范围只包含完全由模板生成的 canonical source（`.theking/agents/*.md`、`.theking/commands/*.md`、`.theking/skills/*/SKILL.md`、`.theking/hooks/*.js`、`.theking/prompts/*.prompt.md`、以及 `.theking/README.md`、`.theking/bootstrap.md`、`.theking/context/architecture.md`、`.theking/context/dev-workflow.md`、`.theking/agents/README.md`、`.theking/agents/catalog.md`、`.theking/verification/README.md`）。

以下文件由用户维护，`upgrade` 不会动：

- `.theking/context/project-overview.md`
- `.theking/memory/MEMORY.md`
- 根目录 `CLAUDE.md`、`CODEBUDDY.md`、`AGENTS.md`（`ensure` 已负责 append 而非覆盖）
- `.kimi/agent.yaml`、`.kimi/agents/*.yaml`（`ensure` 用 `write_if_missing`，用户可以手工定制主 agent 或某个 subagent）

`.claude/`、`.codebuddy/`、`.github/`、`.kimi/skills/` 等投影目录不受 manifest 管辖——它们本来就在每次 `ensure`（也就是 `upgrade` 第一步）里从 canonical source 全量重建。

## 多 runtime 投影（.claude / .codebuddy / .kimi）

Canonical 源 `.theking/agents/*.md` 采用 Claude Code 风格 frontmatter（`tools: Read, Grep, Glob`、`model: opus` 等）。投影规则：

- `.claude/agents/` → **symlink** 到 `.theking/agents/`，内容 1:1 一致。
- `.codebuddy/agents/` → **物化拷贝** 并重写 frontmatter 为 CodeBuddy 方言：移除 `tools`/`model`，改写为 CodeBuddy 默认工具集，并追加 `agentMode: agentic`、`enabled: true`、`enabledAutoRun: true`。正文 body 保持不变。
- `.claude|.codebuddy/commands/`、`.claude|.codebuddy/skills/`、`.github/skills/`、`.github/prompts/` → 继续 symlink，因为这些文件的 frontmatter 在两个 runtime 中兼容。
- `.kimi/skills/` → **symlink** 到 `.theking/skills/`，同一份 SKILL.md 被 Kimi / Claude / CodeBuddy 共享。
- `.kimi/AGENTS.md` → **symlink** 到项目根 `AGENTS.md`，对应 Kimi 的 `${KIMI_AGENTS_MD}` 合并规则。
- `.kimi/agent.yaml` + `.kimi/agents/*.yaml` → **物化生成**：主 agent `extend: default`，每个 subagent `extend: ../agent.yaml` 并把 `system_prompt_path` 指向 `.theking/agents/<role>.md`。Claude frontmatter 的 `tools:` 会按 `CLAUDE_TO_KIMI_TOOL_MAP` 翻译为 Kimi 的 `module:ClassName` 标识。

重写逻辑是幂等的：多次 `ensure`/`upgrade` 不会叠加字段，已存在的 Kimi YAML 不会被覆盖（用户可以手工定制某个 subagent）。要调整 CodeBuddy 的工具集或 Kimi 的工具映射，改 `scripts/scaffold.py` 的 `CODEBUDDY_AGENT_TOOLS`、`scripts/constants.py` 的 `CLAUDE_TO_KIMI_TOOL_MAP` 即可。`mcpTools` 和具体 `model` 值属于用户环境配置，不在投影层注入，请在各 runtime 自己的 settings 中配置。

**Kimi CLI 使用方式：**

```bash
# 启动 Kimi，加载治理 agent + 10 个角色 subagents
kimi --agent-file .kimi/agent.yaml

# 或者直接用默认 agent + skill（不走 subagent 分工）
kimi   # 会自动读 AGENTS.md 和 .kimi/skills/
```

Kimi 当前官方不支持 lifecycle hooks（见 issue #986），因此 `.kimi/` 下没有 settings.json 投影。治理纪律靠 `workflow-governance` skill 文本 + `workflowctl` 命令校验落地，和 Claude/CodeBuddy 的钩子机制相比依赖 agent 自觉程度。

## 工作流底线

- 先做上下文初勘，再决定完整流程还是轻量流程。至少查看相关代码、测试、文档、报错或接口契约中的直接证据。
- 轻量流程只减少规划开销，不减少交付要求。spec、TDD、build/lint/type/unit、执行画像验证、code review、check/sprint-check 都不能跳过。
- `init-task` 生成的 `spec.md` 是占位稿。任务可以先停在 `draft` 或 `planned`，但进入 `red` 之前必须补全 Scope、Non-Goals、Acceptance、Test Plan、Edge Cases 五段内容。
- 进入 `red` 时除了"五段非空"，还要通过条目数门槛：完整流程要求 Test Plan ≥ 5 条、Edge Cases ≥ 3 条；轻量流程要求 ≥ 3 条 / ≥ 1 条。在 task.md frontmatter 加 `flow: lightweight` 启用轻量阈值（默认 `full`）。条目不足时 `advance-status` 会给出明确错误提示，补足即可。

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
- 默认 required_agents 为 planner、tdd-guide、code-reviewer；`web.browser` 任务补 e2e-runner；`backend.http` 任务以及 auth/input/api 任务补 security-reviewer
- 完整朝廷执事表（architect/build-error-resolver/perf-optimizer/doc-updater/refactor-cleaner 等按需召唤）定义于 `.theking/skills/workflow-governance/SKILL.md`，`/decree` 模板与 `agents/` 评语保持一致
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

- Sprint 级全量回归与 `verification/regression.md` 的部分自动化（将 decree Phase 5 的手动步骤翻译成 CLI 子命令）
- 项目级 dashboard / traceability 报表：跨 sprint 查看 task 状态分布、review 轮次、红绿失败热图
- `workflowctl upgrade` 支持反向同步：从任何项目里的成熟模板反哺到 theking 顶流 templates
