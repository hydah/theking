# ADR-002: Home installer contract for theking

## Context

`theking` currently documents `pipx install /path/to/theking` and `uv tool install /path/to/theking` as the primary way to expose `workflowctl`. The new requirement adds a user-facing `install.sh` for people who clone the repository locally and want to install the skill into home-directory runtime locations.

The installer must answer five public-contract questions:

1. What gets installed into the home directory.
2. Which target directories are used by default versus optionally.
3. Which command(s) are exposed on `PATH`.
4. How repeat runs and upgrades behave.
5. Which non-interactive flags are supported for automation and tests.

This is a public installer contract change, so the decisions must be explicit before implementation.

## Decision

- **Main install root**: materialize a managed copy under `~/.agents/skills/theking`.
- **Optional runtime projections**: if `~/.claude` and/or `~/.codebuddy` exist, prompt whether to expose the skill under `~/.claude/skills/theking` and/or `~/.codebuddy/skills/theking`.
- **Projection mode**: prefer symlinks from optional runtime targets back to the managed `~/.agents/skills/theking` copy; fall back to a materialized copy if symlinks are unavailable.
- **Installed content boundary**: include the runtime-relevant repository surface (`.theking/`, `scripts/`, `templates/`, `README.md`, `SKILL.md`, `pyproject.toml`) and exclude repository-only artifacts such as `.git/`, `ref/`, caches, build outputs, and egg-info metadata.
- **PATH exposure**: expose `workflowctl` plus repository-scoped wrappers for the root shell helpers (`theking-install` for `install.sh`, `theking-dogfood` for `dogfood.sh`), installed into `~/.local/bin` unless overridden. Do not expose internal Python modules under `scripts/` as direct PATH commands.
- **Shell profile handling**: do not edit `~/.zshrc`, `~/.bashrc`, or similar files automatically; instead, print an explicit PATH hint when the chosen bin directory is not on `PATH`.
- **Idempotency**: repeated runs must be safe. If managed files are unchanged, treat the run as current; if projections or wrappers are missing or stale, repair them in place.
- **Upgrade semantics**: the installer owns the files it creates. By default it should preserve drifted managed files and ask the user to rerun with `--force` when overwrite is required.
- **Minimum non-interactive interface**: support `--yes`, `--targets`, `--bin-dir`, and `--force`.

## Consequences

### Positive

- Users get a stable install that does not depend on keeping the original clone around.
- Optional `.claude` / `.codebuddy` exposure matches the repository’s existing projection model.
- `workflowctl` remains the main public CLI while `theking-install` and `theking-dogfood` provide explicit helper entrypoints for the repository shell scripts.
- Test automation becomes practical because the installer has a minimal non-interactive mode.

### Negative

- The managed copy consumes more disk space than a direct symlink to the clone.
- The installer must maintain a lightweight notion of managed state to distinguish current content from drift.
- Internal Python modules still remain private implementation detail even though the two root shell helpers gain explicit PATH wrappers.

## Alternatives Considered

- **Directly symlink the cloned repository into home directories**: rejected because the install would break if the clone is moved or deleted.
- **Copy the full repository into every runtime target**: rejected because upgrades and drift handling become much harder across multiple copies.
- **Expose every shell or Python helper on `PATH`**: rejected because only `workflowctl` is currently documented and tested as a stable public interface.
- **Automatically modify shell rc files**: rejected because it is invasive and hard to make predictable across environments.

## Status

Accepted — governs sprint-005 home-installer implementation.
