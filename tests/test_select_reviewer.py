from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "skills" / "orca-evaluate" / "scripts" / "select_reviewer.py"


def _load_module():
    # This repo has no in-process-import precedent (existing script tests use subprocess against
    # a path constant instead), and `orca-evaluate` contains a hyphen, so a plain `import` cannot
    # reach this file regardless. Loading it directly by file path keeps per-branch unit-test
    # granularity instead of degrading every case to a CLI round trip.
    spec = importlib.util.spec_from_file_location("orca_evaluate_select_reviewer", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses' internals look up `sys.modules[cls.__module__]` while processing frozen
    # dataclasses (for its typing-based `KW_ONLY`/`ClassVar` checks) — without registering the
    # module first, that lookup returns None and dataclass() crashes on import.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_module = _load_module()
DiffStats = _module.DiffStats
ReviewerChoice = _module.ReviewerChoice
classify_tier = _module.classify_tier
select_reviewer = _module.select_reviewer
parse_shortstat = _module.parse_shortstat


# ---------------------------------------------------------------------------
# classify_tier
# ---------------------------------------------------------------------------

def test_classify_tier_at_both_thresholds_stays_routine():
    assert classify_tier(DiffStats(files_changed=15, lines_changed=400)) == "routine"


def test_classify_tier_one_file_over_threshold_is_high_risk():
    assert classify_tier(DiffStats(files_changed=16, lines_changed=0)) == "high-risk"


def test_classify_tier_one_line_over_threshold_is_high_risk():
    assert classify_tier(DiffStats(files_changed=0, lines_changed=401)) == "high-risk"


def test_classify_tier_matches_actual_round0_diff():
    # issue #24's own round0 diff: 5 files, +496 -13 = 509 churn — reviewed at claude-opus-5/xhigh
    # in practice. Grounds the line threshold in a real, not hypothetical, case.
    assert classify_tier(DiffStats(files_changed=5, lines_changed=509)) == "high-risk"


def test_classify_tier_small_diff_is_routine():
    assert classify_tier(DiffStats(files_changed=1, lines_changed=10)) == "routine"


def test_classify_tier_high_risk_signal_overrides_small_churn():
    # Round1 Finding 2: a tiny migration diff must not be classified "routine" just because churn
    # is small — §3 already knows (from its own migration-file check) that this is a known
    # high-risk kind, and that signal must not be discarded at tier-selection time.
    small_migration_diff = DiffStats(files_changed=1, lines_changed=5)
    assert classify_tier(small_migration_diff) == "routine"  # churn alone: still routine
    assert classify_tier(small_migration_diff, high_risk_signal=True) == "high-risk"


def test_classify_tier_high_risk_signal_false_does_not_force_high_risk():
    assert classify_tier(DiffStats(files_changed=1, lines_changed=5), high_risk_signal=False) == "routine"


# ---------------------------------------------------------------------------
# select_reviewer — all 2x2 (tier x codex_available) branches, plus the fable exclusion
# ---------------------------------------------------------------------------

def test_select_reviewer_routine_prefers_codex_terra_when_available():
    choice = select_reviewer(DiffStats(1, 10), codex_available=True)
    assert choice == ReviewerChoice("codex", "gpt-5.6-terra", "medium")


def test_select_reviewer_routine_falls_back_to_sonnet_with_advisor_when_codex_unavailable():
    choice = select_reviewer(DiffStats(1, 10), codex_available=False)
    assert choice == ReviewerChoice("claude", "claude-sonnet-5", "high", advisor="opus")


def test_select_reviewer_high_risk_prefers_codex_sol_xhigh_when_available():
    choice = select_reviewer(DiffStats(50, 1000), codex_available=True)
    assert choice == ReviewerChoice("codex", "gpt-5.6-sol", "xhigh")


def test_select_reviewer_high_risk_falls_back_to_opus_xhigh_when_codex_unavailable():
    choice = select_reviewer(DiffStats(50, 1000), codex_available=False)
    assert choice == ReviewerChoice("claude", "claude-opus-5", "xhigh")


def test_select_reviewer_default_codex_available_is_true():
    choice = select_reviewer(DiffStats(1, 10))
    assert choice.provider == "codex"


def test_select_reviewer_never_returns_fable():
    for files, lines in ((1, 10), (50, 1000)):
        for codex_available in (True, False):
            choice = select_reviewer(DiffStats(files, lines), codex_available=codex_available)
            assert choice.model != "claude-fable-5"


# ---------------------------------------------------------------------------
# select_reviewer with high_risk_signal — the direct reproduction the task asked for: a diff with
# low churn (files/lines well under the routine threshold) that still must not be routed to the
# cheapest reviewer tier because a known high-risk signal (e.g. migration files) is present.
# ---------------------------------------------------------------------------

def test_select_reviewer_small_migration_diff_is_no_longer_lowest_tier_when_codex_available():
    small_migration_diff = DiffStats(files_changed=1, lines_changed=5)
    # Without the signal: churn alone puts this at the cheapest reviewer (round1's bug).
    assert select_reviewer(small_migration_diff, codex_available=True) == ReviewerChoice(
        "codex", "gpt-5.6-terra", "medium"
    )
    # With the signal: same tiny diff, now correctly promoted to the high-risk reviewer.
    choice = select_reviewer(small_migration_diff, codex_available=True, high_risk_signal=True)
    assert choice == ReviewerChoice("codex", "gpt-5.6-sol", "xhigh")
    assert choice.model != "gpt-5.6-terra"


def test_select_reviewer_small_migration_diff_is_no_longer_lowest_tier_when_codex_unavailable():
    small_migration_diff = DiffStats(files_changed=1, lines_changed=5)
    choice = select_reviewer(small_migration_diff, codex_available=False, high_risk_signal=True)
    assert choice == ReviewerChoice("claude", "claude-opus-5", "xhigh")
    assert choice.model != "claude-sonnet-5"


# ---------------------------------------------------------------------------
# parse_shortstat — full form, each optional clause missing, singular forms, empty
# ---------------------------------------------------------------------------

def test_parse_shortstat_handles_full_form():
    stats = parse_shortstat(" 5 files changed, 496 insertions(+), 13 deletions(-)")
    assert stats == DiffStats(files_changed=5, lines_changed=509)


def test_parse_shortstat_handles_missing_deletions_clause():
    # git omits the deletions clause entirely when nothing was deleted.
    stats = parse_shortstat(" 1 file changed, 1 insertion(+)")
    assert stats == DiffStats(files_changed=1, lines_changed=1)


def test_parse_shortstat_handles_missing_insertions_clause():
    # Pure-deletion diff — git omits the insertions clause entirely. This branch was missing from
    # round1's coverage (a real, common case: a file or dead-code deletion PR).
    stats = parse_shortstat(" 1 file changed, 3 deletions(-)")
    assert stats == DiffStats(files_changed=1, lines_changed=3)


def test_parse_shortstat_handles_singular_forms():
    stats = parse_shortstat(" 1 file changed, 1 insertion(+), 1 deletion(-)")
    assert stats == DiffStats(files_changed=1, lines_changed=2)


def test_parse_shortstat_empty_diff_is_zero_zero():
    assert parse_shortstat("") == DiffStats(files_changed=0, lines_changed=0)


def test_parse_shortstat_whitespace_only_is_zero_zero():
    assert parse_shortstat("   \n") == DiffStats(files_changed=0, lines_changed=0)


def test_parse_shortstat_raises_on_unparseable_nonempty_input():
    # A non-empty string with no recognizable "N file(s) changed" clause (garbage, or a
    # locale-translated `git` build) must not silently degrade to DiffStats(0, 0) — that would
    # read as the smallest possible diff and route to the cheapest reviewer tier.
    with pytest.raises(ValueError):
        parse_shortstat("fatal: ambiguous argument 'HEAD': unknown revision")


# ---------------------------------------------------------------------------
# CLI — end-to-end, no repo/subprocess-to-git needed since the script itself never calls git
# ---------------------------------------------------------------------------

def test_cli_prints_json_for_shortstat_input():
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--shortstat", " 1 file changed, 1 insertion(+)", "--codex-available"],
        capture_output=True, text=True, check=True,
    )
    payload = json.loads(result.stdout)
    assert payload == {"provider": "codex", "model": "gpt-5.6-terra", "effort": "medium", "advisor": None}


def test_cli_no_codex_available_flag_falls_back_to_claude():
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--shortstat", " 1 file changed, 1 insertion(+)", "--no-codex-available"],
        capture_output=True, text=True, check=True,
    )
    payload = json.loads(result.stdout)
    assert payload == {"provider": "claude", "model": "claude-sonnet-5", "effort": "high", "advisor": "opus"}


def test_cli_high_risk_diff_selects_sol():
    shortstat = " 20 files changed, 900 insertions(+), 100 deletions(-)"
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--shortstat", shortstat, "--codex-available"],
        capture_output=True, text=True, check=True,
    )
    payload = json.loads(result.stdout)
    assert payload == {"provider": "codex", "model": "gpt-5.6-sol", "effort": "xhigh", "advisor": None}


def test_cli_small_migration_diff_promoted_to_high_risk_via_flag():
    # End-to-end reproduction of round1 Finding 2's exact scenario: a diff with low churn (well
    # under the routine threshold) that carries a known high-risk signal (e.g. touches migration
    # files) — first confirm churn alone keeps it at the cheapest tier, then confirm
    # --high-risk-signal promotes it, exactly as §3's bash block now does when
    # migration_files_present=true.
    small_shortstat = " 1 file changed, 5 insertions(+)"

    without_signal = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--shortstat", small_shortstat, "--codex-available"],
        capture_output=True, text=True, check=True,
    )
    payload_without = json.loads(without_signal.stdout)
    assert payload_without["model"] == "gpt-5.6-terra"  # the round1 bug, confirmed present without the flag

    with_signal = subprocess.run(
        [
            sys.executable, str(SCRIPT_PATH), "--shortstat", small_shortstat,
            "--codex-available", "--high-risk-signal",
        ],
        capture_output=True, text=True, check=True,
    )
    payload_with = json.loads(with_signal.stdout)
    assert payload_with == {"provider": "codex", "model": "gpt-5.6-sol", "effort": "xhigh", "advisor": None}
    assert payload_with["model"] != "gpt-5.6-terra"


def test_cli_unparseable_shortstat_exits_nonzero_instead_of_silently_picking_lowest_tier():
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--shortstat", "fatal: ambiguous argument", "--codex-available"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert result.stdout.strip() == ""  # no JSON printed — never silently returns a default choice


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__]))
