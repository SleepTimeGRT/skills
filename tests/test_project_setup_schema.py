"""Doc-schema pin for the new skills/project-setup/SKILL.md (issue #140 design spec §2) -- a
general-purpose, manually-invoked (`/project-setup`) onboarding skill that owns writing both
docs/agents/issue-tracker.md and docs/agents/e2e-tooling.md. This test file is built up across
two tasks: this task adds the §1 (issue tracker) assertions, Task 3 adds §2 (e2e tooling).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_SETUP_MD = REPO_ROOT / "skills" / "project-setup" / "SKILL.md"


def test_project_setup_skill_exists():
    assert PROJECT_SETUP_MD.is_file()


def test_project_setup_has_yaml_frontmatter_with_name_and_description():
    text = PROJECT_SETUP_MD.read_text()
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    frontmatter = text[4:end]
    assert "name: project-setup" in frontmatter
    assert "description:" in frontmatter


def test_project_setup_has_issue_tracker_section():
    text = PROJECT_SETUP_MD.read_text()
    assert "## 1. Issue tracker" in text


def test_issue_tracker_section_skips_when_doc_already_exists():
    text = PROJECT_SETUP_MD.read_text()
    start = text.index("## 1. Issue tracker")
    end = text.index("## 2.") if "## 2." in text else len(text)
    window = text[start:end]
    assert "docs/agents/issue-tracker.md" in window
    assert "있으면" in window and ("스킵" in window or "건너" in window)


def test_issue_tracker_section_github_default_writes_no_file():
    text = PROJECT_SETUP_MD.read_text()
    start = text.index("## 1. Issue tracker")
    end = text.index("## 2.") if "## 2." in text else len(text)
    window = text[start:end]
    assert "GitHub" in window
    # The GitHub-default path must not create a doc -- selection.md's numeric-ID fallback
    # depends on the doc's absence.
    assert "문서를 만들지 않" in window or "문서 생성 없이" in window


def test_project_setup_avoids_claude_code_specific_tool_names():
    text = PROJECT_SETUP_MD.read_text()
    assert "AskUserQuestion" not in text


def test_project_setup_has_e2e_tooling_section():
    text = PROJECT_SETUP_MD.read_text()
    assert "## 2. E2E tooling" in text


def test_e2e_tooling_section_skips_when_doc_already_exists():
    text = PROJECT_SETUP_MD.read_text()
    start = text.index("## 2. E2E tooling")
    window = text[start:]
    assert "docs/agents/e2e-tooling.md" in window
    assert "있으면" in window and ("스킵" in window or "건너" in window)


def test_e2e_tooling_section_has_no_unconditional_default():
    text = PROJECT_SETUP_MD.read_text()
    start = text.index("## 2. E2E tooling")
    window = text[start:]
    # Unlike issue-tracker's GitHub default, e2e-tooling must always ask -- no silent default.
    assert "무조건" in window


def test_e2e_tooling_section_covers_all_four_fields():
    text = PROJECT_SETUP_MD.read_text()
    start = text.index("## 2. E2E tooling")
    window = text[start:]
    for field in ["Platform", "Tool", "Usage guidance", "Precondition"]:
        assert field in window


def test_e2e_tooling_section_proposes_playwright_default_for_web():
    text = PROJECT_SETUP_MD.read_text()
    start = text.index("## 2. E2E tooling")
    window = text[start:]
    assert "Playwright" in window
