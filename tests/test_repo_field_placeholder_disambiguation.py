"""Doc-schema regression coverage for issue #164 (studio-hevv/selah-android #16, #23 realized).

`orca-workflow-epic` §3's task-coordinator spec_text template had a bare "대상 repo" placeholder
with no indication of whether it meant the canonical repo identifier string (the value every
`logging.md` §1 `repo` field must carry, per issue #158) or the local worktree absolute path
(used elsewhere for project-slug computation, per issue #159). At runtime the coordinator filled it
with the worktree path, and the spawned `orca-workflow-task` instance then derived a basename from
that path for its own `log_dispatch`/`log_outcome` calls -- producing a second, divergent `repo`
string for the same repository ("selah_android" vs "studio-hevv/selah-android") that silently
dropped those events from `orca-retro`'s (repo, issue) composite-key filter (the same failure shape
issue #158 fixed, reintroduced through a different placeholder).

Fix: disambiguate the placeholder at the source (`orca-workflow-epic` §3) and add a second line of
defense in `orca-workflow-task` §0 instructing it never to derive/reshape a received repo value.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EPIC_SKILL = REPO_ROOT / "skills" / "orca-workflow-epic" / "SKILL.md"
TASK_SKILL = REPO_ROOT / "skills" / "orca-workflow-task" / "SKILL.md"


def _epic_spec_text_line() -> str:
    text = EPIC_SKILL.read_text()
    start = text.index('spec_text="<orca-workflow-task SKILL.md 지침')
    end = text.index("\n", start)
    return text[start:end]


def test_epic_spec_text_disambiguates_repo_placeholder_from_worktree_path():
    line = _epic_spec_text_line()
    assert "대상 repo(정본 식별자 문자열" in line
    assert "owner/name" in line
    assert "worktree 절대경로가 아니다" in line
    assert "issue #164" in line
    # if a worktree path is genuinely needed by the spawned coordinator, it must be a distinct
    # placeholder, not folded back into the same "대상 repo" token.
    assert "분리된 별개 항목" in line


def test_epic_spec_text_still_has_exactly_one_repo_placeholder_occurrence():
    # Guards against the fix accidentally duplicating "대상 repo" into two competing mentions inside
    # the same spec_text line (which would just relocate the ambiguity).
    line = _epic_spec_text_line()
    assert line.count("대상 repo(") == 1


def _task_repo_defense_bullet() -> str:
    text = TASK_SKILL.read_text()
    start = text.index("**'대상 repo' 값은 무가공 전달(issue #164)**")
    end = text.index("\n- ", start)
    return text[start:end]


def test_task_skill_documents_no_derivation_defense_for_received_repo_value():
    bullet = _task_repo_defense_bullet()
    assert "issue #164" in bullet
    assert "정본 식별자 문자열" in bullet
    assert "basename" in bullet
    assert "logging.md" in bullet
    assert "orca-retro" in bullet


def test_task_skill_defense_bullet_lives_in_section_0_premise_list():
    text = TASK_SKILL.read_text()
    section_0_start = text.index("## 0. 전제")
    section_1_start = text.index("\n## 1.", section_0_start)
    bullet_idx = text.index("**'대상 repo' 값은 무가공 전달(issue #164)**")
    assert section_0_start < bullet_idx < section_1_start
