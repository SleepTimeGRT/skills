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
PROVIDER_REFERENCES = {
    "models/claude-code.md": "../references/models/claude-code.md",
    "models/codex.md": "../references/models/codex.md",
    "models/agy.md": "../references/models/agy.md",
}


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
def test_workflows_docs_do_not_reference_retired_skill_names(doc):
    text = (WORKFLOWS_DIR / doc).read_text()
    for term in RETIRED_SKILLS:
        assert term not in text, f"{doc}: stale reference '{term}'"


def test_model_selection_references_current_workflow_skills():
    text = (WORKFLOWS_DIR / "model-selection.md").read_text()
    for name in NEW_SKILLS:
        assert name in text, (
            f"model-selection.md: workflow entry point should reference {name}"
        )


@pytest.mark.parametrize(("doc", "reference"), PROVIDER_REFERENCES.items())
def test_provider_docs_link_their_evidence_reference(doc, reference):
    text = (WORKFLOWS_DIR / doc).read_text()
    assert f"]({reference})" in text, (
        f"{doc}: should link its provider evidence at {reference}"
    )
    assert (WORKFLOWS_DIR / "models" / reference).resolve().is_file(), (
        f"{doc}: evidence link target does not exist: {reference}"
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


ISSUE_TRACKERS_DIR = REPO_ROOT / "orca-workflows" / "issue-trackers"
TRACKER_ADAPTER_FILES = ["github.md", "jira.md"]
TRACKER_ALL_FILES = ["selection.md", "github.md", "jira.md"]
TRACKER_OPERATIONS = [
    "get_issue",
    "get_issue_type",
    "list_children",
    "get_child_order",
    "is_open",
    "close_issue",
    "link_pr_for_close",
]
VPROP_SPECIFIC_LEAKS = ["VP-", "voyagerx", "fb59360c"]


@pytest.mark.parametrize("filename", TRACKER_ALL_FILES)
def test_issue_tracker_file_exists(filename):
    assert (ISSUE_TRACKERS_DIR / filename).is_file(), (
        f"orca-workflows/issue-trackers/{filename} missing"
    )


@pytest.mark.parametrize("filename", TRACKER_ADAPTER_FILES)
def test_issue_tracker_adapter_defines_all_operations(filename):
    text = (ISSUE_TRACKERS_DIR / filename).read_text()
    for op in TRACKER_OPERATIONS:
        assert f"`{op}(" in text, f"{filename}: must define operation '{op}'"


@pytest.mark.parametrize("term", VPROP_SPECIFIC_LEAKS)
def test_jira_adapter_has_no_vprop_specific_values(term):
    text = (ISSUE_TRACKERS_DIR / "jira.md").read_text()
    assert term not in text, (
        f"jira.md must stay repo-agnostic — found vprop-specific value '{term}'"
    )


def test_jira_adapter_uses_structural_fields():
    text = (ISSUE_TRACKERS_DIR / "jira.md").read_text()
    for field in ("hierarchyLevel", "parent", "statusCategory", "getTransitionsForJiraIssue"):
        assert field in text, f"jira.md must use the structural field/tool '{field}'"


def test_github_adapter_uses_gh_cli():
    text = (ISSUE_TRACKERS_DIR / "github.md").read_text()
    for call in ("gh issue view", "gh issue list", "gh issue close"):
        assert call in text, f"github.md must define '{call}'"


def test_github_adapter_prefers_native_sub_issues_and_exact_close_match():
    text = (ISSUE_TRACKERS_DIR / "github.md").read_text()
    assert "sub_issues" in text, "github.md must query GitHub's native sub-issues API"
    assert re.search(
        r"Refs #N.*?의존 edge로 취급하지 않는다",
        text,
        re.S,
    ), "github.md must explicitly exclude informational refs from dependency edges"
    assert "([^0-9]|$)" in text, (
        "github.md closing-keyword check must not match #12 inside #123"
    )


def test_selection_doc_defines_backend_choice_and_onboarding_trigger():
    text = (ISSUE_TRACKERS_DIR / "selection.md").read_text()
    assert "Issue tracker" in text, (
        "selection.md must describe the AGENTS.md/CLAUDE.md pointer lookup"
    )
    assert "온보딩" in text, (
        "selection.md must reference the onboarding trigger for undocumented repos"
    )


def test_linear_adapter_requires_selection_disambiguation():
    text = (ISSUE_TRACKERS_DIR / "selection.md").read_text()
    assert "Jira와 Linear" in text and "식별자" in text, (
        "selection.md must disambiguate Jira and Linear project-style identifiers"
    )
    assert "변경은 필요 없다" not in text, (
        "selection.md must not claim a Linear adapter is sufficient by itself"
    )


def test_jira_adapter_is_runtime_portable():
    text = (ISSUE_TRACKERS_DIR / "jira.md").read_text()
    assert "mcp__claude_ai_Atlassian" not in text, (
        "jira.md must not pin the adapter to Claude's MCP namespace"
    )
    for capability in (
        r"issue\s+조회",
        r"JQL\s+검색",
        r"transition\s+목록",
        r"상태\s+전환",
        r"comment\s+추가",
    ):
        assert re.search(capability, text), (
            f"jira.md must name the Atlassian capability matching {capability!r}"
        )


def test_spawn_failure_log_uses_json_encoder():
    text = (WORKFLOWS_DIR / "spawn-failures.md").read_text()
    assert "jq -cn" in text, "spawn-failures.md must encode JSONL with jq"
    assert "printf '{\"ts\"" not in text, (
        "spawn-failures.md must not interpolate unescaped values into JSON"
    )


def test_orca_workflow_no_hardcoded_gh_issue_calls():
    text = _read_skill("orca-workflow")
    for term in ("gh issue view", "gh issue list", "gh issue close"):
        assert term not in text, (
            f"orca-workflow must not call '{term}' directly — route through the issue-tracker adapter"
        )
    assert "gh pr" in text, (
        "orca-workflow must keep gh pr calls — code hosting stays GitHub-specific"
    )


def test_orca_workflow_references_issue_tracker_selection():
    text = _read_skill("orca-workflow")
    assert "issue-trackers/selection.md" in text, (
        "orca-workflow §0 must resolve the backend via issue-trackers/selection.md"
    )


def test_orca_workflow_has_onboarding_subflow():
    text = _read_skill("orca-workflow")
    assert "온보딩" in text, (
        "orca-workflow §0 must define the onboarding subflow for undocumented repos"
    )


def test_orca_workflow_uses_abstract_tracker_operations():
    text = _read_skill("orca-workflow")
    for op in ("get_issue", "list_children", "get_child_order", "is_open", "close_issue"):
        assert op in text, f"orca-workflow must route issue-tracker access through '{op}'"


@pytest.mark.parametrize("name", NEW_SKILLS)
def test_no_hardcoded_acceptance_criteria_heading(name):
    text = _read_skill(name)
    assert "## Acceptance criteria" not in text, (
        f"{name}: acceptance-criteria heading must come from the resolved tracker marker, "
        "not a hardcoded GitHub heading"
    )
    assert "## What to build" not in text, (
        f"{name}: 'what to build' heading must not be hardcoded either"
    )
