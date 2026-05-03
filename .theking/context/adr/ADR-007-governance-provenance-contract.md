# ADR-007: Governance provenance contract

## Context

ADR-006 established that every workflow-governance hard rule must have a machine gate, an audit trail, or be labeled advisory. Sprint-019 improved several gates, but the follow-up audit found that important governance facts were still ambiguous:

- Agent invocation rules in the workflow skill could still be satisfied by prose instead of runtime evidence.
- `agent-runs.jsonl` existed as an optional audit aid, not as validated provenance for new tasks that declare required agents.
- Review independence allowed `self` and `main-agent-fallback` paths that could satisfy review completion without independent reviewer provenance.
- Sealed historical sprint artifacts can fail newer validators because old review prose and current parser behavior do not share a stable compatibility contract.
- Static gates such as ruff and mypy can be omitted from sprint seal evidence even when project policy expects them.
- Local dogfood and runtime hook behavior can accidentally use a global `workflowctl` or a runtime-specific edit tool matcher that is not the current workspace source.

These failures all share the same shape: the project needs a precise contract for which artifacts are authoritative governance facts, how new tasks are checked, and how legacy sealed sprints remain compatible.

## Decision

Adopt the governance provenance contract below for theking tasks created after this ADR.

Hard rules must be machine-gated, audit-trailed, or advisory. A rule is hard only when at least one of these facts is true:

1. A `workflowctl` command or validator can reject non-compliance before the task reaches a terminal state.
2. A structured audit artifact records enough detail for later independent detection of non-compliance.
3. The rule text explicitly says the rule is advisory or degraded for runtimes that cannot provide the required capability.

### Authoritative facts for new tasks

For new tasks, identified by `theking_schema_version` and `created_at` task frontmatter, these artifacts are authoritative within their specific domains:

- `task.md` declares task identity, status, required agents, execution profile, review mode, and schema discriminator.
- `spec.md` declares scope, non-goals, acceptance, test plan, and edge cases.
- `handoff.md` records Phase 1 evidence anchors and implementation boundaries.
- `verification/<profile>/` records RED, GREEN, smoke, and final command evidence.
- `agent-runs.jsonl` records required agent runtime audit facts. It is not cryptographic proof, but it is the structured evidence that a runtime or operator supplied for required agent runs.
- `ledger.jsonl` records state-changing CLI actions and audit facts over time.
- Review files under `review/` record reviewer identity, review independence, findings, and resolution coverage.
- Sprint seal evidence records the final static gate set, source identity, sprint-check, sprint-smoke, and seal manifest.

### Required agent provenance

When a new task declares `required_agents`, each required agent must have a successful matching `agent-runs.jsonl` entry before the task can be treated as complete. The entry must identify the agent, invocation channel, task id or path, status, and timestamp. Extra fields are allowed for forward compatibility.

`agent-runs.jsonl` entries are audit facts, not cryptographic proof. They make missing, failed, or mismatched agent runs detectable. They do not prove the external model identity by themselves.

A runtime without true subagent support must use an explicit degraded path. Degraded means the task can document the limitation and may continue only when the relevant rule is classified as advisory or when another accepted audit trail exists. It must not silently present a main-agent summary as an independent subagent run.

### Review independence

For new tasks, review independence is satisfied only by an independent review channel such as `subagent-via-task-tool` or `subagent-via-cli` paired with matching reviewer provenance. `self` and `main-agent-fallback` may be recorded for legacy compatibility or degraded advisory review, but they do not satisfy independent review completion for new tasks.

The review file remains the human-readable review record. The runtime provenance artifact supplies the audit fact that the independent reviewer was actually invoked.

### Source identity and static gates

Before a sprint can be sealed, the seal evidence must capture source identity for the `workflowctl` that ran the gate. Source identity includes the executable path or module path, project root, version or git head when available, and whether the command came from the current workspace or a global installation.

Static gates are part of the seal contract. At minimum, this project records pytest, ruff, mypy, `workflowctl check`, `workflowctl sprint-check`, and `workflowctl sprint-smoke` evidence when those tools are configured for the touched surface. A seal that omits configured static gates is incomplete, even if pytest passes.

### Legacy sealed sprint compatibility

Historical sealed sprints must not be edited to satisfy this ADR. They are not retroactively reinterpreted as unsealed simply because a newer validator adds stricter requirements.

Validators may normalize old review prose, tolerate missing new artifacts, or report legacy warnings, but the policy must remain explicit: historical sealed sprints remain readable and auditable without editing historical sprint artifacts. New-task strictness applies through schema/version/frontmatter discriminators, not through silent mutation of past artifacts.

## Consequences

### Positive

- Future governance text has a concrete target: every hard rule names the machine gate, audit trail, or advisory/degraded classification that backs it.
- Required agent runs and review independence become checkable facts for new tasks instead of prose claims.
- Static gates and source identity become part of sprint seal evidence, reducing false confidence from partial green runs.
- Sealed historical sprints remain stable artifacts while new work can become stricter.

### Negative

- Validators must carry legacy/new branching and clearer error messages.
- Runtime-specific capabilities remain uneven; some runtimes will operate in degraded mode until they can supply structured provenance.
- Audit artifacts are still operator-supplied. They improve detectability but do not remove the need for review judgment.

## Alternatives Considered

- Require cryptographic signatures for all agent and review runs. Rejected because current runtimes do not expose consistent signing keys or identities, and the project needs a practical local contract first.
- Break all historical sealed sprints under the new validator. Rejected because sealed artifacts are historical records and must remain readable without edits.
- Keep the workflow skill as the sole source of truth. Rejected because the failure mode was text promising behavior that runtime gates did not verify.
- Treat all non-subagent runtimes as equivalent to independent review. Rejected because that hides capability gaps and recreates the self-review failure mode.

## Status

Accepted. Follow-up tasks in sprint-020 implement this contract through validator strictness, reviewer provenance, ledger/audit behavior, source identity capture, static gate evidence, runtime hook/source-lock updates, and synchronized workflow-governance skill text.
