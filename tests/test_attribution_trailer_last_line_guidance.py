"""Doc-schema regression coverage for issue #137.

`orca-task-runner` SKILL.md §2 subtask spec item ⑥ told workers to "pre-include the desired trailer
in the commit message" to neutralize Orca's attribution-trailer wrapper (which otherwise breaks
pathspec parsing by inserting a stray `-m` after `-- <pathspec>`). That mitigation only prevents the
pathspec-parsing break -- it says nothing about the wrapper's *separate* append-suppression rule
(`message_already_has_trailer`): the wrapper only skips adding its own
`Co-authored-by: Orca <help@stably.ai>` trailer when the required trailer is already present verbatim
AND in the right position. Workers who merely included the trailer somewhere in the message (not as
the literal last line) still got Orca's own trailer appended after it, failing any AC requiring the
commit message to end with a specific trailer line.

studio-hevv/selah-android issue #14 hit exactly this and exhausted its retry budget
(escalation_parked); issue #21 independently rediscovered the fix (reorder trailers so the required
one is the literal last line) and documented it in its own commit message -- knowledge the skill
itself didn't provide. The fix direction also covers a secondary defect from the same evidence: the
trailer literal must be copied verbatim from the AC/plan text, never substituted with the actual
dispatched model name (issue #14's early commits wrote "Claude Sonnet 5", the model that ran, instead
of the AC-required "Claude Fable 5").
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "orca-task-runner" / "SKILL.md"


def _item_6_window() -> str:
    text = SKILL.read_text()
    start = text.index("⑥**병렬 커밋 안전 규칙**")
    end = text.index("⑦**연결 실패 자동 재시도", start)
    return text[start:end]


def test_item_6_still_covers_the_pathspec_parsing_mitigation():
    window = _item_6_window()
    assert "pathspec 파싱을 깨뜨리므로" in window
    assert "커밋 메시지에 원하는 trailer를 미리 포함시켜 wrapper의 추가 삽입을 무해화한다" in window


def test_item_6_documents_the_append_suppression_condition_and_last_line_requirement():
    window = _item_6_window()
    assert "issue #137" in window
    assert "message_already_has_trailer" in window
    assert "verbatim으로, 정확한 위치에" in window
    assert "Co-authored-by: Orca <help@stably.ai>" in window
    assert "커밋 메시지의 진짜 마지막 줄" in window


def test_item_6_forbids_substituting_dispatched_model_name_for_the_required_trailer_literal():
    window = _item_6_window()
    assert "AC/계획서 원문을 그대로 복사" in window
    assert "실제 dispatch된 model 이름으로 대체하지 않는다" in window


def test_item_6_ordering_pathspec_mitigation_then_append_suppression_then_literal_fidelity():
    window = _item_6_window()
    pathspec_idx = window.index("무해화한다")
    suppression_idx = window.index("message_already_has_trailer")
    literal_idx = window.index("AC/계획서 원문을 그대로 복사")
    assert pathspec_idx < suppression_idx < literal_idx
