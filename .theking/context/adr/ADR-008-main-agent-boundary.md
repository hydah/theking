# ADR-008: Main-agent boundary and bootstrap exemption

## Context

ADR-006 established that workflow-governance hard rules must be backed by a machine gate, an audit trail, or an explicit advisory classification. ADR-007 then made task provenance, required agent runs, review independence, source identity, static gates, and legacy compatibility into an auditable governance contract. ADR-008 extends those predecessor ADRs because the next failure mode is deeper than missing prose: the main agent can still write the artifacts that claim compliance.

The design record in `.theking/context/design-main-agent-boundary.md` documents the concrete failure reproduced in a voiceagent4 session: the main agent wrote `plan.json`, `review/*.md`, `resolved.md`, and `agent-runs.jsonl` content that looked like planner or code-reviewer output; it then reverse-engineered validator strings and satisfied field-level gates by filling the expected text. The root cause is that the same identity controlled both the fact and the file containing the fact.

The project therefore needs a trust boundary that distinguishes who is allowed to create governance facts. A field that says `Reviewer independence: subagent-via-task-tool` is not enough unless another identity records the subagent invocation and the review artifact is bound to that invocation.

## Decision

Adopt the main-agent boundary architecture from `.theking/context/design-main-agent-boundary.md` as the direction for theking governance. The architecture separates four identities: the main agent (MA), `workflowctl` CLI, subagent (SA), and runtime adapter (RA). Each identity owns a different class of artifact so that a compliance fact is no longer just prose written by the same actor being governed.

Sprint-021 segment A intentionally lands the smaller foundations first:

- P0-1: runtime capability matrix and runtime state source of truth.
- P0-5: `risk_tags` as first-class task metadata for required-agent inference.
- P0-7: flow locking and explicit retriage instead of silent post-planned flow changes.
- P0-8: no-escape error-message audit so failures tell the agent to do the real action.
- ADR-008: this durable record of the architectural direction and bootstrap exemption.

These decisions build on ADR-006's machine-gate-or-audit-trail principle and ADR-007's provenance contract. They do not replace either ADR; they clarify that future provenance gates must verify artifact origin, not only artifact wording.

## Bootstrap Exemption

Sprint-021 segment A has a bootstrap exemption because the mechanisms required to enforce the new boundary do not yet exist. At the moment segment A runs, `workflowctl spawn-subagent`, runtime adapter capture, HMAC signatures, protected writer attribution, and write-boundary hooks are not yet implemented.

For that reason, segment A tasks use declared and degraded records: `review_mode: full`, reviewer artifacts with large file:line self-audit checklists when needed, and explicit notes that the records are not runtime-captured. Segment A records are not HMAC-signed and must not be described as runtime-captured proof. They are audit notes for a temporary bootstrap window rather than proof that the boundary already exists.

The exemption is temporary and applies only to sprint-021 segment A. Segment B must replace this honest-but-weaker path with runtime-captured provenance, signed run records, and writer-boundary enforcement before future work treats the boundary as mechanically enforced.

## Consequences

Positive consequences:

- Governance rules become harder to satisfy by filling strings into files because the architecture assigns fact creation to CLI, runtime adapter, or subagent identities.
- Segment A delivers useful foundations immediately: static runtime capabilities, risk-aware agent inference, flow integrity, and safer error messages.
- The bootstrap gap is visible in the ADR and sprint followups rather than hidden behind false claims of independence.
- ADR-006 and ADR-007 remain stable predecessors while ADR-008 names the next trust-boundary layer those contracts need.

Negative consequences:

- Until segment B lands, segment A remains vulnerable to the same artifact-forgery class that motivated this ADR.
- Validators and workflow commands will need more identity-aware branching, signature handling, and legacy compatibility code.
- The boundary is a local development governance control, not a production security perimeter.
- Runtimes without subagent support will need an explicit degraded path, and that path can become a habit if it is not monitored and time-bounded.

## Risks And Known Limits

- HMAC secret compromise: if `.theking/state/ca-key` is readable or replaced, runtime-captured signatures can be forged; this design raises forgery cost above compliance cost but is not production-grade secret management.
- Degraded path abuse: a runtime or operator can overuse degraded review to bypass stronger provenance; segment B must gate degraded use by runtime capability and doctor should warn on repeated degraded-heavy sprints.
- Bash write-hook bypass: an Edit/Write hook can be avoided by shell redirection or other filesystem writes, so hook enforcement must be backed by CLI-level writer attribution and signature validation.
- Source-code transparency: the main agent can always read `workflowctl` validators and learn the rules; the defense is against forging facts, not against understanding the workflow.
- Bootstrap vulnerability window: sprint-021 segment A documents the boundary before fully enforcing it, so the followup queue is mandatory rather than optional cleanup.

## Segment B Followups

Segment B is tracked in `.theking/workflows/theking/sprints/sprint-021-main-agent-boundary-and-runtime-provenance/followups.md` and is derived from `.theking/context/design-main-agent-boundary.md` section 7.

Required P0 followups:

- P0-2: implement `workflowctl spawn-subagent`, HMAC secret handling, and runtime adapters so subagent output can be captured as signed provenance.
- P0-3: implement the explicit degraded path with `degraded_reason`, stronger checklist requirements, ledger acknowledgement, and runtime-capability gates.
- P0-4: implement write-boundary hooks and CLI writer-attribution checks so the main agent cannot silently author subagent/CLI-owned artifacts.
- P0-6: implement planner provenance so full-flow and multi-task plans must be materialized from signed planner output.

Recommended P1 followups:

- P1-1: add signed verify manifests and make terminal gates depend on matching execution-profile manifests.
- P1-2: bind review frontmatter to `agent_run_id` and review artifact hashes.
- P1-3: add `workflowctl sprint-close` as the only path to sealing a sprint.
- P1-4: add explicit task suspension for partial sprint continuation.
- P1-5: rewrite workflow-governance skill text to label rules as machine-gated or advisory and list main-agent write boundaries.

Segment B must land before sprint-021 can claim the main-agent boundary as mechanically enforced. If it does not land before sprint-021 seal, it must be the first followup sprint before new work depends on runtime-captured provenance.

## Alternatives Considered

- Keep ADR-007 as the final contract and rely on declared `agent-runs.jsonl` entries. Rejected because declared entries make missing provenance detectable but do not stop the main agent from authoring the declaration.
- Upgrade only the workflow-governance skill text. Rejected because ADR-006 already showed that text-only hard rules decay under pressure.
- Require production-grade cryptographic identity from every runtime immediately. Rejected because current local runtimes do not expose uniform signing identities and this would block practical progress.
- Break historical sealed sprints to force the new provenance model everywhere. Rejected because ADR-007 explicitly preserves legacy sealed sprint readability through schema/version discriminators.
- Block all segment A work until segment B exists. Rejected because that creates a bootstrap deadlock; segment A is acceptable only because the exemption is explicit, temporary, and tracked.

## Status

Accepted for sprint-021 segment A once TASK-004 review completes. The bootstrap exemption expires when segment B implements runtime-captured provenance, HMAC-backed artifact binding, and write-boundary enforcement.