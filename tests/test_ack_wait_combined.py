"""Doc-schema regression guard for issue #147 (self-recovery.md's wait/recovery loop issued a
separate, unwaited `check --ack ... --json` call after processing each batch, instead of folding
that ack into the very call that waits for the next batch). Orca's own bundled orchestration skill
guide (`orca skills get orchestration`, confirmed live against 1.4.180) documents the combined form
as the standard idiom: "check --ack <delivery_id> --wait ... acknowledges, checks, and waits in one
operation." This test pins the restructured loop: `prev_delivery_id` is empty before the first
iteration (a bare `check --wait`, nothing to ack yet), and every iteration after that combines
`--ack "$prev_delivery_id"` with `--wait` in one call -- never two separate round trips.

zsh does not word-split an unquoted `${var:+...}` expansion the way bash/POSIX sh do (confirmed
live in this session), so the conditional is an explicit if/else, not a one-line optional flag --
this matches scripts/log_dispatch.sh's existing portability contract for the same shell.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SELF_RECOVERY_MD = REPO_ROOT / "orca-workflows" / "self-recovery.md"


def test_prev_delivery_id_initialized_before_first_iteration():
    text = SELF_RECOVERY_MD.read_text()
    assert 'prev_delivery_id=""' in text


def test_top_of_loop_combines_ack_and_wait_when_prev_delivery_id_set():
    text = SELF_RECOVERY_MD.read_text()
    idx = text.index('if [ -n "$prev_delivery_id" ]; then')
    branch_end = text.index("fi", idx)
    window = text[idx:branch_end]
    assert '--ack "$prev_delivery_id"' in window
    assert "--wait" in window
    # both flags on the same orca orchestration check invocation, not two separate calls.
    ack_line_idx = window.index('--ack "$prev_delivery_id"')
    same_call = window[ack_line_idx : ack_line_idx + 200]
    assert "--wait" in same_call


def test_first_iteration_falls_back_to_bare_wait():
    text = SELF_RECOVERY_MD.read_text()
    idx = text.index('if [ -n "$prev_delivery_id" ]; then')
    else_idx = text.index("else", idx)
    fi_idx = text.index("fi", else_idx)
    else_branch = text[else_idx:fi_idx]
    assert "--ack" not in else_branch
    assert "--wait" in else_branch


def test_prev_delivery_id_updated_every_iteration_regardless_of_timeout():
    text = SELF_RECOVERY_MD.read_text()
    idx = text.index("# Set what the *next* iteration")
    window = text[idx : idx + 600]
    assert 'prev_delivery_id=""' in window
    assert "prev_delivery_id=\"$(printf '%s' \"$result\" | jq -r '.result.deliveryId')\"" in window
    assert 'if [ "$timed_out" = "true" ]' in window


def test_no_standalone_unwaited_ack_call_remains():
    text = SELF_RECOVERY_MD.read_text()
    for line in text.splitlines():
        if "orca orchestration check" in line and "--ack" in line:
            assert "--wait" in line, (
                f"every --ack call in this loop must be combined with --wait (issue #147): {line!r}"
            )


def test_official_idiom_citation_present():
    text = SELF_RECOVERY_MD.read_text()
    assert "orca skills get orchestration" in text
    assert "acknowledges, checks, and waits in one operation" in text
