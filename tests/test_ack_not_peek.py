"""Doc-schema regression guard for issue #134 (self-recovery.md's mandatory ack call combined
`--ack "<result.deliveryId>"` with `--peek` on one line -- but `check --peek` never exposes a
`deliveryId` in its response, so any batch it returns can never be acked and gets replayed by the
loop's next `check --wait`, confirmed live against Orca 1.4.178 three times in the same session
this issue was filed from). The fix splits the two concerns: `--ack` always targets this
iteration's own `$result` (the loop's non-peek `check --wait` at the top, the only call that ever
exposes a `deliveryId`), and the next batch is only ever fetched by looping back to that same
non-peek call -- never by `--peek`.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SELF_RECOVERY_MD = REPO_ROOT / "orca-workflows" / "self-recovery.md"


def _ack_lines(text: str) -> list[str]:
    # Only actual command invocations, not the prose paragraph that discusses --ack/--peek.
    return [
        line
        for line in text.splitlines()
        if "orca orchestration check" in line and "--ack" in line
    ]


def test_no_ack_call_combines_peek():
    text = SELF_RECOVERY_MD.read_text()
    ack_lines = _ack_lines(text)
    assert ack_lines, "expected at least one --ack call in self-recovery.md"
    for line in ack_lines:
        assert "--peek" not in line, (
            f"--ack and --peek must never appear on the same call (issue #134): {line!r}"
        )


def test_mandatory_ack_derives_delivery_id_from_loop_result():
    text = SELF_RECOVERY_MD.read_text()
    idx = text.index('orca orchestration check --run "$RUN_ID" --ack')
    line_end = text.index("\n", idx)
    ack_line = text[idx:line_end]
    assert "$result" in ack_line
    assert ".result.deliveryId" in ack_line


def test_peek_ack_incompatibility_documented():
    text = SELF_RECOVERY_MD.read_text()
    assert "Never combine this `--ack` call with `--peek`" in text
    assert "stale_delivery" in text
    assert "#134" in text


def test_no_regression_of_worker_done_ack_replay_warning():
    # ac survives from the loop's pre-existing "unacked stale message was replayed" warning.
    text = SELF_RECOVERY_MD.read_text()
    assert "replays the same unacknowledged delivery" in text
    assert "replayed:true" in text
