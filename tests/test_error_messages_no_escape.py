from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.constants import WorkflowError
from scripts.validation import validate_reviewer_declaration


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
TEMPLATES_DIR = REPO_ROOT / "templates"

FORBIDDEN_MESSAGE_SNIPPETS = (
    "or switch",
    "switch this task to lightweight",
    "flow by setting",
    "raise independence",
    "main-agent-fallback",
    "legacy fallback",
    "fallback review",
)

FORBIDDEN_TEMPLATE_SNIPPETS = (
    "or switch",
    "switch this task to lightweight",
    "raise independence",
)


def _literal_text(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(_literal_text(value) for value in node.values)
    if isinstance(node, ast.FormattedValue):
        return ""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_text(node.left) + _literal_text(node.right)
    return ""


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _workflow_error_and_print_messages(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    messages: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            if _call_name(node.exc.func) == "WorkflowError":
                message = " ".join(_literal_text(arg) for arg in node.exc.args).strip()
                if message:
                    messages.append((node.lineno, message))
        if isinstance(node, ast.Call) and _call_name(node.func) == "print":
            message = " ".join(_literal_text(arg) for arg in node.args).strip()
            if message:
                messages.append((node.lineno, message))
    return messages


def test_workflow_errors_and_prints_do_not_hint_escape_hatches() -> None:
    offenders: list[str] = []
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        for line_number, message in _workflow_error_and_print_messages(path):
            lowered = message.lower()
            for snippet in FORBIDDEN_MESSAGE_SNIPPETS:
                if snippet in lowered:
                    rel = path.relative_to(REPO_ROOT)
                    offenders.append(f"{rel}:{line_number}: contains {snippet!r}: {message}")

    assert not offenders, "Escape-hatch wording found:\n" + "\n".join(offenders)


def test_workflow_templates_do_not_hint_escape_hatches() -> None:
    offenders: list[str] = []
    for path in sorted(TEMPLATES_DIR.rglob("*")):
        if not path.is_file() or path.suffix in {".pyc", ".pyo"}:
            continue
        text = path.read_text(encoding="utf-8").lower()
        for snippet in FORBIDDEN_TEMPLATE_SNIPPETS:
            if snippet in text:
                rel = path.relative_to(REPO_ROOT)
                offenders.append(f"{rel}: contains {snippet!r}")

    assert not offenders, "Escape-hatch wording found:\n" + "\n".join(offenders)


@pytest.mark.parametrize(
    "review_body",
    [
        "# Review\n\n## Context\n- Reviewer: main\n\n## Findings\n- x\n",
        "# Review\n\n## Context\n- Reviewer: main\n- Reviewer independence: bogus\n\n## Findings\n- x\n",
        "# Review\n\n## Context\n- Reviewer: main\n- Reviewer independence: main-agent-fallback\n\n## Findings\n- x\n",
    ],
)
def test_reviewer_declaration_errors_do_not_hint_escape_hatches(
    tmp_path: Path,
    review_body: str,
) -> None:
    review_md = tmp_path / "code-review-round-001.md"
    review_md.write_text(review_body, encoding="utf-8")

    with pytest.raises(WorkflowError) as excinfo:
        validate_reviewer_declaration(review_md)

    message = str(excinfo.value).lower()
    for snippet in FORBIDDEN_MESSAGE_SNIPPETS:
        assert snippet not in message