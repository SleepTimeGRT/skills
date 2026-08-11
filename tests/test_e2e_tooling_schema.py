"""Doc-schema pin for docs/agents/e2e-tooling.md (issue #140 design spec §1) -- the four
section headings this file must carry so orca-evaluate/§2 and project-setup/§2 can rely on a
stable shape when reading or writing an instance of this file in any repo.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
E2E_TOOLING_MD = REPO_ROOT / "docs" / "agents" / "e2e-tooling.md"


def test_e2e_tooling_doc_exists():
    assert E2E_TOOLING_MD.is_file()


def test_e2e_tooling_doc_has_all_four_sections_in_order():
    text = E2E_TOOLING_MD.read_text()
    headings = ["## Platform", "## Tool", "## Usage guidance", "## Precondition"]
    positions = [text.index(h) for h in headings]
    assert positions == sorted(positions), (
        "sections must appear in the order Platform, Tool, Usage guidance, Precondition"
    )


def test_e2e_tooling_doc_declares_playwright_for_this_repo():
    text = E2E_TOOLING_MD.read_text()
    platform_start = text.index("## Platform")
    tool_start = text.index("## Tool")
    platform_section = text[platform_start:tool_start]
    assert "web" in platform_section
    usage_start = text.index("## Usage guidance")
    tool_section = text[tool_start:usage_start]
    assert "Playwright MCP" in tool_section
