"""Regression coverage for issue #152 -- a 2026-08-12 repo-wide audit against
docs/references/anthropic-building-skills-for-claude.pdf p10's "Field requirements" found
`lifecycle-gate-policy`'s frontmatter `description` at 1093 characters, over the documented
1024-character cap; the other 10 skills in the repo were all within range (434-875 chars).

This guards the fix (trimmed to under 1024, same what/when/excludes content) and also pins the
cap itself across every skill in the repo, so a future skill or edit that grows past 1024 chars
fails here instead of waiting for the next manual PDF-checklist audit.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
DESCRIPTION_CAP = 1024


def _skill_dirs() -> list[Path]:
    return sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir() and (p / "SKILL.md").exists())


def _frontmatter(skill_md: Path) -> dict:
    text = skill_md.read_text()
    _, fm, _ = text.split("---", 2)
    return yaml.safe_load(fm)


def test_lifecycle_gate_policy_description_under_cap():
    fm = _frontmatter(SKILLS_DIR / "lifecycle-gate-policy" / "SKILL.md")
    assert len(fm["description"]) <= DESCRIPTION_CAP


def test_all_skill_descriptions_under_cap():
    over = {
        p.name: len(_frontmatter(p / "SKILL.md")["description"])
        for p in _skill_dirs()
        if len(_frontmatter(p / "SKILL.md")["description"]) > DESCRIPTION_CAP
    }
    assert over == {}, f"skills over the {DESCRIPTION_CAP}-char description cap: {over}"
