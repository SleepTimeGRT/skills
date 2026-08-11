"""Doc-schema assertions for issue #92 (verification_plan[] fails_before_fix required field).

These check that orca-workflows/contract-schema.md, skills/orca-task-runner/SKILL.md, and
skills/orca-evaluate/SKILL.md carry the fails_before_fix field/rule at their negotiated sites
(proposal-r2.json's draft_acceptance_criteria is the confirmed contract for this issue, finalized
via override.json after the round limit) -- not merely somewhere in the file. Windows are bounded
by anchor pairs that already exist pre-edit (or the next top-level bullet marker), per
verdict-r2.json's reasons: a fixed-char-count window without an end anchor lets a paraphrase
mentioning both tokens anywhere in the same wide window pass without being adjacent to the edited
content, and a gap check against a token that already exists pre-edit in that window collapses to
bare-token-presence. This repo has no CI, so this suite is the only mechanical gate these docs get.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_SCHEMA_MD = REPO_ROOT / "orca-workflows" / "contract-schema.md"
TASK_RUNNER_SKILL = REPO_ROOT / "skills" / "orca-task-runner" / "SKILL.md"
EVALUATE_SKILL = REPO_ROOT / "skills" / "orca-evaluate" / "SKILL.md"
SET_VERSION = REPO_ROOT / "skills" / "orca-set.version"


def _min_gap(a: str, b: str, text: str) -> int:
    """Smallest character distance between any occurrence of a and any occurrence of b."""
    a_positions = [m.start() for m in re.finditer(re.escape(a), text)]
    b_positions = [m.start() for m in re.finditer(re.escape(b), text)]
    assert a_positions, f"{a!r} not found in text"
    assert b_positions, f"{b!r} not found in text"
    return min(abs(ai - bi) for ai in a_positions for bi in b_positions)


def _bullet_window(text: str, anchor: str) -> str:
    """Slice from anchor to the next top-level bullet marker ('\\n- '), i.e. the rest of the
    current bullet. anchor must exist verbatim in the file."""
    start = text.index(anchor)
    rest = text[start:]
    end = rest.index("\n- ", 1)
    return rest[:end]


# ---------------------------------------------------------------------------
# ac1 -- verification_plan[] JSON schema example gains fails_before_fix
# ---------------------------------------------------------------------------


def test_verification_plan_json_schema_has_fails_before_fix_field():
    text = CONTRACT_SCHEMA_MD.read_text()
    window = text[
        text.index('"scope": { "summary": "<무엇을 만들 것인가 — 사실 서술만>", "files": ["<path>"] },'):
        text.index('"destructive_operations": [ "<의도된 destructive op 설명>" ],')
    ]
    assert '"covers": ["ac1"]' in window
    assert '"method":' in window
    assert '"fails_before_fix":' in window
    assert window.index('"covers"') < window.index('"method"') < window.index('"fails_before_fix"')


# ---------------------------------------------------------------------------
# ac2/ac3 -- "모든 필드 필수" bullet: fails_before_fix required (empty/missing = violation) +
# explicit no-discrimination-path
# ---------------------------------------------------------------------------


def test_all_fields_required_bullet_states_fails_before_fix_empty_is_violation():
    text = CONTRACT_SCHEMA_MD.read_text()
    window = _bullet_window(text, '종전 prose 제안서의 "공란 vs 없음" 구분을 스키마 필수성이 대체한다).')
    assert "fails_before_fix" in window
    assert "스키마 위반" in window
    assert _min_gap("fails_before_fix", "스키마 위반", window) <= 60


def test_all_fields_required_bullet_states_no_discrimination_path():
    text = CONTRACT_SCHEMA_MD.read_text()
    window = _bullet_window(text, '종전 prose 제안서의 "공란 vs 없음" 구분을 스키마 필수성이 대체한다).')
    assert "변별 불가" in window
    assert "fix 전후 구분이 불가능" in window


# ---------------------------------------------------------------------------
# ac4 -- mechanical-check bullet lists both axes (coverage + fails_before_fix)
# ---------------------------------------------------------------------------


def test_mechanical_check_bullet_lists_fails_before_fix_axis():
    text = CONTRACT_SCHEMA_MD.read_text()
    window = text[
        text.index('`verification_plan[].covers`는 `draft_acceptance_criteria`의 id만 참조한다.'):
        text.index('## verdict-r')
    ]
    assert "어떤 plan 항목도" in window
    assert "fails_before_fix" in window
    assert window.count("기계적") >= 2


# ---------------------------------------------------------------------------
# ac5 -- no-persuasion bullet scopes fails_before_fix to facts, not justification
# ---------------------------------------------------------------------------


def test_no_persuasion_bullet_scopes_fails_before_fix_to_facts():
    text = CONTRACT_SCHEMA_MD.read_text()
    window = _bullet_window(text, "**설득 서술 필드는 의도적으로 없다.**")
    assert "fails_before_fix" in window
    # baseline "사실 서술" appears once pre-edit (scope.summary parenthetical) -- requiring a
    # second occurrence proves new content was actually added, not a nearby bare token
    # (verdict-r2.json reason 1: a gap check against a pre-existing token collapses to
    # bare-token-presence).
    assert window.count("사실 서술") >= 2
    # "정당화가 아니다" does not pre-exist in this bullet (pre-edit text only has "정당화는") --
    # a novel phrase, safe to pin exactly.
    assert "정당화가 아니다" in window
    assert _min_gap("fails_before_fix", "정당화가 아니다", window) <= 80


# ---------------------------------------------------------------------------
# ac6 -- orca-task-runner SKILL.md verification_plan bullet pins the required-field phrase
# ---------------------------------------------------------------------------


def test_orca_task_runner_verification_plan_bullet_pins_required_phrase():
    text = TASK_RUNNER_SKILL.read_text()
    window = _bullet_window(text, "검증 방법(`verification_plan`) — 구체적인 파일/함수/테스트로,")
    assert "fails_before_fix" in window
    assert "비어 있거나 없으면 반려 대상이다" in window
    for weasel in ("선택", "권장", "optional"):
        assert weasel not in window


# ---------------------------------------------------------------------------
# ac7 -- orca-evaluate: both sites (judgment-axis prose + spawned spec_text) mention
# fails_before_fix
# ---------------------------------------------------------------------------


def test_orca_evaluate_two_axis_sentence_mentions_fails_before_fix():
    text = EVALUATE_SKILL.read_text()
    window = text[
        text.index("②`verification_plan`이 그 AC를 실제로 커버하"):
        text.index("제안된 파일 범위")
    ]
    assert "fails_before_fix" in window


def test_orca_evaluate_spec_text_line_mentions_fails_before_fix():
    text = EVALUATE_SKILL.read_text()
    line = next(
        l for l in text.splitlines() if l.strip().startswith('spec_text="<proposal-r<n>.json 경로')
    )
    assert "fails_before_fix" in line


# ---------------------------------------------------------------------------
# ac8 -- skills/orca-set.version bumped to v1.1.9 (new assertion, separate from the
# existing_tests_affected update to tests/test_log_enum_schema.py)
# ---------------------------------------------------------------------------


def test_orca_set_version_line1_is_v1_1_9():
    lines = [l for l in SET_VERSION.read_text().splitlines() if l.strip()]
    assert lines[0] == "v1.1.9"


# ---------------------------------------------------------------------------
# ac9 -- the MediCount#513 proposal-r1.json item that slipped past round 1 review is rejected
# by the new required-field rule
# ---------------------------------------------------------------------------


def _verification_plan_item_is_schema_valid(item: dict) -> bool:
    """Mirrors the required-field rule contract-schema.md's "모든 필드 필수" bullet documents
    (see test_all_fields_required_bullet_states_fails_before_fix_empty_is_violation, which pins
    that sentence in the doc itself -- this helper is the executable form of the same rule,
    exercised against a real pre-fix fixture rather than only asserted as prose)."""
    return bool(item.get("covers")) and bool(item.get("method")) and bool(item.get("fails_before_fix"))


ISSUE_513_R1_AC2_ITEM = {
    "covers": ["ac2"],
    "method": (
        "104_ Q1-Q4: pg_get_functiondef에 position()을 써서 'v_ticket public.tickets%ROWTYPE'/"
        "'v_report public.reports%ROWTYPE' 존재(>0)와 unqualified 선언형 부재(=0)를 단언. LIKE는 "
        "쓰지 않는다(패턴의 '%ROWTYPE'에서 '%'가 와일드카드가 됨 — 103_이 명시한 함정)."
    ),
}


def test_issue_513_r1_ac2_item_rejected_by_new_required_field_rule():
    assert "fails_before_fix" not in ISSUE_513_R1_AC2_ITEM
    assert _verification_plan_item_is_schema_valid(ISSUE_513_R1_AC2_ITEM) is False


def test_verification_plan_item_with_fails_before_fix_passes_required_field_rule():
    item = dict(
        ISSUE_513_R1_AC2_ITEM,
        fails_before_fix=(
            "fix 이전 정의(단일 공백 padding)에서도 position()=0이라 변별 불가 — RED 확보 못함, "
            "ac4/ac5 절차로 별도 단언 필요."
        ),
    )
    assert _verification_plan_item_is_schema_valid(item) is True


# ---------------------------------------------------------------------------
# ac10 -- verdict-r<n>.json target enum unchanged; both check axes report under plan_coverage
# ---------------------------------------------------------------------------


def test_verdict_target_enum_unchanged_fails_before_fix_uses_plan_coverage():
    text = CONTRACT_SCHEMA_MD.read_text()
    window = _bullet_window(text, '`reasons[].target`은 `"ac_fidelity"` 또는 `"plan_coverage"`;')
    assert "plan_coverage" in window
    assert "추가하지 않는다" in window
