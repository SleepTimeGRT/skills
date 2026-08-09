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
    # verdict-r2.json plan_coverage/ac4: L135 alone quoting the new value isn't enough -- L132-133's
    # present-tense claim ("check --wait --types worker_done,escalation 호출이 question 타입을 듣지
    # 않아") must also be reframed as historical, or the paragraph still contradicts the fixed L51.
    assert _min_gap("당시", "check --wait --types worker_done,escalation", window) <= 50
