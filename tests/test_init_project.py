from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "workflowctl.py"
REPO_ROOT = Path(__file__).resolve().parents[1]

CANONICAL_SHARED = ".theking"
PORTABLE_WORKFLOWCTL_CMD = "workflowctl"


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def workflow_root(tmp_path: Path) -> Path:
    return tmp_path / "demo-app" / ".theking" / "workflows" / "demo-app"


def canonical_root(tmp_path: Path) -> Path:
    return tmp_path / "demo-app" / ".theking"


def assert_runtime_symlink(path: Path, expected_target: Path) -> None:
    assert path.is_symlink(), f"Expected symlink: {path}"
    assert path.resolve() == expected_target.resolve()


def test_init_project_creates_theking_scaffold_and_workflow_root(tmp_path: Path) -> None:
    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_dir = tmp_path / "demo-app"
    theking_dir = project_dir / ".theking"
    project_md = workflow_root(tmp_path) / "project.md"

    assert project_dir.is_dir()
    assert theking_dir.is_dir()
    assert project_md.is_file()
    assert "Demo App" in project_md.read_text(encoding="utf-8")
    assert not (theking_dir / "scripts").exists()
    assert not (theking_dir / "runtime").exists()

    for entry_file in ("CLAUDE.md", "CODEBUDDY.md", "AGENTS.md"):
        path = project_dir / entry_file
        assert path.is_file(), f"Missing {entry_file}"
        content = path.read_text(encoding="utf-8")
        assert ".theking/bootstrap.md" in content, f"{entry_file} missing bootstrap link"
        assert "Do NOT maintain rules here" in content, f"{entry_file} missing guard text"
    assert (theking_dir / "README.md").is_file()
    assert (theking_dir / "bootstrap.md").is_file()
    assert (theking_dir / "context" / "project-overview.md").is_file()
    assert (theking_dir / "context" / "architecture.md").is_file()
    assert (theking_dir / "context" / "dev-workflow.md").is_file()
    assert (theking_dir / "memory" / "MEMORY.md").is_file()
    assert (theking_dir / "verification" / "README.md").is_file()
    assert (theking_dir / "state").is_dir()
    assert (theking_dir / "state" / "session").is_dir()
    assert (theking_dir / "agents" / "README.md").is_file()
    assert (theking_dir / "agents" / "catalog.md").is_file()
    assert (theking_dir / "commands").is_dir()
    assert (theking_dir / "skills").is_dir()
    assert (theking_dir / "hooks").is_dir()
    assert (theking_dir / "prompts").is_dir()
    assert (theking_dir / ".manifests").is_dir()
    assert (theking_dir / "runs").is_dir()
    assert (project_dir / ".github" / "skills" / "workflow-governance" / "SKILL.md").is_file()
    assert (project_dir / ".github" / "prompts" / "decree.prompt.md").is_file()
    theking_readme = (theking_dir / "README.md").read_text(encoding="utf-8")
    bootstrap_doc = (theking_dir / "bootstrap.md").read_text(encoding="utf-8")
    assert "agents/catalog.md" in theking_readme
    assert "*** Add File" not in (theking_dir / "agents" / "README.md").read_text(encoding="utf-8")
    dev_workflow = (theking_dir / "context" / "dev-workflow.md").read_text(encoding="utf-8")
    governance_skill = (theking_dir / "skills" / "workflow-governance" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    decree_command = (theking_dir / "commands" / "decree.md").read_text(encoding="utf-8")
    expected_demo_task = ".theking/workflows/demo-app/sprints/sprint-001-foundation/tasks/TASK-001-demo"
    for content in (dev_workflow, governance_skill, decree_command):
        assert PORTABLE_WORKFLOWCTL_CMD in content
        assert str(SCRIPT_PATH) not in content
        assert str(project_dir) not in content
        assert "workflowctl.py" not in content
        assert ".theking/scripts/workflowctl.py" not in content
    assert f"{PORTABLE_WORKFLOWCTL_CMD} init-project --project-dir . --project-slug demo-app" in dev_workflow
    assert f"{PORTABLE_WORKFLOWCTL_CMD} check --task-dir {expected_demo_task}" in dev_workflow
    assert "优先把 `--project-dir` 传当前项目根目录 `.`" in dev_workflow
    assert f"{PORTABLE_WORKFLOWCTL_CMD} ensure --project-dir . --project-slug demo-app" in governance_skill
    assert f"{PORTABLE_WORKFLOWCTL_CMD} deactivate --project-dir ." in governance_skill
    # Phase 1-5 完整编排是 skill 的职责（唯一真相源）；decree 只做薄入口+对照表。
    assert f"{PORTABLE_WORKFLOWCTL_CMD} init-sprint --project-dir . --project-slug demo-app --theme <theme>" in governance_skill
    assert "先审上下文，再做分流" in governance_skill
    assert governance_skill.index("上下文初勘") < governance_skill.index("此旨意走<完整|轻量>流程")
    assert "light流程只减少规划开销" not in governance_skill
    assert "轻量流程只减少规划开销，不降低交付标准" in governance_skill
    assert "build/lint/type/unit + 画像验证" in governance_skill
    assert "Phase 1: 察情" in governance_skill
    assert governance_skill.index("Phase 1: 察情") < governance_skill.index("Phase 2: 议旨")
    assert "未察案牍、未勘波及、未过调研清单，不得擅宣「轻量流程」" in governance_skill
    assert "Scope / Non-Goals / Acceptance / Test Plan / Edge Cases 全部 section 必须保留" in governance_skill
    assert "build/lint/type/unit checks" in governance_skill
    # decree 侧契约：薄入口必含 skill 指针 + 参数注入 + Phase 对照表
    assert ".theking/skills/workflow-governance/SKILL.md" in decree_command
    assert "$ARGUMENTS" in decree_command
    assert "Phase 1" in decree_command and "Phase 5" in decree_command
    assert "开发工作流底线" in bootstrap_doc
    assert "先做上下文初勘，再决定完整流程还是轻量流程" in bootstrap_doc
    assert "`init-task` 生成的 `spec.md` 是占位稿" in bootstrap_doc
    assert "Compact Recovery" in bootstrap_doc
    assert f"{PORTABLE_WORKFLOWCTL_CMD} status --project-dir . --project-slug demo-app" in bootstrap_doc
    assert f"{PORTABLE_WORKFLOWCTL_CMD} checkpoint --project-dir . --project-slug demo-app --phase phase-2-triage" in bootstrap_doc
    assert "错误示例" in bootstrap_doc
    assert "正确示例" in bootstrap_doc
    assert "工作流底线" in theking_readme
    assert "state/" in theking_readme
    assert "轻量流程不允许跳过 spec、TDD、build/lint/type/unit、执行画像验证、code review、check/sprint-check" in theking_readme
    assert "进入 `red` 前必须补全五个 section 的实际内容" in theking_readme
    assert "先完成最小上下文初勘，再创建 sprint 或 task" in dev_workflow
    assert f"{PORTABLE_WORKFLOWCTL_CMD} status --project-dir . --project-slug demo-app" in dev_workflow
    assert "# 编辑 spec.md，补全五个 section 的实际内容" in dev_workflow
    assert dev_workflow.index("init-task --project-dir . --project-slug demo-app") < dev_workflow.index(
        "# 编辑 spec.md，补全五个 section 的实际内容"
    ) < dev_workflow.index("advance-status --task-dir .theking/workflows/demo-app/sprints/sprint-001-foundation/tasks/TASK-001-demo --to-status red")
    assert not (project_dir / "project.md").exists()
    assert not (project_dir / "sprints").exists()


def test_source_docs_explain_context_before_triage_and_spec_before_red() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    skill = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "先做上下文初勘，再决定完整流程还是轻量流程" in readme
    assert "轻量流程只减少规划开销，不减少交付要求" in readme
    assert "workflowctl status --project-dir . --project-slug demo-app" in readme
    assert "workflowctl checkpoint --project-dir . --project-slug demo-app --phase phase-2-triage" in readme
    assert readme.index("workflowctl init-task --project-dir . --project-slug demo-app --sprint sprint-001-foundation --slug login-flow") < readme.index(
        "# 编辑 .theking/.../spec.md，补全 Scope / Non-Goals / Acceptance / Test Plan / Edge Cases"
    ) < readme.index("workflowctl advance-status --task-dir .theking/workflows/demo-app/sprints/sprint-001-foundation/tasks/TASK-001-login-flow --to-status red")

    assert "第一步不是宣告“轻量流程”，而是完成最小上下文初勘" in skill
    assert "轻量流程只减少 planner 拆解开销，不减少交付要求" in skill
    assert "workflowctl status --project-dir . --project-slug <PROJECT_SLUG>" in skill
    assert "workflowctl checkpoint --project-dir . --project-slug <PROJECT_SLUG> --phase phase-2-triage" in skill


def test_init_project_quotes_shell_paths_in_generated_examples(tmp_path: Path) -> None:
    root_with_space = tmp_path / "root with space"
    root_with_space.mkdir()

    result = run_cli(
        ["init-project", "--root", str(root_with_space), "--project-slug", "demo-app"],
        cwd=root_with_space,
    )

    assert result.returncode == 0, result.stderr
    project_dir = root_with_space / "demo-app"
    dev_workflow = (project_dir / ".theking" / "context" / "dev-workflow.md").read_text(encoding="utf-8")
    governance_skill = (
        project_dir / ".theking" / "skills" / "workflow-governance" / "SKILL.md"
    ).read_text(encoding="utf-8")
    decree_command = (project_dir / ".theking" / "commands" / "decree.md").read_text(encoding="utf-8")
    expected_demo_task = ".theking/workflows/demo-app/sprints/sprint-001-foundation/tasks/TASK-001-demo"

    assert f"{PORTABLE_WORKFLOWCTL_CMD} init-project --project-dir . --project-slug demo-app" in dev_workflow
    assert f"{PORTABLE_WORKFLOWCTL_CMD} check --task-dir {expected_demo_task}" in dev_workflow
    assert f"{PORTABLE_WORKFLOWCTL_CMD} ensure --project-dir . --project-slug demo-app" in governance_skill
    assert f"{PORTABLE_WORKFLOWCTL_CMD} deactivate --project-dir ." in governance_skill
    assert f"{PORTABLE_WORKFLOWCTL_CMD} init-sprint --project-dir . --project-slug demo-app --theme <theme>" in governance_skill
    assert ".theking/skills/workflow-governance/SKILL.md" in decree_command
    for content in (dev_workflow, governance_skill, decree_command):
        assert str(root_with_space) not in content
        assert str(project_dir) not in content
        assert "workflowctl.py" not in content


def test_init_project_preserves_existing_project_files_and_adds_theking(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir()
    readme = project_dir / "README.md"
    readme.write_text("existing project file\n", encoding="utf-8")

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert readme.read_text(encoding="utf-8") == "existing project file\n"
    assert (project_dir / ".theking" / "README.md").is_file()
    assert (project_dir / ".theking" / "agents" / "catalog.md").is_file()
    assert (workflow_root(tmp_path) / "project.md").is_file()
    assert not (project_dir / "project.md").exists()


def test_init_project_preserves_existing_claude_md(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir()
    custom = "# My Project\nCustom CLAUDE.md content\n"
    (project_dir / "CLAUDE.md").write_text(custom, encoding="utf-8")

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    content = (project_dir / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Custom CLAUDE.md content" in content
    assert ".theking/bootstrap.md" in content


def test_init_project_does_not_duplicate_theking_reference(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir()
    existing = "# My Project\n\nSee [.theking/bootstrap.md](.theking/bootstrap.md)\n"
    (project_dir / "CLAUDE.md").write_text(existing, encoding="utf-8")

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    content = (project_dir / "CLAUDE.md").read_text(encoding="utf-8")
    assert content == existing


def test_init_sprint_creates_sequential_sprint_directories_under_theking_workflows(tmp_path: Path) -> None:
    init_project = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert init_project.returncode == 0, init_project.stderr

    first = run_cli(
        [
            "init-sprint",
            "--root",
            str(tmp_path),
            "--project-slug",
            "demo-app",
            "--theme",
            "foundation",
        ],
        cwd=tmp_path,
    )
    second = run_cli(
        [
            "init-sprint",
            "--root",
            str(tmp_path),
            "--project-slug",
            "demo-app",
            "--theme",
            "auth-hardening",
        ],
        cwd=tmp_path,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert (workflow_root(tmp_path) / "sprints" / "sprint-001-foundation" / "sprint.md").is_file()
    assert (workflow_root(tmp_path) / "sprints" / "sprint-002-auth-hardening" / "sprint.md").is_file()


def test_init_sprint_accepts_theking_dir_as_project_dir(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir()
    ensure_result = run_cli(
        ["ensure", "--project-dir", str(project_dir), "--project-slug", "demo-app"],
        cwd=project_dir,
    )

    result = run_cli(
        [
            "init-sprint",
            "--project-dir",
            str(project_dir / ".theking"),
            "--project-slug",
            "demo-app",
            "--theme",
            "foundation",
        ],
        cwd=project_dir,
    )

    assert ensure_result.returncode == 0, ensure_result.stderr
    assert result.returncode == 0, result.stderr
    assert (project_dir / ".theking" / "workflows" / "demo-app" / "sprints" / "sprint-001-foundation" / "sprint.md").is_file()


def test_init_sprint_rejects_theking_dir_passed_to_legacy_root(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir()
    ensure_result = run_cli(
        ["ensure", "--project-dir", str(project_dir), "--project-slug", "demo-app"],
        cwd=project_dir,
    )

    result = run_cli(
        [
            "init-sprint",
            "--root",
            str(project_dir / ".theking"),
            "--project-slug",
            "demo-app",
            "--theme",
            "foundation",
        ],
        cwd=project_dir,
    )

    assert ensure_result.returncode == 0, ensure_result.stderr
    assert result.returncode != 0
    assert "--project-dir" in result.stderr
    assert ".theking" in result.stderr


def test_init_sprint_rejects_symlinked_theking_dir_passed_to_project_dir(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir(parents=True)
    external_theking = tmp_path / "external-theking"
    external_theking.mkdir(parents=True)
    (project_dir / ".theking").symlink_to(external_theking, target_is_directory=True)

    result = run_cli(
        [
            "init-sprint",
            "--project-dir",
            str(project_dir / ".theking"),
            "--project-slug",
            "demo-app",
            "--theme",
            "foundation",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "stay under" in result.stderr or "symlink" in result.stderr


def test_init_sprint_rejects_symlinked_sprints_directory(tmp_path: Path) -> None:
    init_project = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert init_project.returncode == 0, init_project.stderr

    sprints_dir = workflow_root(tmp_path) / "sprints"
    outside_sprints = tmp_path / "outside-sprints"
    outside_sprints.mkdir()
    sprints_dir.rmdir()
    sprints_dir.symlink_to(outside_sprints, target_is_directory=True)

    result = run_cli(
        [
            "init-sprint",
            "--root",
            str(tmp_path),
            "--project-slug",
            "demo-app",
            "--theme",
            "foundation",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "symlink" in result.stderr or "stay under" in result.stderr


AGENT_FILENAMES = [
    "planner.md",
    "tdd-guide.md",
    "code-reviewer.md",
    "security-reviewer.md",
    "e2e-runner.md",
    "architect.md",
    "build-error-resolver.md",
    "doc-updater.md",
    "refactor-cleaner.md",
    "perf-optimizer.md",
]


def test_init_project_creates_agent_definitions_in_theking_and_claude(tmp_path: Path) -> None:
    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_dir = tmp_path / "demo-app"
    theking_agents = project_dir / ".theking" / "agents"
    claude_agents = project_dir / ".claude" / "agents"
    codebuddy_agents = project_dir / ".codebuddy" / "agents"

    # .claude mirrors canonical theking agents via symlink.
    assert_runtime_symlink(claude_agents, theking_agents)
    # .codebuddy is a materialized copy with CodeBuddy-flavored frontmatter —
    # not a symlink (the frontmatter differs from canonical).
    assert not codebuddy_agents.is_symlink()
    assert codebuddy_agents.is_dir()

    for filename in AGENT_FILENAMES:
        theking_file = theking_agents / filename
        claude_file = claude_agents / filename
        codebuddy_file = codebuddy_agents / filename
        assert theking_file.is_file(), f"Missing .theking/agents/{filename}"
        assert claude_file.is_file(), f"Missing .claude/agents/{filename}"
        assert codebuddy_file.is_file(), f"Missing .codebuddy/agents/{filename}"

        theking_content = theking_file.read_text(encoding="utf-8")
        claude_content = claude_file.read_text(encoding="utf-8")
        codebuddy_content = codebuddy_file.read_text(encoding="utf-8")
        assert theking_content == claude_content, f"Content mismatch .claude for {filename}"
        assert theking_content.startswith("---\n"), f"{filename} missing YAML frontmatter"
        assert "name:" in theking_content, f"{filename} missing name field"
        assert "tools:" in theking_content, f"{filename} missing tools field"
        assert "demo-app" in theking_content, f"{filename} missing project slug"

        # CodeBuddy flavor: body identical, frontmatter rewritten.
        assert codebuddy_content.startswith("---\n")
        assert "agentMode: agentic" in codebuddy_content
        assert "enabled: true" in codebuddy_content
        assert "enabledAutoRun: true" in codebuddy_content
        assert "tools: list_dir" in codebuddy_content
        # Canonical Claude-specific keys must be absent.
        for banned in (
            "tools: Read",
            "tools: Read, Grep",
            "tools: Read, Write",
            "model: opus",
            "model: sonnet",
        ):
            assert banned not in codebuddy_content, f"{filename} leaked {banned!r} into CodeBuddy projection"
        # Body (everything after the second `---`) must match.
        _, _, theking_body = theking_content.partition("\n---\n")
        _, _, codebuddy_body = codebuddy_content.partition("\n---\n")
        assert theking_body == codebuddy_body, f"Body mismatch for {filename}"


def test_init_project_preserves_existing_agent_definitions(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    agents_dir = project_dir / ".theking" / "agents"
    agents_dir.mkdir(parents=True)
    custom_content = "---\nname: planner\n---\nCustom planner prompt\n"
    (agents_dir / "planner.md").write_text(custom_content, encoding="utf-8")

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert (agents_dir / "planner.md").read_text(encoding="utf-8") == custom_content
    for filename in AGENT_FILENAMES[1:]:
        assert (agents_dir / filename).is_file()


def test_init_project_rejects_legacy_runtime_directory_when_migrating_agent_file(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    legacy_agent_dir = project_dir / ".theking" / "runtime" / "agents" / "planner.md"
    legacy_agent_dir.mkdir(parents=True)

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "legacy artifact must be a file" in result.stderr.lower()


SKILL_NAMES = ["workflow-governance", "knowledge-base"]


def test_init_project_creates_skill_definitions(tmp_path: Path) -> None:
    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_dir = tmp_path / "demo-app"

    assert_runtime_symlink(project_dir / ".claude" / "skills", project_dir / ".theking" / "skills")
    assert_runtime_symlink(project_dir / ".codebuddy" / "skills", project_dir / ".theking" / "skills")

    for skill_name in SKILL_NAMES:
        for base in (".theking/skills", ".claude/skills", ".codebuddy/skills", ".github/skills"):
            skill_md = project_dir / base / skill_name / "SKILL.md"
            assert skill_md.is_file(), f"Missing {base}/{skill_name}/SKILL.md"
            content = skill_md.read_text(encoding="utf-8")
            assert content.startswith("---\n"), f"{skill_name} missing YAML frontmatter"
            assert f"name: {skill_name}" in content
            assert "demo-app" in content or "Demo App" in content

    # canonical and runtime copies are identical
    for skill_name in SKILL_NAMES:
        canonical = (project_dir / ".theking" / "skills" / skill_name / "SKILL.md").read_text(encoding="utf-8")
        claude_copy = (project_dir / ".claude" / "skills" / skill_name / "SKILL.md").read_text(encoding="utf-8")
        codebuddy_copy = (project_dir / ".codebuddy" / "skills" / skill_name / "SKILL.md").read_text(encoding="utf-8")
        github_copy = (project_dir / ".github" / "skills" / skill_name / "SKILL.md").read_text(encoding="utf-8")
        assert canonical == claude_copy, f"Content mismatch .claude for {skill_name}"
        assert canonical == codebuddy_copy, f"Content mismatch .codebuddy for {skill_name}"
        assert canonical == github_copy, f"Content mismatch .github for {skill_name}"


def test_init_project_preserves_existing_skill_definitions(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    skill_dir = project_dir / ".theking" / "skills" / "workflow-governance"
    skill_dir.mkdir(parents=True)
    custom_content = "---\nname: workflow-governance\n---\nCustom governance rules\n"
    (skill_dir / "SKILL.md").write_text(custom_content, encoding="utf-8")

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == custom_content
    # other skill still created
    assert (project_dir / ".theking" / "skills" / "knowledge-base" / "SKILL.md").is_file()


COMMAND_FILENAMES = [
    "decree.md",
    "analyze-project.md",
]


def test_init_project_creates_command_definitions(tmp_path: Path) -> None:
    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_dir = tmp_path / "demo-app"

    assert_runtime_symlink(project_dir / ".claude" / "commands", project_dir / ".theking" / "commands")
    assert_runtime_symlink(project_dir / ".codebuddy" / "commands", project_dir / ".theking" / "commands")

    for cmd_filename in COMMAND_FILENAMES:
        theking_cmd = project_dir / ".theking" / "commands" / cmd_filename
        claude_cmd = project_dir / ".claude" / "commands" / cmd_filename
        codebuddy_cmd = project_dir / ".codebuddy" / "commands" / cmd_filename
        github_prompt = project_dir / ".github" / "prompts" / cmd_filename.replace(".md", ".prompt.md")
        assert theking_cmd.is_file(), f"Missing .theking/commands/{cmd_filename}"
        assert claude_cmd.is_file(), f"Missing .claude/commands/{cmd_filename}"
        assert codebuddy_cmd.is_file(), f"Missing .codebuddy/commands/{cmd_filename}"
        assert github_prompt.is_file(), f"Missing .github/prompts/{github_prompt.name}"

        theking_content = theking_cmd.read_text(encoding="utf-8")
        claude_content = claude_cmd.read_text(encoding="utf-8")
        codebuddy_content = codebuddy_cmd.read_text(encoding="utf-8")
        github_prompt_content = github_prompt.read_text(encoding="utf-8")
        assert theking_content == claude_content, f"Content mismatch .claude for {cmd_filename}"
        assert theking_content == codebuddy_content, f"Content mismatch .codebuddy for {cmd_filename}"
        assert theking_content == github_prompt_content, f"Content mismatch .github for {cmd_filename}"
        assert theking_content.startswith("---\n"), f"{cmd_filename} missing YAML frontmatter"
        assert "description:" in theking_content, f"{cmd_filename} missing description"
        if cmd_filename == "decree.md":
            assert ".theking/skills/workflow-governance/SKILL.md" in theking_content


def test_init_project_github_export_does_not_include_agents_or_commands(tmp_path: Path) -> None:
    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_dir = tmp_path / "demo-app"
    assert not (project_dir / ".github" / "agents").exists()
    assert not (project_dir / ".github" / "commands").exists()


def test_ensure_prunes_legacy_github_agents_and_commands_when_they_match_runtime(tmp_path: Path) -> None:
    init_result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert init_result.returncode == 0, init_result.stderr

    project_dir = tmp_path / "demo-app"
    runtime_agents = project_dir / ".theking" / "agents"
    runtime_commands = project_dir / ".theking" / "commands"
    github_agents = project_dir / ".github" / "agents"
    github_commands = project_dir / ".github" / "commands"

    shutil.copytree(runtime_agents, github_agents)
    shutil.copytree(runtime_commands, github_commands)

    ensure_result = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert ensure_result.returncode == 0, ensure_result.stderr
    assert not github_agents.exists()
    assert not github_commands.exists()


def test_ensure_preserves_custom_legacy_github_agent_export(tmp_path: Path) -> None:
    init_result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert init_result.returncode == 0, init_result.stderr

    project_dir = tmp_path / "demo-app"
    runtime_agents = project_dir / ".theking" / "agents"
    github_agents = project_dir / ".github" / "agents"

    shutil.copytree(runtime_agents, github_agents)
    (github_agents / "planner.md").write_text("custom legacy export\n", encoding="utf-8")

    ensure_result = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert ensure_result.returncode == 0, ensure_result.stderr
    assert github_agents.is_dir()
    assert (github_agents / "planner.md").read_text(encoding="utf-8") == "custom legacy export\n"


def test_ensure_preserves_legacy_github_commands_with_extra_empty_directory(tmp_path: Path) -> None:
    init_result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert init_result.returncode == 0, init_result.stderr

    project_dir = tmp_path / "demo-app"
    runtime_commands = project_dir / ".theking" / "commands"
    github_commands = project_dir / ".github" / "commands"

    shutil.copytree(runtime_commands, github_commands)
    (github_commands / "custom").mkdir()

    ensure_result = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert ensure_result.returncode == 0, ensure_result.stderr
    assert github_commands.is_dir()
    assert (github_commands / "custom").is_dir()


def test_init_project_preserves_existing_command_definitions(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    commands_dir = project_dir / ".theking" / "commands"
    commands_dir.mkdir(parents=True)
    custom_content = "---\ndescription: Custom decree\n---\nMy custom decree\n"
    (commands_dir / "decree.md").write_text(custom_content, encoding="utf-8")

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert (commands_dir / "decree.md").read_text(encoding="utf-8") == custom_content
    for cmd_filename in COMMAND_FILENAMES:
        if cmd_filename != "decree.md":
            assert (commands_dir / cmd_filename).is_file()


def test_init_project_creates_hooks_and_runtime_settings(tmp_path: Path) -> None:
    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_dir = tmp_path / "demo-app"
    hooks_dir = project_dir / ".theking" / "hooks"

    assert (hooks_dir / "check-spec-exists.js").is_file()
    assert (hooks_dir / "check-task-status.js").is_file()
    assert (hooks_dir / "remind-review.js").is_file()

    import json
    for runtime_dir in (".claude", ".codebuddy"):
        settings_path = project_dir / runtime_dir / "settings.json"
        assert settings_path.is_file(), f"Missing {runtime_dir}/settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        assert "hooks" in settings
        assert "PreToolUse" in settings["hooks"]
        assert "PostToolUse" in settings["hooks"]
        assert any("[theking]" in h["description"] for h in settings["hooks"]["PreToolUse"])
        settings_raw = settings_path.read_text(encoding="utf-8")
        assert ".theking/hooks/" in settings_raw
    assert len(settings["hooks"]["PreToolUse"]) >= 2
    assert any("[theking]" in h["description"] for h in settings["hooks"]["PreToolUse"])


def test_init_project_preserves_existing_runtime_settings(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    custom_settings = '{"custom": true}\n'
    for runtime_dir in (".claude", ".codebuddy"):
        d = project_dir / runtime_dir
        d.mkdir(parents=True)
        (d / "settings.json").write_text(custom_settings, encoding="utf-8")

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    for runtime_dir in (".claude", ".codebuddy"):
        settings = json.loads((project_dir / runtime_dir / "settings.json").read_text(encoding="utf-8"))
        assert settings["custom"] is True
        assert "hooks" in settings
        assert "PreToolUse" in settings["hooks"]
        assert "PostToolUse" in settings["hooks"]


def test_init_project_rejects_invalid_runtime_settings_hook_shape(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    for runtime_dir in (".claude", ".codebuddy"):
        runtime_path = project_dir / runtime_dir
        runtime_path.mkdir(parents=True)
        (runtime_path / "settings.json").write_text(
            '{"hooks": {"PreToolUse": "oops"}}\n',
            encoding="utf-8",
        )

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "must be a list" in result.stderr or "must be an object" in result.stderr


def test_init_project_rejects_non_object_runtime_settings_json(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    for runtime_dir in (".claude", ".codebuddy"):
        runtime_path = project_dir / runtime_dir
        runtime_path.mkdir(parents=True)
        (runtime_path / "settings.json").write_text("[]\n", encoding="utf-8")

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "json object" in result.stderr.lower()


def test_init_project_rejects_invalid_nested_runtime_hook_shape(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    invalid_settings = (
        '{"hooks": {"PreToolUse": ['
        '{"description": "bad", "hooks": "oops"}'
        ']}}\n'
    )
    for runtime_dir in (".claude", ".codebuddy"):
        runtime_path = project_dir / runtime_dir
        runtime_path.mkdir(parents=True)
        (runtime_path / "settings.json").write_text(invalid_settings, encoding="utf-8")

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert ".hooks must be a list" in result.stderr or "must be a list" in result.stderr


def test_ensure_creates_scaffold_on_fresh_project(tmp_path: Path) -> None:
    result = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_dir = tmp_path / "demo-app"
    assert (project_dir / ".theking" / "README.md").is_file()
    assert (project_dir / ".theking" / "agents" / "planner.md").is_file()
    assert (project_dir / ".claude" / "agents" / "planner.md").is_file()
    assert (project_dir / ".codebuddy" / "agents" / "planner.md").is_file()
    assert (project_dir / ".claude" / "settings.json").is_file()
    assert (project_dir / ".github" / "skills" / "workflow-governance" / "SKILL.md").is_file()
    assert (project_dir / ".github" / "prompts" / "decree.prompt.md").is_file()
    assert (workflow_root(tmp_path) / "project.md").is_file()
    assert not (project_dir / ".theking" / "scripts").exists()
    assert not (project_dir / ".theking" / "runtime").exists()

    for entry_file in ("CLAUDE.md", "CODEBUDDY.md", "AGENTS.md"):
        path = project_dir / entry_file
        assert path.is_file(), f"ensure: Missing {entry_file}"
        assert ".theking/bootstrap.md" in path.read_text(encoding="utf-8")

    dev_workflow = (project_dir / ".theking" / "context" / "dev-workflow.md").read_text(
        encoding="utf-8"
    )
    assert f"{PORTABLE_WORKFLOWCTL_CMD} init-project --project-dir . --project-slug demo-app" in dev_workflow
    assert str(SCRIPT_PATH) not in dev_workflow
    assert ".theking/scripts/workflowctl.py" not in dev_workflow


def test_ensure_accepts_project_root_as_project_dir(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir()

    result = run_cli(
        ["ensure", "--project-dir", str(project_dir), "--project-slug", "demo-app"],
        cwd=project_dir,
    )

    assert result.returncode == 0, result.stderr
    assert (project_dir / ".theking" / "workflows" / "demo-app" / "project.md").is_file()


def test_ensure_rejects_project_dir_slug_mismatch(tmp_path: Path) -> None:
    project_dir = tmp_path / "custom-root"
    project_dir.mkdir()

    result = run_cli(
        ["ensure", "--project-dir", str(project_dir), "--project-slug", "demo-app"],
        cwd=project_dir,
    )

    assert result.returncode != 0
    assert "basename exactly matches --project-slug" in result.stderr
    assert "--root <parent-dir>" in result.stderr


def test_ensure_rejects_project_dir_when_only_slugified_name_matches(tmp_path: Path) -> None:
    project_dir = tmp_path / "My App"
    project_dir.mkdir()

    result = run_cli(
        ["ensure", "--project-dir", str(project_dir), "--project-slug", "my-app"],
        cwd=project_dir,
    )

    assert result.returncode != 0
    assert "basename exactly matches --project-slug" in result.stderr
    assert "my-app" in result.stderr


def test_ensure_rejects_project_root_passed_to_legacy_root(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir()

    result = run_cli(
        ["ensure", "--root", str(project_dir), "--project-slug", "demo-app"],
        cwd=project_dir,
    )

    assert result.returncode != 0
    assert "project parent directory, not the project directory itself" in result.stderr
    assert not (project_dir / "demo-app" / ".theking" / "workflows" / "demo-app" / "project.md").exists()


def test_ensure_rejects_slugified_project_root_passed_to_legacy_root(tmp_path: Path) -> None:
    project_dir = tmp_path / "My App"
    project_dir.mkdir()

    result = run_cli(
        ["ensure", "--root", str(project_dir), "--project-slug", "my-app"],
        cwd=project_dir,
    )

    assert result.returncode != 0
    assert "project parent directory, not the project directory itself" in result.stderr
    assert not (project_dir / "my-app" / ".theking" / "workflows" / "my-app" / "project.md").exists()


def test_ensure_is_idempotent(tmp_path: Path) -> None:
    run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    project_md = workflow_root(tmp_path) / "project.md"
    original_content = project_md.read_text(encoding="utf-8")
    project_md.write_text(original_content + "\n## Custom Section\n", encoding="utf-8")

    result = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "## Custom Section" in project_md.read_text(encoding="utf-8")


def test_ensure_after_init_project_does_not_fail(tmp_path: Path) -> None:
    init_result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert init_result.returncode == 0, init_result.stderr

    ensure_result = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert ensure_result.returncode == 0, ensure_result.stderr


def test_ensure_rejects_symlinked_workflow_project_dir_outside_project(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    workflow_parent = project_dir / ".theking" / "workflows"
    workflow_parent.mkdir(parents=True)
    external_dir = tmp_path / "external-workflow"
    external_dir.mkdir()
    (workflow_parent / "demo-app").symlink_to(external_dir, target_is_directory=True)

    result = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "stay under" in result.stderr or "symlink" in result.stderr
    assert not (external_dir / "project.md").exists()


def test_ensure_rejects_dangling_symlinked_project_file_outside_project(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    workflow_project_dir = project_dir / ".theking" / "workflows" / "demo-app"
    workflow_project_dir.mkdir(parents=True)
    outside_target = tmp_path / "outside-project.md"
    (workflow_project_dir / "project.md").symlink_to(outside_target)

    result = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "symlink" in result.stderr or "overwrite" in result.stderr or "stay under" in result.stderr
    assert not outside_target.exists()


def test_init_project_rejects_dangling_symlinked_project_file(tmp_path: Path) -> None:
    project_md = workflow_root(tmp_path) / "project.md"
    outside_target = tmp_path / "outside-project.md"
    project_md.parent.mkdir(parents=True, exist_ok=True)
    project_md.symlink_to(outside_target)

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "symlink" in result.stderr or "overwrite" in result.stderr
    assert not outside_target.exists()


def test_init_project_appends_to_symlinked_claude_md(tmp_path: Path) -> None:
    """When CLAUDE.md is a symlink to a real file, append theking reference to the target."""
    project_dir = tmp_path / "demo-app"
    kb_dir = project_dir / "kb"
    kb_dir.mkdir(parents=True)
    target = kb_dir / "bootstrap.md"
    target.write_text("# My Project\nCustom content\n", encoding="utf-8")
    (project_dir / "CLAUDE.md").symlink_to(target)

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    # Symlink still intact
    assert (project_dir / "CLAUDE.md").is_symlink()
    # Target file has theking reference appended
    content = target.read_text(encoding="utf-8")
    assert "Custom content" in content
    assert ".theking/bootstrap.md" in content


def test_init_project_rejects_symlinked_entry_file_outside_project(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir(parents=True)
    target = tmp_path / "outside" / "CLAUDE.md"
    target.parent.mkdir(parents=True)
    target.write_text("# External\n", encoding="utf-8")
    (project_dir / "CLAUDE.md").symlink_to(target)

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "stay under" in result.stderr or "symlink" in result.stderr
    assert target.read_text(encoding="utf-8") == "# External\n"


def test_init_project_rejects_symlinked_entry_file_outside_project_even_with_existing_reference(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir(parents=True)
    target = tmp_path / "outside" / "CLAUDE.md"
    target.parent.mkdir(parents=True)
    target.write_text("# External\n\nSee [.theking/bootstrap.md](.theking/bootstrap.md)\n", encoding="utf-8")
    (project_dir / "CLAUDE.md").symlink_to(target)

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "stay under" in result.stderr or "symlink" in result.stderr
    assert "External" in target.read_text(encoding="utf-8")


def test_init_project_skips_symlinked_claude_md_with_existing_reference(tmp_path: Path) -> None:
    """When symlinked CLAUDE.md target already has theking reference, skip it."""
    project_dir = tmp_path / "demo-app"
    kb_dir = project_dir / "kb"
    kb_dir.mkdir(parents=True)
    target = kb_dir / "bootstrap.md"
    target.write_text("# My Project\n\nSee [.theking/bootstrap.md](.theking/bootstrap.md)\n", encoding="utf-8")
    (project_dir / "CLAUDE.md").symlink_to(target)

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    content = target.read_text(encoding="utf-8")
    assert content.count(".theking/bootstrap.md") == 2  # original two refs, no extra


def test_init_project_skips_dangling_symlinked_entry_file(tmp_path: Path) -> None:
    """When CLAUDE.md is a dangling symlink, skip it instead of crashing."""
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir(parents=True)
    nonexistent = tmp_path / "nonexistent" / "bootstrap.md"
    (project_dir / "CLAUDE.md").symlink_to(nonexistent)

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    # Dangling symlink untouched
    assert (project_dir / "CLAUDE.md").is_symlink()
    assert not (project_dir / "CLAUDE.md").exists()


@pytest.mark.parametrize(
    ("runtime_path", "is_directory"),
    [
        ((".github", "skills"), True),
        ((".github", "prompts"), True),
        ((".claude", "settings.json"), False),
        ((".codebuddy", "settings.json"), False),
    ],
)
def test_init_project_rejects_symlinked_runtime_paths_outside_project(
    tmp_path: Path,
    runtime_path: tuple[str, ...],
    is_directory: bool,
) -> None:
    project_dir = tmp_path / "demo-app"
    runtime_parent = project_dir.joinpath(*runtime_path[:-1])
    runtime_parent.mkdir(parents=True, exist_ok=True)
    external_target = tmp_path / "external"
    if is_directory:
        external_target.mkdir()
        project_dir.joinpath(*runtime_path).symlink_to(external_target, target_is_directory=True)
    else:
        project_dir.joinpath(*runtime_path).symlink_to(external_target)

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "symlink" in result.stderr or "stay under" in result.stderr
    if is_directory:
        assert list(external_target.rglob("*")) == []
    else:
        assert not external_target.exists()


def test_init_project_creates_runtime_projection_tree(tmp_path: Path) -> None:
    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_dir = tmp_path / "demo-app"
    runtime_dir = canonical_root(tmp_path)

    for path in (
        runtime_dir / "agents",
        runtime_dir / "commands",
        runtime_dir / "skills",
        runtime_dir / "hooks",
        runtime_dir / "prompts",
    ):
        assert path.is_dir(), f"Missing canonical path: {path}"

    assert_runtime_symlink(project_dir / ".claude" / "agents", runtime_dir / "agents")
    assert_runtime_symlink(project_dir / ".claude" / "commands", runtime_dir / "commands")
    assert_runtime_symlink(project_dir / ".claude" / "skills", runtime_dir / "skills")
    # .codebuddy/agents is a materialized copy (CodeBuddy-flavored frontmatter).
    codebuddy_agents = project_dir / ".codebuddy" / "agents"
    assert not codebuddy_agents.is_symlink()
    assert codebuddy_agents.is_dir()
    assert_runtime_symlink(project_dir / ".codebuddy" / "commands", runtime_dir / "commands")
    assert_runtime_symlink(project_dir / ".codebuddy" / "skills", runtime_dir / "skills")


def test_init_project_reuses_existing_runtime_projection_directories(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    runtime_commands = project_dir / ".claude" / "commands"
    runtime_commands.mkdir(parents=True)
    custom_content = "---\ndescription: Existing runtime decree\n---\nCustom decree runtime\n"
    (runtime_commands / "decree.md").write_text(custom_content, encoding="utf-8")

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    canonical_content = (project_dir / ".theking" / "commands" / "decree.md").read_text(encoding="utf-8")
    assert (project_dir / ".claude" / "commands" / "decree.md").read_text(encoding="utf-8") == canonical_content


@pytest.mark.parametrize(
    "bad_path",
    [
        (".claude", "commands", "decree.md"),
        (".codebuddy", "commands", "decree.md"),
        (".github", "prompts", "decree.prompt.md"),
    ],
)
def test_init_project_rejects_directory_where_runtime_file_is_expected(
    tmp_path: Path,
    bad_path: tuple[str, ...],
) -> None:
    project_dir = tmp_path / "demo-app"
    target_dir = project_dir.joinpath(*bad_path)
    target_dir.mkdir(parents=True)

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "must be a file" in result.stderr.lower()


def test_ensure_rejects_directory_where_canonical_runtime_file_is_expected(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    bad_path = project_dir / ".theking" / "agents" / "README.md"
    bad_path.mkdir(parents=True)

    result = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "non-file path" in result.stderr.lower() or "must be a file" in result.stderr.lower()


def test_init_project_rejects_nested_symlink_inside_existing_runtime_projection(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    nested_parent = project_dir / ".github" / "skills"
    nested_parent.mkdir(parents=True)
    external_target = tmp_path / "external-skill"
    external_target.mkdir(parents=True)
    (nested_parent / "workflow-governance").symlink_to(external_target, target_is_directory=True)

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "symlink" in result.stderr or "stay under" in result.stderr
    assert list(external_target.rglob("*")) == []


def test_init_project_rejects_nested_symlink_inside_runtime_source(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    runtime_prompts = project_dir / ".theking" / "prompts"
    runtime_prompts.mkdir(parents=True)
    external_file = tmp_path / "outside.txt"
    external_file.write_text("external content\n", encoding="utf-8")
    (runtime_prompts / "leak.prompt.md").symlink_to(external_file)

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "symlink" in result.stderr or "stay under" in result.stderr
    assert not (project_dir / ".github" / "prompts" / "leak.prompt.md").exists()


def test_init_project_settings_matchers_exclude_all_runtime_dirs(tmp_path: Path) -> None:
    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    for runtime_dir in (".claude", ".codebuddy"):
        settings_raw = (tmp_path / "demo-app" / runtime_dir / "settings.json").read_text(encoding="utf-8")
        assert "\\.claude/" in settings_raw
        assert "\\.codebuddy/" in settings_raw


def test_ensure_refreshes_github_exports_from_runtime_source(tmp_path: Path) -> None:
    init_result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert init_result.returncode == 0, init_result.stderr

    project_dir = tmp_path / "demo-app"
    runtime_skill = project_dir / ".theking" / "skills" / "workflow-governance" / "SKILL.md"
    runtime_prompt = project_dir / ".theking" / "prompts" / "decree.prompt.md"
    runtime_skill.write_text(runtime_skill.read_text(encoding="utf-8") + "\n<!-- refreshed -->\n", encoding="utf-8")
    runtime_prompt.write_text(runtime_prompt.read_text(encoding="utf-8") + "\n<!-- refreshed -->\n", encoding="utf-8")

    ensure_result = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert ensure_result.returncode == 0, ensure_result.stderr

    github_skill = project_dir / ".github" / "skills" / "workflow-governance" / "SKILL.md"
    github_prompt = project_dir / ".github" / "prompts" / "decree.prompt.md"
    assert "<!-- refreshed -->" in github_skill.read_text(encoding="utf-8")
    assert "<!-- refreshed -->" in github_prompt.read_text(encoding="utf-8")


def test_ensure_prunes_deleted_github_exports_from_runtime_source(tmp_path: Path) -> None:
    init_result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert init_result.returncode == 0, init_result.stderr

    project_dir = tmp_path / "demo-app"
    runtime_extra_prompt = project_dir / ".theking" / "prompts" / "extra.prompt.md"
    runtime_extra_prompt.write_text("---\ndescription: extra\n---\n# Extra\n", encoding="utf-8")

    first_ensure = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert first_ensure.returncode == 0, first_ensure.stderr
    github_extra_prompt = project_dir / ".github" / "prompts" / "extra.prompt.md"
    assert github_extra_prompt.is_file()

    runtime_extra_prompt.unlink()
    second_ensure = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert second_ensure.returncode == 0, second_ensure.stderr
    assert not github_extra_prompt.exists()


def test_ensure_preserves_user_github_assets_outside_theking_manifest(tmp_path: Path) -> None:
    init_result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert init_result.returncode == 0, init_result.stderr

    project_dir = tmp_path / "demo-app"
    custom_prompt = project_dir / ".github" / "prompts" / "custom.prompt.md"
    custom_prompt.write_text("---\ndescription: custom\n---\n# Custom\n", encoding="utf-8")

    ensure_result = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert ensure_result.returncode == 0, ensure_result.stderr
    assert custom_prompt.read_text(encoding="utf-8") == "---\ndescription: custom\n---\n# Custom\n"


def test_ensure_rejects_invalid_export_manifest_json(tmp_path: Path) -> None:
    init_result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert init_result.returncode == 0, init_result.stderr

    manifest_path = tmp_path / "demo-app" / ".theking" / ".manifests" / "github-prompts.json"
    manifest_path.write_text("{broken json}\n", encoding="utf-8")

    ensure_result = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert ensure_result.returncode != 0
    assert "valid json" in ensure_result.stderr.lower()


def test_ensure_rejects_manifest_path_that_escapes_export_directory(tmp_path: Path) -> None:
    init_result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert init_result.returncode == 0, init_result.stderr

    project_dir = tmp_path / "demo-app"
    outside_file = project_dir / "outside.txt"
    outside_file.write_text("safe\n", encoding="utf-8")
    manifest_path = project_dir / ".theking" / ".manifests" / "github-prompts.json"
    manifest_path.write_text('["../outside.txt"]\n', encoding="utf-8")

    ensure_result = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert ensure_result.returncode != 0
    assert "stay within the export directory" in ensure_result.stderr.lower()
    assert outside_file.read_text(encoding="utf-8") == "safe\n"


def test_ensure_rejects_symlinked_export_manifest_outside_project(tmp_path: Path) -> None:
    init_result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert init_result.returncode == 0, init_result.stderr

    project_dir = tmp_path / "demo-app"
    external_manifest = tmp_path / "external-manifest.json"
    external_manifest.write_text('["decree.prompt.md"]\n', encoding="utf-8")
    manifest_path = project_dir / ".theking" / ".manifests" / "github-prompts.json"
    manifest_path.unlink()
    manifest_path.symlink_to(external_manifest)

    ensure_result = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert ensure_result.returncode != 0
    assert "symlink" in ensure_result.stderr or "stay under" in ensure_result.stderr
    assert external_manifest.read_text(encoding="utf-8") == '["decree.prompt.md"]\n'


def test_init_project_migrates_legacy_runtime_skill_to_flat_canonical_source(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    legacy_skill_dir = project_dir / ".theking" / "runtime" / "skills" / "workflow-governance"
    legacy_skill_dir.mkdir(parents=True)
    legacy_content = "---\nname: workflow-governance\n---\nLegacy governance rules\n"
    (legacy_skill_dir / "SKILL.md").write_text(legacy_content, encoding="utf-8")

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    canonical_skill = project_dir / ".theking" / "skills" / "workflow-governance" / "SKILL.md"
    assert canonical_skill.read_text(encoding="utf-8") == legacy_content
    assert (project_dir / ".github" / "skills" / "workflow-governance" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == legacy_content
    assert not (project_dir / ".theking" / "runtime").exists()


def test_init_project_retargets_legacy_runtime_agent_symlink_projection(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    legacy_agents_dir = project_dir / ".theking" / "runtime" / "agents"
    legacy_agents_dir.mkdir(parents=True)
    legacy_content = "---\nname: planner\n---\nLegacy planner prompt\n"
    (legacy_agents_dir / "planner.md").write_text(legacy_content, encoding="utf-8")

    claude_dir = project_dir / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "agents").symlink_to("../.theking/runtime/agents", target_is_directory=True)

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    canonical_agents_dir = project_dir / ".theking" / "agents"
    assert_runtime_symlink(claude_dir / "agents", canonical_agents_dir)
    assert (canonical_agents_dir / "planner.md").read_text(encoding="utf-8") == legacy_content
    assert not (project_dir / ".theking" / "runtime").exists()


def test_init_project_rejects_conflicting_legacy_runtime_and_flat_skill_sources(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    canonical_skill_dir = project_dir / ".theking" / "skills" / "workflow-governance"
    canonical_skill_dir.mkdir(parents=True)
    (canonical_skill_dir / "SKILL.md").write_text(
        "---\nname: workflow-governance\n---\nCanonical governance rules\n",
        encoding="utf-8",
    )

    legacy_skill_dir = project_dir / ".theking" / "runtime" / "skills" / "workflow-governance"
    legacy_skill_dir.mkdir(parents=True)
    (legacy_skill_dir / "SKILL.md").write_text(
        "---\nname: workflow-governance\n---\nLegacy governance rules\n",
        encoding="utf-8",
    )

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "canonical artifact conflicts with legacy artifact" in result.stderr.lower()


def test_init_project_rejects_legacy_only_runtime_agent_artifact(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    legacy_agents_dir = project_dir / ".theking" / "runtime" / "agents"
    legacy_agents_dir.mkdir(parents=True)
    (legacy_agents_dir / "custom.md").write_text("custom legacy agent\n", encoding="utf-8")

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "legacy runtime artifact has no canonical destination" in result.stderr.lower()


def test_ensure_rejects_symlinked_legacy_runtime_source_before_migration(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    legacy_runtime_dir = project_dir / ".theking" / "runtime"
    legacy_runtime_dir.mkdir(parents=True)
    external_agents_dir = tmp_path / "external-agents"
    external_agents_dir.mkdir()
    (external_agents_dir / "planner.md").write_text("external planner\n", encoding="utf-8")
    (legacy_runtime_dir / "agents").symlink_to(external_agents_dir, target_is_directory=True)

    result = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "symlink" in result.stderr.lower() or "stay under" in result.stderr.lower()
    assert not (project_dir / ".theking" / "agents" / "planner.md").exists()
    assert not (project_dir / ".claude" / "settings.json").exists()


def test_init_project_rejects_unknown_legacy_runtime_manifest_artifact(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    legacy_manifest_dir = project_dir / ".theking" / "runtime" / ".manifests"
    legacy_manifest_dir.mkdir(parents=True)
    custom_manifest = legacy_manifest_dir / "custom.json"
    custom_manifest.write_text("{}\n", encoding="utf-8")

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "legacy runtime manifest artifact has no canonical destination" in result.stderr.lower()
    assert custom_manifest.read_text(encoding="utf-8") == "{}\n"


def test_ensure_rejects_legacy_runtime_manifest_file_path(tmp_path: Path) -> None:
    init_result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert init_result.returncode == 0, init_result.stderr

    project_dir = tmp_path / "demo-app"
    legacy_manifest_path = project_dir / ".theking" / "runtime" / ".manifests"
    legacy_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_manifest_path.write_text("not a directory\n", encoding="utf-8")

    result = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "legacy runtime manifest path must be a directory" in result.stderr.lower()
    assert legacy_manifest_path.read_text(encoding="utf-8") == "not a directory\n"


def test_init_project_normalizes_legacy_runtime_hook_paths_in_existing_settings(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir(parents=True)
    legacy_settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Edit",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "node .theking/runtime/hooks/check-spec-exists.js",
                        }
                    ],
                    "description": "legacy",
                }
            ]
        }
    }
    claude_dir = project_dir / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "settings.json").write_text(json.dumps(legacy_settings, indent=2) + "\n", encoding="utf-8")

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    settings_raw = (claude_dir / "settings.json").read_text(encoding="utf-8")
    assert ".theking/hooks/check-spec-exists.js" in settings_raw
    assert ".theking/runtime/hooks/check-spec-exists.js" not in settings_raw


# ---------------------------------------------------------------------------
# Kimi CLI runtime projections
#
# Kimi Code CLI (moonshotai) has three relevant surfaces:
#
#   * `.kimi/skills/` — project-level skills, identical SKILL.md format as
#     Claude / CodeBuddy. We symlink it to `.theking/skills/` so skills stay
#     canonical.
#   * `.kimi/AGENTS.md` — Kimi merges AGENTS.md files from the project root
#     down to the working directory (including `.kimi/AGENTS.md`) into the
#     `${KIMI_AGENTS_MD}` system-prompt variable. We symlink `.kimi/AGENTS.md`
#     to the project-root `AGENTS.md` so both paths resolve to the same file.
#   * `.kimi/agent.yaml` + `.kimi/agents/*.yaml` — Kimi's native agent format
#     (YAML). Subagents are declared in the main agent's `subagents:` map and
#     point at `.kimi/agents/<role>.yaml`; each subagent `extend:`s the main
#     agent and sets `system_prompt_path` to the canonical `.theking/agents/
#     <role>.md` so the prompt body remains single-sourced.
# ---------------------------------------------------------------------------


KIMI_SUBAGENT_ROLES = [
    "planner",
    "tdd-guide",
    "code-reviewer",
    "security-reviewer",
    "e2e-runner",
    "architect",
    "build-error-resolver",
    "doc-updater",
    "refactor-cleaner",
    "perf-optimizer",
]


def test_init_project_kimi_skills_is_symlink_to_canonical(tmp_path: Path) -> None:
    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_dir = tmp_path / "demo-app"
    canonical_skills = project_dir / ".theking" / "skills"
    kimi_skills = project_dir / ".kimi" / "skills"

    assert_runtime_symlink(kimi_skills, canonical_skills)
    for skill_name in SKILL_NAMES:
        kimi_skill_md = kimi_skills / skill_name / "SKILL.md"
        canonical_skill_md = canonical_skills / skill_name / "SKILL.md"
        assert kimi_skill_md.is_file(), f"Missing .kimi/skills/{skill_name}/SKILL.md"
        assert kimi_skill_md.read_text(encoding="utf-8") == canonical_skill_md.read_text(
            encoding="utf-8"
        )


def test_init_project_kimi_agents_md_symlinks_to_project_root(tmp_path: Path) -> None:
    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_dir = tmp_path / "demo-app"
    root_agents_md = project_dir / "AGENTS.md"
    kimi_agents_md = project_dir / ".kimi" / "AGENTS.md"

    assert root_agents_md.is_file(), "Root AGENTS.md should exist"
    assert kimi_agents_md.is_symlink(), ".kimi/AGENTS.md must be a symlink"
    assert kimi_agents_md.resolve() == root_agents_md.resolve()
    assert kimi_agents_md.read_text(encoding="utf-8") == root_agents_md.read_text(encoding="utf-8")


def test_init_project_kimi_main_agent_yaml(tmp_path: Path) -> None:
    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_dir = tmp_path / "demo-app"
    main_agent = project_dir / ".kimi" / "agent.yaml"

    assert main_agent.is_file(), "Missing .kimi/agent.yaml"
    assert not main_agent.is_symlink()
    content = main_agent.read_text(encoding="utf-8")

    # Structural assertions — we don't lock an exact YAML byte-for-byte layout
    # so later formatting tweaks don't break tests.
    assert "version: 1" in content
    assert "extend: default" in content, "Main agent must inherit default tool policy"
    assert "name: theking-main" in content or "name: demo-app-main" in content, (
        "Main agent must have a deterministic name"
    )
    assert "subagents:" in content
    for role in KIMI_SUBAGENT_ROLES:
        assert f"{role}:" in content, f"Main agent missing subagent entry for {role}"
        # Each subagent entry must point at a separate YAML file under .kimi/agents/.
        assert f"./agents/{role}.yaml" in content, (
            f"Main agent subagent {role} must point to ./agents/{role}.yaml"
        )


def test_init_project_kimi_subagent_yaml_files(tmp_path: Path) -> None:
    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_dir = tmp_path / "demo-app"
    kimi_agents_dir = project_dir / ".kimi" / "agents"

    assert kimi_agents_dir.is_dir()
    assert not kimi_agents_dir.is_symlink()

    for role in KIMI_SUBAGENT_ROLES:
        subagent_yaml = kimi_agents_dir / f"{role}.yaml"
        assert subagent_yaml.is_file(), f"Missing .kimi/agents/{role}.yaml"
        content = subagent_yaml.read_text(encoding="utf-8")

        assert "version: 1" in content
        assert f"name: {role}" in content
        # Each subagent extends the main agent so tool policy stays uniform.
        assert "extend: ../agent.yaml" in content, (
            f"{role}.yaml must extend the main agent at ../agent.yaml"
        )
        # The canonical prompt body lives in .theking/agents/<role>.md; Kimi's
        # system_prompt_path is resolved relative to the agent YAML file, so
        # we point back to the canonical md.
        assert (
            f"system_prompt_path: ../../.theking/agents/{role}.md" in content
        ), f"{role}.yaml must point system_prompt_path at the canonical md"


def test_init_project_kimi_subagent_prompt_path_resolves(tmp_path: Path) -> None:
    """The system_prompt_path stored in .kimi/agents/<role>.yaml must point at
    an existing canonical md file so Kimi can actually load it."""
    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_dir = tmp_path / "demo-app"
    kimi_agents_dir = project_dir / ".kimi" / "agents"

    for role in KIMI_SUBAGENT_ROLES:
        subagent_yaml = kimi_agents_dir / f"{role}.yaml"
        assert subagent_yaml.is_file(), f"Missing .kimi/agents/{role}.yaml"
        resolved_prompt = (subagent_yaml.parent / f"../../.theking/agents/{role}.md").resolve()
        assert resolved_prompt.is_file(), (
            f"system_prompt_path for {role}.yaml resolves to missing file: {resolved_prompt}"
        )
        canonical_md = (project_dir / ".theking" / "agents" / f"{role}.md").resolve()
        assert resolved_prompt == canonical_md


def test_init_project_kimi_preserves_existing_agent_yaml(tmp_path: Path) -> None:
    """User customizations to .kimi/agent.yaml or .kimi/agents/*.yaml must
    survive re-running init-project (idempotent, non-destructive)."""
    project_dir = tmp_path / "demo-app"
    kimi_dir = project_dir / ".kimi"
    kimi_agents_dir = kimi_dir / "agents"
    kimi_agents_dir.mkdir(parents=True)

    custom_main = "# custom main agent\nversion: 1\nagent:\n  name: my-own\n"
    custom_planner = "# custom planner\nversion: 1\nagent:\n  name: my-planner\n"
    (kimi_dir / "agent.yaml").write_text(custom_main, encoding="utf-8")
    (kimi_agents_dir / "planner.yaml").write_text(custom_planner, encoding="utf-8")

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert (kimi_dir / "agent.yaml").read_text(encoding="utf-8") == custom_main
    assert (kimi_agents_dir / "planner.yaml").read_text(encoding="utf-8") == custom_planner
    # Other subagents are still generated.
    for role in KIMI_SUBAGENT_ROLES:
        if role == "planner":
            continue
        assert (kimi_agents_dir / f"{role}.yaml").is_file(), (
            f"Non-custom subagent {role}.yaml should have been created"
        )


def test_ensure_generates_kimi_runtime_on_fresh_project(tmp_path: Path) -> None:
    result = run_cli(
        ["ensure", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_dir = tmp_path / "demo-app"
    assert (project_dir / ".kimi" / "agent.yaml").is_file()
    assert (project_dir / ".kimi" / "AGENTS.md").is_symlink()
    assert_runtime_symlink(project_dir / ".kimi" / "skills", project_dir / ".theking" / "skills")
    for role in KIMI_SUBAGENT_ROLES:
        assert (project_dir / ".kimi" / "agents" / f"{role}.yaml").is_file()


def test_kimi_generated_yaml_is_parseable(tmp_path: Path) -> None:
    """Guard against string-concatenation bugs that produce invalid YAML. A
    real ``yaml.safe_load`` round-trip is the cheapest way to catch indentation
    and escaping mistakes before they break `kimi --agent-file`."""
    yaml = pytest.importorskip("yaml")

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    project_dir = tmp_path / "demo-app"
    kimi_dir = project_dir / ".kimi"

    main_agent_text = (kimi_dir / "agent.yaml").read_text(encoding="utf-8")
    main_agent_doc = yaml.safe_load(main_agent_text)
    assert isinstance(main_agent_doc, dict)
    assert main_agent_doc.get("version") == 1
    agent_cfg = main_agent_doc.get("agent")
    assert isinstance(agent_cfg, dict)
    assert agent_cfg.get("extend") == "default"
    subagents = agent_cfg.get("subagents")
    assert isinstance(subagents, dict)
    for role in KIMI_SUBAGENT_ROLES:
        entry = subagents.get(role)
        assert isinstance(entry, dict), f"Main agent subagent `{role}` not a mapping"
        assert entry.get("path") == f"./agents/{role}.yaml"
        assert isinstance(entry.get("description"), str)

    for role in KIMI_SUBAGENT_ROLES:
        subagent_text = (kimi_dir / "agents" / f"{role}.yaml").read_text(encoding="utf-8")
        subagent_doc = yaml.safe_load(subagent_text)
        assert isinstance(subagent_doc, dict)
        assert subagent_doc.get("version") == 1
        sub_cfg = subagent_doc.get("agent")
        assert isinstance(sub_cfg, dict)
        assert sub_cfg.get("extend") == "../agent.yaml"
        assert sub_cfg.get("name") == role
        assert sub_cfg.get("system_prompt_path") == f"../../.theking/agents/{role}.md"


def test_kimi_tool_mapping_drops_unknown_and_dedupes() -> None:
    """The tool mapper must silently drop unknown Claude tools and deduplicate
    when multiple Claude aliases map to the same Kimi tool. If it didn't,
    subagent YAML would either contain `None` entries or duplicate tool
    registrations — both reject by Kimi."""
    import importlib

    scaffold = importlib.import_module("theking.scaffold")

    result = scaffold.map_claude_tools_to_kimi(
        ["Read", "ReadFile", "TotallyMadeUpTool", "Grep", "Read"]
    )
    assert result == [
        "kimi_cli.tools.file:ReadFile",
        "kimi_cli.tools.file:Grep",
    ], "Unknown tool must be dropped; duplicates must collapse"


def test_kimi_subagent_yaml_escapes_quotes_in_description() -> None:
    """A canonical agent whose description contains double quotes must emit
    valid double-quoted YAML (Kimi would reject unescaped inner quotes)."""
    import importlib

    scaffold = importlib.import_module("theking.scaffold")
    yaml = pytest.importorskip("yaml")

    md = (
        '---\n'
        'name: test-role\n'
        'description: "He said \\"hello\\" to the crowd."\n'
        'tools: Read, Grep\n'
        '---\n'
        'Body content\n'
    )
    generated = scaffold.build_kimi_subagent_yaml(
        role="test-role", canonical_md_text=md
    )
    parsed = yaml.safe_load(generated)
    assert isinstance(parsed, dict)
    assert isinstance(parsed["agent"]["description"], str)


def test_kimi_subagent_roles_match_canonical_agent_definitions() -> None:
    """Guard against drift: every canonical agent role must also be exposed as
    a Kimi subagent. Otherwise adding a new role would silently leave Kimi
    users without access to it."""
    # Import from the installed theking package (so this test reflects what
    # `workflowctl` actually ships).
    import importlib

    constants = importlib.import_module("theking.constants")
    canonical_roles = {name.removesuffix(".md") for name, _tmpl in constants.AGENT_DEFINITIONS}
    kimi_roles = set(constants.KIMI_SUBAGENT_ROLES)
    assert canonical_roles == kimi_roles, (
        "KIMI_SUBAGENT_ROLES drifted from AGENT_DEFINITIONS. "
        f"Only in canonical: {canonical_roles - kimi_roles}. "
        f"Only in kimi: {kimi_roles - canonical_roles}."
    )


# --- .gitignore scaffold (TASK-003 kimi-feedback sprint) ---


def test_init_project_writes_root_gitignore_with_theking_defaults(tmp_path: Path) -> None:
    """init-project creates a project-root .gitignore with sensible defaults.

    Every project scaffolded by theking should ship with a .gitignore that keeps
    theking state/backup artifacts and AI session ephemera out of git; the
    Kimi CLI feedback confirmed this is a 100% miss on greenfield projects
    otherwise.
    """
    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr

    gitignore = tmp_path / "demo-app" / ".gitignore"
    assert gitignore.is_file(), "project root must have a .gitignore after init-project"
    content = gitignore.read_text(encoding="utf-8")
    for entry in (".theking/state/", "plan.json", ".env", ".DS_Store"):
        assert entry in content, (
            f"default .gitignore must contain '{entry}' — it's a 100% common miss"
        )


def test_init_project_preserves_existing_gitignore(tmp_path: Path) -> None:
    """If the user already wrote a .gitignore, ensure/init-project must not overwrite it.

    write_if_missing semantics: users own .gitignore, theking only seeds it.
    """
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir()
    custom = "# user-authored gitignore\nmy-custom-dir/\n"
    (project_dir / ".gitignore").write_text(custom, encoding="utf-8")

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr

    preserved = (project_dir / ".gitignore").read_text(encoding="utf-8")
    assert preserved == custom, "existing .gitignore must not be overwritten by theking"
