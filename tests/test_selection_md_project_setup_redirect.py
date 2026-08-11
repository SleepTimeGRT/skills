"""Doc-schema pin for orca-workflows/issue-trackers/selection.md's onboarding redirect
(issue #140 design spec §2/§3). Before this change, the onboarding trigger pointed at
`skills/orca-workflow/SKILL.md` §0's inline onboarding subflow, which this issue moves into
the new project-setup skill. selection.md must now be self-contained: it names
`/project-setup` directly instead of pointing at orca-workflow's (now-removed) inline logic.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SELECTION_MD = REPO_ROOT / "orca-workflows" / "issue-trackers" / "selection.md"


def test_onboarding_trigger_redirects_to_project_setup():
    text = SELECTION_MD.read_text()
    start = text.index("PROJECT-숫자")
    end = text.index("cloudId 같은 값은 추측으로 채울 수 없다")
    window = text[start:end]
    assert "/project-setup" in window


def test_onboarding_trigger_no_longer_points_at_orca_workflow_inline_subflow():
    text = SELECTION_MD.read_text()
    start = text.index("PROJECT-숫자")
    end = text.index("cloudId 같은 값은 추측으로 채울 수 없다")
    window = text[start:end]
    assert "orca-workflow/SKILL.md` §0의 온보딩 서브플로우" not in window


def test_numeric_id_github_default_path_unchanged():
    # Regression guard (design spec explicit call-out): the numeric-ID -> GitHub-default path
    # must still work with no tracker doc present -- this task must not touch it.
    text = SELECTION_MD.read_text()
    assert "순수 숫자(`123`) → GitHub Issues 기본값(현재 동작과 동일). 아래 3의 `github.md`로." in text
