# ADR-003: Runnable evidence gate — 把"能跑"纳入硬规则

## Context

voiceagent4 这一案例（/decree 全流程走完、`go test ./...` 全绿、`go
vet` 过、单元覆盖率 75–88%）**一跑就 `panic: send on closed channel`**，
主链路的 TTS→WebRTC 音频输出甚至明确标注为"占位实现"，但 task 被推到
`done`、sprint 被 `sealed`。

根因是 skill 里 **Phase 4 步骤 5「亲勘实证」** 与 **Phase 5 步骤 2-3
「Sprint 级全量回归 / 画像验证」** 是"软要求"性质的规则文档，没有和
`workflowctl check` / `sprint-check` 代码联动。具体空洞：

1. `validation.py::has_non_empty_verification_evidence` 只查"文件大
   小 > 0"。smoke.md 里写"待补"也能过。
2. spec.md 的 Acceptance 每一条只有一个 checkbox，没有"验证方式
   / 证据路径"。AI 可以用 unit test 冒充所有 acceptance，然后把
   "真跑一次"的要求移入交付清单的"已知限制"章节糊弄过去。
3. Phase 5 的"sprint 级画像验证必做"是纯文字约束，`sprint-check`
   只扫目录结构，`seal-sprint` 只查 task 终态。跳过的代价是 0。

相关工件：

- `.theking/skills/workflow-governance/SKILL.md`（硬规则 1-8、Phase 4
  步骤 5、Phase 5 步骤 2-3）
- `scripts/validation.py`（`has_non_empty_verification_evidence`、
  `validate_verification_layout`、`collect_spec_sections`、
  `spec_section_has_content`）
- `scripts/workflowctl.py`（`handle_check`、`handle_sprint_check`、
  `handle_seal_sprint`）
- `templates/workflow/spec.md.tmpl`（Acceptance 结构）
- `scripts/sprint_plan.py::render_spec_markdown`（spec 生成的唯一入口）

## Decision

**把"Runnable evidence"升格为第 9 条硬规则，并同时在校验器里
兜住；不加任何 opt-out 逃生阀。**

三个并列的闸，对应本次 sprint 的 3 个 task：

### 闸 1 — smoke.md 内容校验（task 级）

`validation.py` 的 `has_non_empty_verification_evidence` 改为
`has_substantive_verification_evidence`：

- 向下兼容旧行为（size > 0 是必要条件，不是充分条件）。
- 新增 placeholder 文本黑名单检测：文件里若**只**包含以下任一
  词条（大小写无关、位置无关）且无其他实质内容，视为伪证据：
  - `待补` / `TODO` / `tbd` / `pending` / `placeholder` / `fill me in`
  - `<!-- ... -->` 纯注释行
- 判定逻辑复用 `spec_section_has_content` 成熟的"剥离注释 + 去项目
  符号 + 检测残余文字"模式。
- 阈值：同 profile 目录下**所有**文件的 substantive 文本拼接后
  长度 ≥ 40 个非空字符（经验值，一条能看的证据条目至少达到这
  个量）。

不加 `--skip-smoke-check` opt-out。错误提示写明"请补一段真实
命令/请求/截图/观察，不要只写『待补』"。

### 闸 2 — spec.md Acceptance 结构升级（task 级 + 公共契约）

`templates/workflow/spec.md.tmpl` 与 `sprint_plan.py::render_spec_markdown`
升级：每条 Acceptance 条目**强制追加** 2 个子行：

```
- [ ] <criterion>
  - 验证方式：<unit | integration | smoke | e2e | manual-observed>
  - 证据路径：<verification/.../xxx.md | tests/xxx_test.go::TestXxx>
```

`validation.py::validate_spec` 在 `require_content=True` 且**非 legacy
结构**时，额外跑 `validate_acceptance_traceability`：

- 每个顶层 `- [ ]` checkbox 下必须有"验证方式"和"证据路径"两行
  子项（任一缺失即 fail）。
- "验证方式"值必须在允许集合 `{unit, integration, smoke, e2e,
  manual-observed}` 内；未知值 fail 并列出允许值。
- "证据路径"不做文件存在性检查（避免循环依赖——spec 在 red
  阶段写，证据文件可能还没写）；只校验非空字符串。

兼容路径：

- legacy 双 section spec（`is_legacy_spec_structure`）继续旁路。
- 已 `done`、已 `sealed` 的 sprint **不追溯**校验（checkpoint 仅对
  新推进状态生效）。

### 闸 3 — sprint 级 smoke 汇总（sprint 级）

新增 `workflowctl sprint-smoke` 子命令，`seal-sprint` 前置调用：

- 扫描 sprint 下所有 task 的 `execution_profile` 集合。
- 对每个 profile（web.browser / backend.http / backend.cli /
  backend.job），要求 `sprint-dir/verification/<profile-dir>/`
  目录存在且至少有一个 substantive 文件（复用闸 1 的判定）。
- 若缺：fail 并列出缺失的 profile + 建议补证据方式。
- `seal-sprint` 在推 `status: sealed` **之前**调用
  `sprint-smoke`，任一 profile 缺证据 → 拒绝 seal。

为什么要 sprint 级而不仅仅靠 task 级：单 task 的 smoke 只覆盖
单 task 的局部，但"真实联调"需要**跨 task 的端到端**（如
voiceagent4 这种"ASR+LLM+TTS+WebRTC 串起来"的场景，单个 task
的 smoke 都能过，但拼起来 panic）。sprint-smoke 是这层的唯一
落点。

### 闸 4 — SKILL.md 硬规则第 9 条

在硬规则列表里加一条：

> **9. 有启动入口的 sprint 必须有"冷启动真实跑通"证据** — 任何
> `backend.http` / `backend.cli` / `backend.job` / `web.browser`
> 画像的 task，`done` 之前必须在 `verification/<profile>/smoke.md`
> 里留下：启动命令 + 启动后 stdout/stderr 片段 + 至少一条**非
> mock** 的请求/交互/观察证据；纯单元测试不算。sprint 级
> `seal-sprint` 通过 `sprint-smoke` 核查跨 task 的联调证据。
> → 落地于 Phase 4 步骤 5、Phase 5 步骤 1/7

同时把 Phase 4 步骤 5 与 Phase 5 步骤 2-3 的正文措辞从「必做」
升级为「由 check / sprint-smoke 强制校验」，并在 spec.md 模板
与 `default_test_plan` 的 test plan 骨架里同步新增 Acceptance
traceability 格式示例。

## Consequences

### Positive

- 把"能编译就算完"这条 LLM 最爱钻的缝彻底堵死。
- 三个闸都有独立的 task，独立 TDD、独立 review，回滚粒度清晰。
- validation 逻辑集中、规则层与代码层对齐，下游 AI 工具（Cursor
  / Codex / CodeBuddy / Claude Code）零差异体验。
- smoke 证据现在必须是"人类可读的一段话"，不是"文件大小 > 0"；
  审计意义恢复。

### Negative

- 下游已有 sprint 的 in-progress task 升级后会被新闸拦一次。
  **缓解**：spec.md 新格式只对 `require_content=True` 且**新建**
  task 生效；legacy spec 与已 sealed sprint 不追溯。
- spec 模板变"重"一点（每条 acceptance 多 2 行）。
  **缓解**：`render_spec_markdown` 从 plan.json hints 自动填入
  占位，AI 只要补值不必手打骨架。
- `sprint-smoke` 与 `seal-sprint` 耦合使 seal 不再是纯元数据动作。
  **缓解**：sprint-smoke 是幂等、只读 + 报错性质的校验，不产生
  副作用；失败时提示"补证据或显式 `--skip-smoke` 豁免"——**我们
  拒绝加 skip 选项**，保持与 I-003"硬规则不让步"原则一致。

### Neutral

- 已 sealed 的 sprint-001/002/003 按约定不追溯。若用户希望补
  齐历史 sprint 的 smoke 证据，走 `followup-sprint` 新起一道。

## Alternatives Considered

- **只改 SKILL 文档，不改校验器**：拒绝。本次事故根因就是
  "规则是文档、执行无闸"；只改文档是继续放任。
- **给 `sprint-smoke` 加 `--skip` 逃生阀**：拒绝。I-003 先例
  已明确"硬规则不让步"；一旦开口，偷懒会被泛化。
- **smoke.md 检测用 LLM 语义校验**：拒绝。非确定性、跨工具不
  一致、不可审计。用 placeholder 黑名单 + 长度阈值足够兜住
  90% 偷懒场景，剩余 10% 的"看上去像但其实没跑"交给 code-reviewer
  人肉审。
- **把 Acceptance traceability 做成可选**：拒绝。可选 = AI 永远
  不选。要么都有，要么都没有。已存在的 legacy 旁路已经给了历史
  兼容通路。

## Status

Accepted — 落地于 sprint-004 TASK-001/002/003。
