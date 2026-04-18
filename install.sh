#!/usr/bin/env bash
# install.sh - End-user installer for theking home runtimes
#
# Usage:
#   ./install.sh
#   ./install.sh --yes
#   ./install.sh --targets agents,claude --bin-dir ~/.local/bin

set -euo pipefail

SCRIPT_PATH="$0"
while [ -L "$SCRIPT_PATH" ]; do
    LINK_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
    SCRIPT_PATH="$(readlink "$SCRIPT_PATH")"
    case "$SCRIPT_PATH" in
        /*) ;;
        *) SCRIPT_PATH="$LINK_DIR/$SCRIPT_PATH" ;;
    esac
done
REPO_ROOT="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
    echo "[error] python3 is required to install theking." >&2
    exit 1
fi

ASSUME_YES=0
FORCE=0
TARGETS_RAW=""
BIN_DIR="${HOME}/.local/bin"

show_help() {
    cat <<'EOF'
install.sh - End-user installer for theking home runtimes

Usage:
  ./install.sh [OPTIONS]

Options:
  -y, --yes             Non-interactive mode. Installs only ~/.agents/skills/theking unless --targets is supplied.
  --targets LIST        Comma-separated targets: agents,claude,codebuddy
  --bin-dir DIR         Directory where PATH wrappers are installed (default: ~/.local/bin)
  --force               Overwrite conflicting managed targets and wrappers
  -h, --help            Show this help message

Installed commands:
  workflowctl           Main theking CLI
  theking-install       Wrapper to the installed install.sh
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        -y|--yes)
            ASSUME_YES=1
            shift
            ;;
        --targets)
            [ "$#" -ge 2 ] || { echo "[error] --targets requires a value" >&2; exit 1; }
            TARGETS_RAW="$2"
            shift 2
            ;;
        --bin-dir)
            [ "$#" -ge 2 ] || { echo "[error] --bin-dir requires a value" >&2; exit 1; }
            BIN_DIR="$2"
            shift 2
            ;;
        --force)
            FORCE=1
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "[error] Unknown option: $1" >&2
            show_help >&2
            exit 1
            ;;
    esac
done

contains_target() {
    local needle="$1"
    shift || true
    local item
    for item in "$@"; do
        if [ "$item" = "$needle" ]; then
            return 0
        fi
    done
    return 1
}

prompt_yes_no() {
    local message="$1"
    local answer=""
    while true; do
        printf "%s [y/N] " "$message"
        if ! IFS= read -r answer; then
            echo ""
            return 1
        fi
        case "$answer" in
            [Yy]|[Yy][Ee][Ss])
                return 0
                ;;
            ""|[Nn]|[Nn][Oo])
                return 1
                ;;
            *)
                echo "Please answer y or n."
                ;;
        esac
    done
}

SELECTED_TARGETS=()
if [ -n "$TARGETS_RAW" ]; then
    OLD_IFS="$IFS"
    IFS=','
    # shellcheck disable=SC2206
    PARSED_TARGETS=($TARGETS_RAW)
    IFS="$OLD_IFS"
    for raw_target in "${PARSED_TARGETS[@]}"; do
        target="$(printf '%s' "$raw_target" | tr '[:upper:]' '[:lower:]' | xargs)"
        case "$target" in
            agents|claude|codebuddy)
                if ! contains_target "$target" "${SELECTED_TARGETS[@]}"; then
                    SELECTED_TARGETS+=("$target")
                fi
                ;;
            *)
                echo "[error] Unsupported target '$raw_target'. Allowed: agents,claude,codebuddy" >&2
                exit 1
                ;;
        esac
    done
else
    SELECTED_TARGETS=("agents")
    if [ "$ASSUME_YES" -eq 0 ]; then
        if [ -d "${HOME}/.claude" ] && prompt_yes_no "Also expose theking under ~/.claude/skills/theking?"; then
            SELECTED_TARGETS+=("claude")
        fi
        if [ -d "${HOME}/.codebuddy" ] && prompt_yes_no "Also expose theking under ~/.codebuddy/skills/theking?"; then
            SELECTED_TARGETS+=("codebuddy")
        fi
    fi
fi

TARGETS_JOINED=""
if [ "${#SELECTED_TARGETS[@]}" -gt 0 ]; then
    OLD_IFS="$IFS"
    IFS=','
    TARGETS_JOINED="${SELECTED_TARGETS[*]}"
    IFS="$OLD_IFS"
fi

export THEKING_INSTALL_REPO_ROOT="$REPO_ROOT"
export THEKING_INSTALL_HOME="$HOME"
export THEKING_INSTALL_BIN_DIR="$BIN_DIR"
export THEKING_INSTALL_FORCE="$FORCE"
export THEKING_INSTALL_TARGETS="$TARGETS_JOINED"

python3 <<'PY'
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
from pathlib import Path

MARKER_NAME = ".theking-home-install.json"
WRAPPER_MARKER = "# Managed by theking install.sh"
ROOT_FILES = [
    "README.md",
    "SKILL.md",
    "pyproject.toml",
    "install.sh",
    "dogfood.sh",
]
ROOT_DIRS = ["scripts", "templates"]
THEKING_FILES = ["README.md", "bootstrap.md"]
THEKING_DIRS = ["context", "agents", "commands", "skills", "hooks", "prompts", "verification"]
HELPER_WRAPPERS = {
    "theking-install": "install.sh",
}

repo_root = Path(os.environ["THEKING_INSTALL_REPO_ROOT"]).resolve()
home = Path(os.environ["THEKING_INSTALL_HOME"]).expanduser().resolve()
bin_dir = Path(os.environ["THEKING_INSTALL_BIN_DIR"]).expanduser().resolve()
force = os.environ.get("THEKING_INSTALL_FORCE") == "1"
selected_targets = [token for token in os.environ.get("THEKING_INSTALL_TARGETS", "").split(",") if token]
main_target = home / ".agents" / "skills" / "theking"
optional_targets = {
    "claude": home / ".claude" / "skills" / "theking",
    "codebuddy": home / ".codebuddy" / "skills" / "theking",
}


def fail(message: str) -> "NoReturn":
    print(f"[error] {message}", file=sys.stderr)
    raise SystemExit(1)


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def load_marker(path: Path) -> dict[str, object] | None:
    marker_path = path / MARKER_NAME
    if not marker_path.is_file():
        return None
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def is_owned_directory(path: Path) -> bool:
    marker = load_marker(path)
    return marker is not None and marker.get("managed_by") == "theking-install"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def clean_conflicting_target(path: Path, *, allow_owned: bool) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink():
        if force:
            remove_path(path)
            return
        fail(f"Refusing to overwrite symlink without --force: {path}")
    if path.is_file():
        if force:
            remove_path(path)
            return
        fail(f"Refusing to overwrite file without --force: {path}")
    if path.is_dir():
        if allow_owned and is_owned_directory(path):
            remove_path(path)
            return
        if force:
            remove_path(path)
            return
        fail(f"Refusing to overwrite unmanaged directory without --force: {path}")


def write_marker(path: Path, *, role: str, source: str) -> None:
    payload = {
        "managed_by": "theking-install",
        "role": role,
        "source": source,
    }
    (path / MARKER_NAME).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def copy_runtime_surface(src_root: Path, dst_root: Path) -> None:
    dst_root.mkdir(parents=True, exist_ok=True)
    for filename in ROOT_FILES:
        src = src_root / filename
        if src.is_file():
            shutil.copy2(src, dst_root / filename)
    for dirname in ROOT_DIRS:
        src = src_root / dirname
        if src.is_dir():
            shutil.copytree(src, dst_root / dirname, symlinks=False)
    src_theking = src_root / ".theking"
    dst_theking = dst_root / ".theking"
    dst_theking.mkdir(parents=True, exist_ok=True)
    for filename in THEKING_FILES:
        src = src_theking / filename
        if src.is_file():
            shutil.copy2(src, dst_theking / filename)
    for dirname in THEKING_DIRS:
        src = src_theking / dirname
        if src.is_dir():
            shutil.copytree(src, dst_theking / dirname, symlinks=False)


def install_main_copy() -> None:
    staging_target = main_target.parent / ".theking-install-staging"
    if staging_target.exists() or staging_target.is_symlink():
        remove_path(staging_target)
    ensure_parent(staging_target)
    copy_runtime_surface(repo_root, staging_target)
    write_marker(staging_target, role="managed", source=str(repo_root))
    clean_conflicting_target(main_target, allow_owned=True)
    staging_target.replace(main_target)


def install_projection(name: str, target: Path) -> None:
    ensure_parent(target)
    if target.is_symlink():
        if target.resolve(strict=False) == main_target.resolve():
            return
        if not force:
            fail(f"Projection already points elsewhere; rerun with --force: {target}")
        target.unlink()
    elif target.exists():
        if is_owned_directory(target):
            remove_path(target)
        elif force:
            remove_path(target)
        else:
            fail(f"Refusing to overwrite unmanaged runtime target without --force: {target}")

    try:
        relative_target = os.path.relpath(main_target, target.parent)
        target.symlink_to(relative_target, target_is_directory=True)
    except OSError:
        shutil.copytree(main_target, target, symlinks=False)
        write_marker(target, role=f"projection:{name}", source=str(main_target))


def existing_wrapper_is_managed(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return WRAPPER_MARKER in content


def write_wrapper(path: Path, command: list[str]) -> None:
    ensure_parent(path)
    if path.exists() and not existing_wrapper_is_managed(path):
        if force:
            remove_path(path)
        else:
            fail(f"Refusing to overwrite unmanaged wrapper without --force: {path}")
    script = "\n".join(
        [
            "#!/usr/bin/env bash",
            WRAPPER_MARKER,
            "set -euo pipefail",
            "exec " + " ".join(json.dumps(part) for part in command) + ' "$@"',
            "",
        ]
    )
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install_wrappers() -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    write_wrapper(bin_dir / "workflowctl", ["python3", str(main_target / "scripts" / "workflowctl.py")])
    for wrapper_name, relative_target in HELPER_WRAPPERS.items():
        write_wrapper(bin_dir / wrapper_name, ["bash", str(main_target / relative_target)])


install_main_copy()
for name in selected_targets:
    if name == "agents":
        continue
    install_projection(name, optional_targets[name])
install_wrappers()

print(f"[info] Installed theking to {main_target}")
for name in selected_targets:
    if name == "agents":
        continue
    print(f"[info] Exposed runtime target: {optional_targets[name]}")
print(f"[info] Installed commands into {bin_dir}: workflowctl, theking-install")
PY

case ":${PATH}:" in
    *":${BIN_DIR}:"*)
        ;;
    *)
        echo "[info] ${BIN_DIR} is not on PATH for this shell. Add it with:" 
        echo "       export PATH=\"${BIN_DIR}:\$PATH\""
        ;;
esac

echo "[info] Verify with: workflowctl --help"
