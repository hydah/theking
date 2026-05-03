# ADR-001: Spec section count gate — 向后兼容策略

## Context

sprint-002 TASK-001 在 `validate_spec` 里加了"Test Plan ≥ N 条、Edge
Cases ≥ M 条"的硬门槛，触发点是 `advance-status planned → red`（以及
后续任何 `require_content=True` 的路径）。

已有 `is_legacy_spec_structure` 用于识别"只有 Acceptance / Test Plan 两
section"的旧版 spec，并跳过校验。但这次要覆盖的情况是**新版结构（5 个
section 都存在）但条目稀疏**的 spec —— sprint-001 的 6 个 task 就是这种
形态（Test Plan 1–2 条，Edge Cases 空或 1 条）。

相关工件：

- `.theking/workflows/theking/sprints/sprint-002-evolution-ux-round-1/tasks/TASK-001-spec-section-count-gate/spec.md`
- `scripts/validation.py` 新增 `validate_spec_section_counts` /
  `count_spec_section_items` / `normalize_task_flow`
- `.theking/context/evolution-workflow-ux.md` · I-004

## Decision

**硬拦（not opt-in），但给出可操作的错误提示，不加
`--skip-spec-count-check` 逃生阀。**

- 默认阈值在 `scripts/validation.py` 顶层：
  - `SPEC_SECTION_COUNT_THRESHOLDS_FULL = {"Test Plan": 5, "Edge Cases": 3}`
  - `SPEC_SECTION_COUNT_THRESHOLDS_LIGHT = {"Test Plan": 3, "Edge Cases": 1}`
- 流程判定：task.md frontmatter 加可选字段 `flow: full | lightweight`
  （默认 `full`）。**不**读 decree checkpoint 的 flow，因为 checkpoint
  是 session 级状态，会被覆盖；task 级 flow 必须固化在 task 自己的
  frontmatter 里。
- 兼容路径：
  - 已 `done` 的 task（sprint-001）不会被追溯校验，推状态已结束。
  - 新建 task 从此受 gate 约束。
  - legacy spec（`is_legacy_spec_structure` 路径）继续旁路。

## Consequences

### Positive

- 硬拦与 skill "8 条硬规则"体系一致，不引入例外。
- 阈值集中在两个常量里，未来调整 1-2 行变更。
- task 级 flow 字段解耦 decree checkpoint，天然支持「同 sprint 不同 task
  不同流程」，为 evolution-workflow-ux I-003 铺路。
- 错误消息同时命名"提高条目数"与"切换到 lightweight flow"两条出路。

### Negative

- 下游用户升级会被打扰一次：现存 sprint 的 fixtures 或已有 task spec 会
  被新 gate 拦住。**缓解**：错误消息清晰 + CHANGELOG 明确升级提示 + 补足
  条目即可通过。
- sprint-002 自举时 6 个 fixture 文件（5 个测试文件）需同步升级，已落在
  TASK-001 的实施范围内。

## Alternatives Considered

- **`--skip-spec-count-check` opt-in flag**：拒绝。一旦开口，偷懒出口
  会被泛化；与 evolution-workflow-ux I-003 "硬规则不让步" 原则相冲。
- **只加 warning 不 fail**：拒绝。warning 在 AI 工作流里等于无（AI 看过
  就忽略）。
- **阈值从 decree checkpoint 读**：拒绝。checkpoint 是 session 级，
  task 级流程应当自描述，避免跨 session 含义漂移。
- **把阈值写进 task.md frontmatter 作为 override**：作为 followup，
  sprint-002 不做；当前 defaults 已足够。

## Status

Accepted — 落地于 sprint-002 TASK-001。
