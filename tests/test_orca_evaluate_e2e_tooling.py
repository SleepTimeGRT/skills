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
    # Bound tightly to the self-recheck paragraph itself (not all of section 2) so this
    # test actually pins the new "**구체 기준**" sentence rather than passing merely
    # because "Tool" appears somewhere earlier in section 2 (e.g. the opening paragraph).
    self_recheck = _section(
        text, "이 세션(evaluator)은 agy의 자기 요약을", "## 3. Diff"
    )
    assert "구체 기준" in self_recheck
    assert "selah-android" in self_recheck or "adb" in self_recheck


def test_escalate_bucket_covers_missing_e2e_tooling_doc():
    text = EVALUATE_SKILL.read_text()
    # Bound to §4 only (not §4-through-EOF) so this doesn't accidentally pass because the
    # unrelated "## 폴백" section below also mentions e2e-tooling.md.
    section4 = _section(text, "## 4.", "## 폴백")
    assert "e2e-tooling" in section4 or "e2e-tooling.md" in section4


def test_fallback_no_longer_hardcodes_playwright():
    text = EVALUATE_SKILL.read_text()
    fallback = text[text.index("## 폴백"):]
    assert "Playwright MCP를 붙인 headless agy" not in fallback
    assert "docs/agents/e2e-tooling.md" in fallback
