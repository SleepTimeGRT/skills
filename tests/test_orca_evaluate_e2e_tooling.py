"""Doc-schema pin for skills/orca-evaluate/SKILL.md's agent-e2e tooling generalization
(issue #140). Before this change, §2's spawn command hardcoded the literal string
"Playwright MCP 지침" into the agy -p launch string, and the fallback (old L194) hardcoded
"Playwright MCP를 붙인 headless agy". This made agent-e2e unusable for native-mobile projects
(studio-hevv/selah-android in the issue's real-world evidence). The fix reads
docs/agents/e2e-tooling.md at spawn time and splices its declared tool into the launch string,
with an ESCALATE-and-redirect-to-/project-setup path when the doc is missing, and a
strengthened self-recheck that catches silent tool substitution (the issue's exact observed
failure: Playwright declared, raw adb used instead).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALUATE_SKILL = REPO_ROOT / "skills" / "orca-evaluate" / "SKILL.md"


def _section(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


def test_section_2_no_longer_hardcodes_playwright_literal_in_spawn_command():
    text = EVALUATE_SKILL.read_text()
    section2 = _section(text, "## 2. Test Gate", "## 3. Diff")
    assert "Playwright MCP 지침" not in section2


def test_section_2_reads_e2e_tooling_doc_before_spawn():
    text = EVALUATE_SKILL.read_text()
    section2 = _section(text, "## 2. Test Gate", "## 3. Diff")
    assert "docs/agents/e2e-tooling.md" in section2


def test_section_2_splices_tool_and_usage_guidance_into_launch_string():
    text = EVALUATE_SKILL.read_text()
    section2 = _section(text, "## 2. Test Gate", "## 3. Diff")
    assert "Tool" in section2 and "Usage guidance" in section2


def test_section_2_missing_doc_redirects_to_project_setup():
    text = EVALUATE_SKILL.read_text()
    section2 = _section(text, "## 2. Test Gate", "## 3. Diff")
    assert "/project-setup" in section2


def test_self_recheck_paragraph_checks_declared_tool_actually_used():
    text = EVALUATE_SKILL.read_text()
    section2 = _section(text, "## 2. Test Gate", "## 3. Diff")
    assert "Tool" in section2
    assert "우회" in section2 or "대체" in section2


def test_escalate_bucket_covers_missing_e2e_tooling_doc():
    text = EVALUATE_SKILL.read_text()
    section4 = text[text.index("## 4."):]
    assert "e2e-tooling" in section4 or "e2e-tooling.md" in section4


def test_fallback_no_longer_hardcodes_playwright():
    text = EVALUATE_SKILL.read_text()
    fallback = text[text.index("## 폴백"):]
    assert "Playwright MCP를 붙인 headless agy" not in fallback
    assert "docs/agents/e2e-tooling.md" in fallback
