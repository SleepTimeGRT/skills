"""Doc-schema assertions for issue #93 (self-recovery.md check --wait --types missing
question/decision_gate -- a dispatched worker's blocking `ask` never reaches the coordinator's
wait loop, so the worker times out and proceeds unsupervised).

Confirmed contract: CONTRACT_DIR/proposal-r2.json's draft_acceptance_criteria (ac1-ac6). ac5/ac6
(diff-scope-vs-base and orca-set.version-unchanged) are deliberately NOT encoded here as
committed, base-SHA-relative tests -- override.json (round 2) flagged that shape as a permanent
regression: a test comparing against a fixed historical commit goes red forever the moment any
later, unrelated PR touches orca-set.version or self-recovery.md outside these three ranges. ac5
was verified once, at implementation time, via `git diff --stat` against the branch's own base and
recorded in the commit message -- a review-time check, not a standing invariant. ac6 is already
covered by the pre-existing tests/test_log_enum_schema.py::test_orca_set_version_bumped, which
asserts the current version string and is updated by whichever future PR next bumps it -- this
change does not touch skills/orca-set.version, so that test's existing assertion continues to hold
unmodified.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SELF_RECOVERY_MD = REPO_ROOT / "orca-workflows" / "self-recovery.md"


def _min_gap(a: str, b: str, text: str) -> int:
    a_positions = [m.start() for m in re.finditer(re.escape(a), text)]
    b_positions = [m.start() for m in re.finditer(re.escape(b), text)]
    if not a_positions or not b_positions:
        raise AssertionError(f"{a!r} or {b!r} not found in text")
    return min(abs(ai - bi) for ai in a_positions for bi in b_positions)


# ---------------------------------------------------------------------------
# ac1 + ac2 -- check --wait --types gains question and decision_gate
# ---------------------------------------------------------------------------


def test_wait_loop_types_includes_question_and_decision_gate():
    text = SELF_RECOVERY_MD.read_text()
    assert (
        "--types worker_done,escalation,question,decision_gate --timeout-ms 3600000"
        in text
    )


# ---------------------------------------------------------------------------
# ac3 -- batch-routing comment documents question/decision_gate routing and priority
# ---------------------------------------------------------------------------


def test_routing_comment_documents_question_decision_gate_routing():
    text = SELF_RECOVERY_MD.read_text()
    start = text.index('# result.timedOut == "false"')
    end = text.index('orca orchestration check --run "$RUN_ID" --ack')
    window = text[start:end]
    # ac5 regression guard: the pre-existing worker_done/escalation routing survives untouched.
    assert "worker_done -> remove this task_id from the pending set" in window
    assert "escalation" in window and "route immediately" in window
    # ac3's new content.
    assert "question/decision_gate" in window
    assert "orca orchestration reply --id" in window
    assert "before worker_done's pending-set removal" in window


# ---------------------------------------------------------------------------
# ac4 -- the none_decision_gate_self_timed_out_worker_proceeded paragraph no longer
# contradicts the updated L51 --types value
# ---------------------------------------------------------------------------


def test_stale_paragraph_corrected():
    text = SELF_RECOVERY_MD.read_text()
    start = text.index("**`none_decision_gate_self_timed_out_worker_proceeded`**")
    end = text.index("**`UNMAPPED_BRANCH`**")
    window = text[start:end]
    assert "이 값 도입으로 바뀌지 않는다" not in window
    assert "worker_done,escalation,question,decision_gate" in window
    assert "#93" in window
    # verdict-r2.json plan_coverage/ac4: quoting the new --types value alone isn't enough -- the
    # historical claim ("check --wait --types worker_done,escalation 호출이 ... 듣지 않아") must be
    # reframed so it no longer describes the current L51 value, or the paragraph still contradicts
    # the fixed L51.
    assert _min_gap("이전", "check --wait --types worker_done,escalation", window) <= 50
    # eval-report-a1.json Finding 1 (important): the round-2 fix over-corrected into a *different*
    # self-contradiction -- claiming this action_taken value's occurrence path is fully "차단한다"
    # (blocked) while the very next sentence still gives present-tense recording instructions for
    # it. That exact false claim must not reappear, and the paragraph must instead say the value
    # remains valid and can still be recorded (coordinator receives the question but replies too
    # late for the worker's own `ask` budget) -- consistent with the recording instructions that
    # follow it in the same paragraph.
    assert "이 값이 다시 발생하는 경로를 차단한다" not in window
    assert "여전히 유효하다" in window
    assert "다시 기록될 수 있다" in window
    # eval-report-a1.json Finding 1's 부수 지적: 정의문 자체가 과거형("...진행한 경우였다")으로
    # 바뀌면 이 값이 은퇴한 것처럼 읽혀, 재관측 시 코디네이터가 UNMAPPED_BRANCH로 오분류해
    # 불필요한 스키마-갭 이슈를 열 위험이 있다(fail-open). 정의문은 현재형을 유지해야 한다.
    assert "진행한 경우다" in window
    assert "진행한 경우였다" not in window
