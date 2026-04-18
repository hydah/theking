"""TASK-007 sprint-002: agent catalog architect upgrade.

The scaffold catalog template must move architect from 按需 into 条件必须
with the 4 trigger signals listed verbatim.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "workflowctl.py"
CATALOG_TEMPLATE = (
    REPO_ROOT / "templates" / "scaffold" / "theking_agents_catalog.md.tmpl"
)


SIGNALS = (
    "跨 module 接口",
    "引入新依赖",
    "公共接口变更",
    "数据迁移",
)


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def read_template() -> str:
    return CATALOG_TEMPLATE.read_text(encoding="utf-8")


# --- Template structure ---------------------------------------------------


def test_catalog_template_lists_architect_under_conditional_required() -> None:
    text = read_template()
    # Locate the 条件必须 agent block.
    start = text.index("### 条件必须 agent")
    end = text.index("### ", start + 1)
    block = text[start:end]
    assert "architect" in block, (
        "architect must appear in 条件必须 agent table, not 按需 agent"
    )


def test_catalog_template_on_demand_block_no_longer_lists_architect() -> None:
    text = read_template()
    start = text.index("### 按需 agent")
    # Consume through end-of-file (按需 is the last subsection).
    block = text[start:]
    assert "architect" not in block, (
        "architect row must not also appear in 按需 agent section"
    )


def test_catalog_template_names_all_four_architect_signals() -> None:
    text = read_template()
    for signal in SIGNALS:
        assert signal in text, f"catalog template missing architect signal: {signal}"


def test_catalog_template_architect_row_references_signal_list() -> None:
    # 架构师触发条件必须指向 4 条信号列表的锚点词，而不是笼统的"架构决策"。
    text = read_template()
    start = text.index("### 条件必须 agent")
    end = text.index("### ", start + 1)
    block = text[start:end]
    # Expect at least one of the 4 signal phrases inline on the architect row.
    hits = sum(signal in block for signal in SIGNALS)
    assert hits >= 1, (
        "architect row in 条件必须 table should cite >=1 specific signal"
    )


# --- Scaffold-level regeneration -----------------------------------------


def test_init_project_produces_upgraded_catalog(tmp_path: Path) -> None:
    project_slug = "demo-app"
    project_dir = tmp_path / project_slug
    project_dir.mkdir()

    assert (
        run_cli(
            [
                "init-project",
                "--project-dir",
                str(project_dir),
                "--project-slug",
                project_slug,
            ],
            cwd=tmp_path,
        ).returncode
        == 0
    )

    catalog = (
        project_dir / ".theking" / "agents" / "catalog.md"
    ).read_text(encoding="utf-8")
    # Architect must be in the 条件必须 block in the regenerated catalog too.
    conditional_block = catalog[
        catalog.index("### 条件必须 agent") : catalog.index(
            "### 按需 agent", catalog.index("### 条件必须 agent")
        )
    ]
    assert "architect" in conditional_block
    for signal in SIGNALS:
        assert signal in catalog


def test_ensure_is_idempotent_for_catalog(tmp_path: Path) -> None:
    project_slug = "demo-app"
    project_dir = tmp_path / project_slug
    project_dir.mkdir()

    assert (
        run_cli(
            [
                "init-project",
                "--project-dir",
                str(project_dir),
                "--project-slug",
                project_slug,
            ],
            cwd=tmp_path,
        ).returncode
        == 0
    )
    catalog_path = project_dir / ".theking" / "agents" / "catalog.md"
    first = catalog_path.read_text(encoding="utf-8")

    assert (
        run_cli(
            [
                "ensure",
                "--project-dir",
                str(project_dir),
                "--project-slug",
                project_slug,
            ],
            cwd=tmp_path,
        ).returncode
        == 0
    )
    second = catalog_path.read_text(encoding="utf-8")
    assert first == second, "ensure must not mutate catalog.md if unchanged"
