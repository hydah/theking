# ADR-006: Governance must self-govern (mechanical enforcement over text)

## Context

Sprint-017 landed three test-treatment gates (evidence shape / pass
marker / failure-modes). Afterwards, a self-audit discovered three
sprint-017 偏差 in how those very gates were developed:

- **A**: handoff.md was empty across all three tasks; the handoff-anchor
  gate silently passed because its "missing file" branch was lenient.
- **B**: TASK-001's red commit was produced by `git stash push scripts/`
  AFTER writing the implementation, then committing "red" with
  tests-only, then `stash pop`. The skill-text hard rule #4 caught
  nothing because no gate inspected git.
- **C**: All three tasks' code-reviews were self-audited with a terse
  "no findings" — no subagent independence, no checklist of what was
  actually inspected.

The meta-observation: **when the governance designer is also the
governance target, text-only rules drift to zero enforcement under
time pressure**. An LLM reading "先红后绿" understands the rule
perfectly and simultaneously, without conscious intent, rationalizes
the stash-commit-pop dance as "compliant enough".

## Decision

Establish as a theking architectural principle:

**Every hard rule in workflow-governance skill must either:**
1. have a machine gate (workflowctl validator) that enforces it, OR
2. have an audit trail (ledger entry) that makes post-hoc detection
   possible.

**Text-only hard rules are no longer sufficient.** Rules without one
of the two anchors above are to be treated as advisory (and explicitly
labeled as such in the skill).

Implementation landed in sprint-019:

- **TASK-001** — `theking_schema_version` + `created_at` frontmatter
  fields: the discriminator that tells "new task" (post-sprint-019,
  strict) from "legacy task" (pre-sprint-019, lenient).
- **TASK-002** — Tightens `validate_handoff_evidence_anchors` and
  `validate_spec` silent-pass paths for new tasks. Legacy unchanged.
- **TASK-003** — `validate_red_transition_diff` scans git index +
  HEAD commit; rejects red transition when production code is
  present. Closes the "fake red via stash" attack mechanically.
- **TASK-004** — (A) PreToolUse hook `check-spec-exists.js` exits 1
  on no-active-task + production file edit; (B) code-review-round
  template adds `Reviewer:` / `Reviewer independence:` fields;
  `validate_reviewer_declaration` requires ≥10 self-audit bullets
  when reviewer is `self` / `main-agent-fallback`.
- **TASK-005** — Append-only `ledger.jsonl` with sha256 chain-hash;
  `workflowctl ledger` / `audit` subcommands. Every state
  transition is recorded with git_head + staged_diff_summary. After
  the fact, an independent party can verify the timeline.

## Consequences

### Positive

- Three specific sprint-017 偏差 are mechanically impossible for new
  tasks created post-sprint-019.
- Legacy tasks (pre-sprint-019, no schema_version) continue to work
  byte-identically — the `is_new_theking_task` discriminator gates
  every strict path.
- The principle is generalizable: when future sprint introduces a
  new hard rule, the question "what's the machine gate?" becomes
  mandatory during planning.
- Audit is an escape valve for catching rules that are hard to gate
  at runtime — the hash-chained ledger gives "evidence over time"
  where runtime evidence isn't available.

### Negative

- Legacy vs new dispatch doubles the surface area of several
  validators. Mitigated by the single discriminator helper.
- `classify_diff_path` is duplicated across Python (scripts/validation.py)
  and JavaScript (.theking/hooks/check-spec-exists.js). Kept in sync
  by a marker-string parity test.
- Audit is advisory by default — a project that doesn't run
  `workflowctl audit --strict` in CI still has all the runtime gates
  but loses the time-line guarantee. Future sprint may auto-run
  audit in the existing `check` command (gated behind a config).

## Alternatives considered

- **Make audit a hard CI requirement**: rejected for now. Not every
  theking-using project has CI; forcing it would break adoption.
- **No legacy-compat path (flag day)**: rejected. Breaking every
  existing sealed sprint would contradict theking's stability
  promise.
- **Only text upgrade to workflow-governance skill**: rejected. That's
  exactly the failure mode this ADR is addressing.

## Status

Accepted — landed in sprint-019. Future hard-rule additions must
explicitly cite this ADR and declare whether they provide a machine
gate, an audit trail, or both.
