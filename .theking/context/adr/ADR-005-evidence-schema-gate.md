# ADR-004: Per-profile evidence schema gate

## Context

Sprint-004 introduced `has_substantive_verification_evidence` (ADR-003):
evidence under `verification/<profile>/` must carry >= 40 substantive
characters (after stripping HTML comments, bullet markers, placeholder
tokens). That gate stops pure-placeholder evidence dead, but it does
**not** tell the difference between:

- "ran `pytest tests -q`, observed 596 passed, exit 0" (real smoke)
- "went through the motions, everything looks fine, moving on" (plausible
  40+ substantive chars, zero actual test-execution evidence)

Both are > 40 chars. The second one is a valid failure mode: an LLM
agent summarising its feelings instead of pasting runtime output. In
practice, evidence.md files produced under time pressure drift toward
the second shape because narrative prose is easier than looking up a
command's real stdout.

This is the gap the user called out: "the evidence gate only counts
chars, not semantics".

## Decision

**Add a sibling check `validate_profile_evidence_shape(profile_dir,
profile_name)` that demands profile-specific semantic anchors.** Run
it at exactly the same point `has_substantive_verification_evidence`
runs — `ready_to_merge` / `done` — so no task can be sealed without
carrying real execution evidence.

Anchor catalogue (implementation in
`scripts/validation.py::validate_profile_evidence_shape`):

| Profile        | Required anchors (both must be present)                                                                                        |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `backend.cli`  | (a) command line: `$ <cmd>` / `> <cmd>` / `Command:` at line start (bullet prefix tolerated) <br> (b) exit line: `Exit:` / `exit code` / `returncode` / `Status: <int>` |
| `backend.http` | (a) HTTP method verb at line start: GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS <br> (b) 3-digit status code: `HTTP/1.1 200 OK` or `status: 200`     |
| `backend.job`  | (a) start anchor: ran/started/invoked/launched/began <br> (b) completion anchor: completed/finished/done/succeeded               |
| `web.browser`  | at least one binary artifact of a recognised media type (PNG/JPEG/WebM/MP4/PDF/ZIP/GIF) at least `PROFILE_SCHEMA_MIN_BINARY_BYTES` (= 512) bytes, OR a markdown image reference that resolves under the profile dir to such a file |

Rules:

- **HTML comments are stripped before matching.** Pasting anchors inside
  `<!-- ... -->` does not count. Mirrors `substantive_text_length`.
- **Magic bytes, not extensions.** `web.browser` rejects a text file
  renamed to `.png` — the first 16 bytes must match a real media
  signature. Extension fallback would re-open the escape hatch ADR-003
  was written to close.
- **Markdown image references must stay inside the profile dir.** An
  attacker (or a clumsy paste) cannot reference `../../etc/passwd` to
  pass the gate — `ref_path.relative_to(profile_dir)` gates the resolve.
- **Unknown profiles no-op.** Forward compat: if a future `backend.grpc`
  is added to `EXECUTION_PROFILE_DIRS`, the shape gate simply doesn't
  fire until anchors are defined.
- **No `--skip` flag, no opt-out.** Inherits ADR-001's stance: any
  escape hatch gets generalised by an LLM under time pressure. The
  error message names the missing anchor and both families so authors
  know what to paste.

Layering with existing gates:

1. `has_substantive_verification_evidence` fires first. An empty or
   placeholder-only profile dir errors with the 40-char message — shape
   gate stays silent (one clear error wins).
2. `validate_profile_evidence_shape` fires only when the substantive
   gate passed. It's an orthogonal concern: structure, not volume.

## Consequences

### Positive

- "Typed 40 chars of narrative" is no longer valid evidence for any
  profile. An agent must paste real command output or artifact.
- Forward compat: adding a new profile means adding one entry to the
  catalogue, not editing control flow.
- Error messages are actionable — they name the missing anchor family
  and the profile, so an agent knows what line to paste.
- Magic-byte check closes the rename trick on `web.browser` without
  pulling in a heavy image library.

### Negative

- Existing sprint fixtures in the test suite (historically content with
  40 chars of plausible prose) had to be updated in the same commit
  that introduced the gate. 26 test failures initially; all fixed by
  adding the missing anchors to 5 fixture helpers. Closed the "fixture
  is dishonest evidence" drift at the same time.
- LLMs must now learn the anchor patterns. Mitigation: error message
  lists the accepted forms explicitly; `e2e-runner` / workflow-governance
  skill can be updated in a follow-up to cite ADR-004.

## Alternatives considered

- **Tier into `has_substantive_verification_evidence`**: rejected.
  Mixes two orthogonal concerns (volume vs structure) into one helper,
  harder to explain in error messages, harder to test in isolation.
- **Run the gate at `red → green`**: rejected (handled by the sibling
  task TASK-002 `green-pass-marker-gate`). Shape gate is about
  "evidence is well-formed for its profile"; pass-marker gate is
  about "a test runner actually reported PASS". Different questions,
  different gates.
- **Extension-based check on `web.browser`**: rejected. A `.png` with
  no magic bytes is exactly the attack this gate should stop.

## Status

Accepted — landed in sprint-017 TASK-001 evidence-schema-gate.
