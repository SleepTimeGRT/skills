"""Structural validation for the orca-workflow/orca-task-runner/orca-evaluate
skill family. These are prose/instruction files, not executable code, so the
checks validate structure (frontmatter, cross-references, stale-term absence)
rather than runtime behavior.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
WORKFLOWS_DIR = REPO_ROOT / "orca-workflows"

NEW_SKILLS = ["orca-workflow", "orca-task-runner", "orca-evaluate"]
RETIRED_SKILLS = ["orca-review-gate", "orca-sdd"]
STALE_TERMS = [
    "orca-review-gate",
    "orca-sdd",
    "evaluator에서 제외",
    "cross-model 리뷰 게이트",
]
WORKFLOWS_DOCS = [
    "model-selection.md",
    "models/claude-code.md",
    "models/codex.md",
    "models/agy.md",
]


def _read_skill(name: str) -> str:
    path = SKILLS_DIR / name / "SKILL.md"
    assert path.is_file(), f"{name}/SKILL.md missing"
    return path.read_text()


def _frontmatter(text: str) -> str:
    assert text.startswith("---\n"), "missing YAML frontmatter"
    return text.split("---\n", 2)[1]


@pytest.mark.parametrize("name", NEW_SKILLS)
def test_skill_directory_exists(name):
    assert (SKILLS_DIR / name / "SKILL.md").is_file(), f"{name}/SKILL.md missing"


@pytest.mark.parametrize("name", NEW_SKILLS)
def test_frontmatter_has_name_and_description(name):
    text = _read_skill(name)
    fm = _frontmatter(text)
    assert re.search(rf"^name:\s*{re.escape(name)}\s*$", fm, re.M), (
        f"{name}: frontmatter 'name' must equal directory name"
    )
    desc = re.search(r"^description:\s*(.+)$", fm, re.M)
    assert desc and len(desc.group(1)) > 40, (
        f"{name}: 'description' missing or too short to carry real trigger info"
    )


@pytest.mark.parametrize("name", RETIRED_SKILLS)
def test_retired_skill_removed(name):
    assert not (SKILLS_DIR / name).exists(), (
        f"{name} must be deleted from skills/, not left alongside its replacement"
    )


@pytest.mark.parametrize("name", NEW_SKILLS)
def test_no_stale_terms_in_body(name):
    text = _read_skill(name)
    for term in STALE_TERMS:
        assert term not in text, f"{name}: stale reference '{term}' should be gone"


def test_delegation_references():
    task_runner = _read_skill("orca-task-runner")
    workflow = _read_skill("orca-workflow")
    assert "orca-evaluate" in task_runner, (
        "orca-task-runner must hand off evaluation to orca-evaluate, not embed it"
    )
    assert "orca-task-runner" in workflow and "orca-evaluate" in workflow, (
        "orca-workflow must route to both orca-task-runner and orca-evaluate"
    )


def test_orca_evaluate_has_verdict_vocabulary():
    text = _read_skill("orca-evaluate")
    for term in ("PASS", "FAIL", "ESCALATE"):
        assert re.search(rf"\b{term}\b", text), f"orca-evaluate must define the '{term}' verdict"


def test_orca_workflow_never_generates_or_evaluates_itself():
    text = _read_skill("orca-workflow")
    assert "생성하지도, 평가하지도 않는다" in text, (
        "orca-workflow must explicitly state it never generates or evaluates directly"
    )


@pytest.mark.parametrize("doc", WORKFLOWS_DOCS)
def test_workflows_docs_reference_new_skill_names(doc):
    text = (WORKFLOWS_DIR / doc).read_text()
    for term in RETIRED_SKILLS:
        assert term not in text, f"{doc}: stale reference '{term}'"
    assert any(name in text for name in NEW_SKILLS), (
        f"{doc}: should reference at least one of {NEW_SKILLS} after the migration"
    )


def test_orca_task_runner_declares_destructive_ops_field():
    text = _read_skill("orca-task-runner")
    assert "의도된 destructive 오퍼레이션" in text, (
        "orca-task-runner's proposal format must require a declared destructive-ops field"
    )


def test_orca_evaluate_has_migration_escalate_condition():
    text = _read_skill("orca-evaluate")
    assert "destructive-op 린터가 flag" in text and "선언에 커버되지 않는다" in text, (
        "orca-evaluate §4 must add the migration destructive-op ESCALATE condition"
    )
