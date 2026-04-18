#!/usr/bin/env bash
# dogfood.sh - Local development installer for theking
# Usage:
#   ./dogfood.sh              # Install/upgrade theking in editable mode
#   ./dogfood.sh --ensure    # Also run workflowctl ensure on theking project itself
#   ./dogfood.sh --help      # Show help

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[info]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }
error() { echo -e "${RED}[error]${NC} $*" >&2; }

show_help() {
    cat <<'EOF'
dogfood.sh - Local development installer for theking

Usage:
  ./dogfood.sh [OPTIONS]

Options:
  --ensure      Also run 'workflowctl ensure' on theking project itself
  --pip        Use pip instead of uv for installation
  --reinstall   Force reinstallation
  --help        Show this help message

Examples:
  ./dogfood.sh                  # Quick install/update with uv
  ./dogfood.sh --ensure         # Install and ensure theking project itself
  ./dogfood.sh --pip           # Use pip instead of uv
  ./dogfood.sh --reinstall     # Force reinstall

EOF
}

# Parse arguments
RUN_ENSURE=false
USE_PIP=false
REINSTALL_FLAG=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --ensure)
            RUN_ENSURE=true
            shift
            ;;
        --pip)
            USE_PIP=true
            shift
            ;;
        --reinstall)
            REINSTALL_FLAG="--force-reinstall"
            shift
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Detect package manager
detect_package_manager() {
    if command -v uv &> /dev/null; then
        echo "uv"
    elif command -v pipx &> /dev/null; then
        echo "pipx"
    elif command -v pip &> /dev/null; then
        echo "pip"
    else
        echo ""
    fi
}

# Install with uv
install_with_uv() {
    info "Installing theking with uv..."

    # Check if uv is available
    if ! command -v uv &> /dev/null; then
        error "uv not found. Please install uv first: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi

    cd "${PROJECT_DIR}"

    # Sync the project (installs dependencies and the package in editable mode)
    info "Running 'uv sync' to install theking in editable mode..."
    uv sync ${REINSTALL_FLAG}

    # Ensure the workflowctl command is available
    if uv run workflowctl --help &> /dev/null; then
        info "workflowctl is working via 'uv run workflowctl'"
    else
        warn "workflowctl may not be properly installed. Try: uv run workflowctl --help"
    fi

    info "Installation complete! You can now use:"
    info "  uv run workflowctl --help"
    info "Or activate the virtual environment: source .venv/bin/activate"
}

# Install with pip
install_with_pip() {
    info "Installing theking with pip..."

    cd "${PROJECT_DIR}"

    # Install in editable mode
    pip install -e . ${REINSTALL_FLAG}

    info "Installation complete! workflowctl should now be available in your PATH."
}

# Install with pipx
install_with_pipx() {
    info "Installing theking with pipx..."

    cd "${PROJECT_DIR}"

    # Uninstall first if already installed
    if pipx list | grep -q theking; then
        info "Uninstalling existing theking installation..."
        pipx uninstall theking
    fi

    # Install in editable mode
    pipx install --editable . ${REINSTALL_FLAG}

    info "Installation complete! workflowctl should now be available in your PATH."
}

# Run workflowctl ensure on theking project itself
run_ensure() {
    info "Running 'workflowctl ensure' on theking project itself..."

    cd "${PROJECT_DIR}"

    # Determine how to run workflowctl
    local WORKFLOWCTL=""
    if [[ -f ".venv/bin/workflowctl" ]]; then
        WORKFLOWCTL=".venv/bin/workflowctl"
    elif command -v workflowctl &> /dev/null; then
        WORKFLOWCTL="workflowctl"
    elif command -v uv &> /dev/null; then
        WORKFLOWCTL="uv run workflowctl"
    else
        error "Cannot find workflowctl. Please install theking first."
        exit 1
    fi

    info "Using: ${WORKFLOWCTL}"

    # Run ensure
    ${WORKFLOWCTL} ensure --project-dir "${PROJECT_DIR}" --project-slug theking

    info "'workflowctl ensure' completed."
}

# Main logic
main() {
    info "Starting theking dogfood installation..."
    info "Project directory: ${PROJECT_DIR}"

    if [[ "${USE_PIP}" == true ]]; then
        install_with_pip
    else
        # Try uv first, then pipx, then pip
        local PM
        PM=$(detect_package_manager)

        case "${PM}" in
            uv)
                install_with_uv
                ;;
            pipx)
                install_with_pipx
                ;;
            pip)
                warn "uv not found, falling back to pip."
                install_with_pip
                ;;
            *)
                error "No suitable package manager found."
                error "Please install uv (recommended): https://docs.astral.sh/uv/getting-started/installation/"
                error "Or install pipx: https://pypa.github.io/pipx/"
                exit 1
                ;;
        esac
    fi

    # Run ensure if requested
    if [[ "${RUN_ENSURE}" == true ]]; then
        run_ensure
    fi

    echo ""
    info "Done! theking has been installed/updated."
    info "Test it with: cd /path/to/your/project && workflowctl ensure --project-dir . --project-slug <your-project>"
}

main
