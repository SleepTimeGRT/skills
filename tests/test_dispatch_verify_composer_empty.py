"""Doc-schema regression guard for issue #151 (dispatch-verify.md's post-injection Enter-only retry
was written for one failure shape only: text sitting unsubmitted in the composer. A live `worker-start
--agent codex` failure showed a different shape -- the paste happened before the target TUI could accept
input, so nothing reached the composer at all, no draft, partial or otherwise. Sending Enter into an empty
composer is a no-op, so the escalation section needs a branch that tells the two shapes apart: any trace of
the injected payload present (however garbled) routes to the existing Enter-only remedy, no trace at all
routes to worker-abandon + worker-start --retry-of instead.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DISPATCH_VERIFY_MD = REPO_ROOT / "orca-workflows" / "dispatch-verify.md"


def test_escalation_section_distinguishes_stuck_draft_from_empty_composer():
    text = DISPATCH_VERIFY_MD.read_text()
    idx = text.index("## Escalation")
    next_idx = text.index("## Edge cases")
    window = text[idx:next_idx]
    assert "stuck draft" in window
    assert "composer empty" in window or "Composer is empty" in window


def test_empty_composer_branch_does_not_resend_enter():
    text = DISPATCH_VERIFY_MD.read_text()
    idx = text.index("Composer is empty, not stuck")
    window = text[idx : idx + 400]
    assert "Resending Enter cannot help" in window
    assert "worker-abandon" in window
    assert "--retry-of" in window


def test_stuck_draft_branch_still_defers_to_spawn_failures_43():
    text = DISPATCH_VERIFY_MD.read_text()
    idx = text.index("some form of our payload is present but unsubmitted")
    window = text[idx : idx + 200]
    assert "spawn-failures.md #43" in window


def test_fragment_check_is_coarser_than_prefix_check():
    text = DISPATCH_VERIFY_MD.read_text()
    idx = text.index("spec_fragment=")
    line_end = text.index("\n", idx)
    fragment_line = text[idx:line_end]
    assert "head -c 24" in fragment_line
    # ac: the fragment length must be strictly shorter than the original $spec_prefix's 80 chars, so a
    # partially-corrupted paste (garbled after the first ~24 bytes) still matches this coarser check even
    # when it no longer matches the clean 80-byte prefix used earlier in the procedure.
    assert "head -c 80" in text  # the original $spec_prefix definition, unchanged, still present above


def test_issue_151_cited():
    text = DISPATCH_VERIFY_MD.read_text()
    idx = text.index("## Escalation")
    next_idx = text.index("## Edge cases")
    window = text[idx:next_idx]
    assert "#151" in window
