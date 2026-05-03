# ADR-002: Sealed sprints and followup-sprint CLI surface

## Context

Sprint-002 closed cleanly, but `evolution-workflow-ux.md` I-007 surfaced a real
gap: there is no formal way to mark a sprint as "封印 / sealed", and no formal
way to start a follow-up sprint that points back at an earlier one. Today the
end of a sprint is a convention (`Phase 5` runs + `deactivate`), and any
follow-up work either pollutes the closed sprint's history or starts a new
sprint with no audit link to its source.

Concretely, two scenarios show up:

- **场景 A**: sprint-N just closed; a small enhancement of the same theme is
  noticed. Tempting to add a TASK-008 to sprint-N. That rewrites the sprint's
  Task Overview, blurs "what did sprint-N actually deliver", and breaks the
  audit invariant that a closed sprint is an immutable artifact.
- **场景 B**: sprint-N closed several sprints ago; reviewing it now reveals a
  real bug or genuine leftover. New work needs to point at sprint-N's evidence
  (review notes, verification artifacts) so the follow-up has a paper trail.

Two pieces are missing:

1. A machine-checkable seal: `workflowctl init-task --sprint <sealed>` must
   refuse, otherwise the convention is just words.
2. A standardized way to spawn a followup sprint that records the back-link in
   both directions (in the new sprint.md and in a `followups.md` under the
   sealed sprint).

This ADR covers the **public CLI surface change** signal from the planner
template (new subcommands are public contract). It does **not** cover the
content of sprint-003's other tasks (subagent-gating language, integration
tests, skill text edits) — those are local refinements with no new
contract surface.

## Decision

Add two new `workflowctl` subcommands and a small contract change to
`sprint.md`:

1. `workflowctl seal-sprint --sprint-dir <dir>`
   - Requires every task in the sprint to be in a terminal status
     (`done` / `blocked`).
   - Adds an opt-in YAML frontmatter block at the top of `sprint.md`:
     ```yaml
     ---
     status: sealed
     sealed_at: 2026-04-18T00:00:00Z
     ---
     ```
   - Idempotent: re-running on an already-sealed sprint is a no-op.
   - `init-task --sprint <sealed-sprint>` and `init-sprint-plan --sprint
     <sealed-sprint>` reject with a pointer to `followup-sprint`.

2. `workflowctl followup-sprint --source-sprint <path> --new-theme <slug>`
   - Wraps `init-sprint --theme <slug>` so the new sprint name carries a
     conventional suffix (`sprint-NNN-<slug>` is unchanged; the back-link
     metadata is what matters, not the name).
   - Inserts a `## Follow-up Source` section into the new `sprint.md`,
     pointing at the source sprint's relative path.
   - Appends a one-line entry to `<source-sprint>/followups.md`
     (single file, append-only, created if missing) listing the new sprint
     name and a one-sentence reason from a `--reason` flag.
   - Does NOT need the source sprint to be sealed (场景 A is allowed: a
     followup can be raised the moment a sprint is in `done`-only state, even
     before `seal-sprint` runs). But if the source sprint *is* sealed,
     followup-sprint must keep working — sealing is the strong guarantee, the
     followup link is the audit trail.

3. `sprint.md` template gains an optional, leading YAML frontmatter block.
   When absent, the existing `# sprint-NNN-<slug>` H1 stays the source of
   truth — every test that reads sprint.md today must keep passing. When
   present, only the `status` and `sealed_at` fields are recognized;
   unknown keys raise `WorkflowError` (defensive, prevents drift).

## Consequences

### Positive

- Sprint-N becomes a true immutable audit unit; "did anyone keep editing
  sprint-N's Task Overview after Phase 5?" becomes a one-grep question
  (frontmatter present → no).
- Followup sprints get a typed back-link instead of vibes. Reviewers can
  navigate from any sealed sprint to every downstream effort caused by it.
- The convention layer in evolution-workflow-ux.md gets paired with a tool
  layer; the I-007 議題 stops being a footnote and becomes mechanism.
- No new dependencies; everything is stdlib + existing template machinery.

### Negative

- One more contract for sprint.md (the optional frontmatter). Templates
  consumed by external readers (humans, future tools) must learn to skip it.
  Mitigated by keeping it strictly opt-in: a sprint without frontmatter
  behaves exactly as today.
- `seal-sprint` adds a rule that "all tasks must be done or blocked" — if a
  user wants to permanently abandon a sprint with in-flight tasks, they will
  have to either `advance-status … blocked` first or accept that
  `seal-sprint` rejects them. We consciously refuse to add `--force`: an
  unsealed sprint is fine; a force-sealed one would silently lose audit
  signal.
- Two new commands enlarge the CLI surface; downstream wrappers (Kimi
  agent.yaml subagents, Claude `.claude/commands/`) do not need updates
  (they invoke `workflowctl` by name), but the agent catalog table and
  README command index will both need a one-line mention per command.

## Alternatives Considered

- **Convention-only**: keep evolution-workflow-ux.md's text as the only
  authority. Rejected because sprint-001 and sprint-002 both showed AI
  agents readily edit sprint.md if no validator stops them; "convention
  without enforcement" is the exact failure mode I-007 is calling out.
- **`reopen-sprint` command**: rejected explicitly by I-007. Reopening a
  sealed sprint breaks its immutability, which is the only reason sealing is
  valuable in the first place.
- **Frontmatter on every sprint.md from day 1**: rejected. Backward
  compatibility for existing sprints (sprint-001, sprint-002) and for the
  hundreds of test fixtures that build a sprint.md and grep for `## Theme`
  is more important than a uniform header. Opt-in keeps the change additive.
- **Auto-numbering ADRs (`workflowctl new-adr`)**: out of scope (I-009,
  P3). Manual NNN selection is fine until concurrent sprints actually
  collide on numbering.

## Status

Accepted
