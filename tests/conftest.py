"""pytest config — make repo root importable so tests can do `from scripts.x import y`.

Rationale: existing tests historically shell out to `workflowctl.py` via
subprocess, so sys.path never mattered. Sprint-010 introduces unit tests that
import `scripts.validation` helpers directly (finer-grained gates, faster
loops). Injecting the repo root here keeps that import path uniform.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
