"""Doc-schema pin for orca-workflows/models/agy.md's agent-e2e configuration note
(issue #140). Before this change, the note hardcoded "an accessibility-tree Playwright MCP"
as the only tool agy configures for agent-e2e. Generalized to reference the project-declared
tool orca-evaluate/§2 resolves from docs/agents/e2e-tooling.md, which is not necessarily an
MCP server at all (e.g. a raw CLI like Maestro or adb).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGY_MD = REPO_ROOT / "orca-workflows" / "models" / "agy.md"


def test_agent_e2e_note_no_longer_hardcodes_playwright():
    text = AGY_MD.read_text()
    assert "an accessibility-tree Playwright MCP" not in text


def test_agent_e2e_note_references_project_declared_tool():
    text = AGY_MD.read_text()
    assert "project-declared" in text


def test_agent_e2e_note_still_requires_smoke_test_before_relying_on_it():
    # Regression guard -- the smoke-test-before-relying-on-it requirement predates this issue
    # and must survive the wording generalization.
    text = AGY_MD.read_text()
    assert "smoke-test" in text
