"""Doc-schema pin for skills/orca-workflow/SKILL.md §0's onboarding removal + e2e-tooling gate
(issue #140). Before this change, §0 carried its own inline tracker-onboarding paragraph
(now redundant with orca-workflows/issue-trackers/selection.md's redirect, see
tests/test_selection_md_project_setup_redirect.py, and with the new project-setup skill, see
tests/test_project_setup_schema.py) and had no e2e-tooling existence check at all -- §1 routing
ran unconditionally even when docs/agents/e2e-tooling.md was absent, which is the root cause
of issue #140 (agent-e2e always hardcoded to Playwright with no per-project override).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ORCA_WORKFLOW_SKILL = REPO_ROOT / "skills" / "orca-workflow" / "SKILL.md"


def test_section_0_no_longer_has_inline_onboarding_paragraph():
    text = ORCA_WORKFLOW_SKILL.read_text()
    section0 = text[text.index("## 0."):text.index("## 1.")]
    assert "①어떤 tracker를 쓰는지" not in section0


def test_section_0_has_e2e_tooling_gate_before_routing():
    text = ORCA_WORKFLOW_SKILL.read_text()
    section0 = text[text.index("## 0."):text.index("## 1.")]
    assert "docs/agents/e2e-tooling.md" in section0
    assert "/project-setup" in section0


def test_e2e_tooling_gate_precedes_section_1_in_document_order():
    text = ORCA_WORKFLOW_SKILL.read_text()
    gate_pos = text.index("docs/agents/e2e-tooling.md")
    section1_pos = text.index("## 1.")
    assert gate_pos < section1_pos


def test_stuck_dispatched_sweep_bullet_still_present():
    # Regression guard -- this task only removes the onboarding bullet and adds the
    # e2e-tooling gate; the unrelated stale-dispatched-sweep bullet must survive untouched.
    text = ORCA_WORKFLOW_SKILL.read_text()
    section0 = text[text.index("## 0."):text.index("## 1.")]
    assert "고착 dispatched 스윕" in section0
