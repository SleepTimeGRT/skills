"""Regression coverage for issue #163 -- orca-workflow-task SKILL.md §1's "round limit reached"
mechanical branch checked override.json existence *before* checking whether verdict-r2.json's
rejection reasons include ac_fidelity. An ac_fidelity rejection never reaches the override step at
all (AC disagreement escalates straight to a human), so override.json is legitimately absent in
that case -- but the old check order treated that absence as "generator violated the §1 recording
contract" regardless of why. Real-world hit: studio-hevv/selah-android issue #23 (T25 settings
screen) logged "override.json 미기록" as if it were a contract violation when verdict-r2 had
already rejected on ac_fidelity(ac8, ac12) -- a normal, expected path with no violation at all.

The fix reorders the checks so ac_fidelity is examined first (right after confirming verdict-r2.json
itself exists), before the override.json-existence check. `orca-workflows/scripts/contract_resume.sh`
mirrors the same routing (see tests/test_contract_resume.py) and had the identical bug in its
"override.json absent" branch, literally commented "unchanged legacy path".
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_SKILL = REPO_ROOT / "skills" / "orca-workflow-task" / "SKILL.md"


def _round_limit_block(text: str) -> str:
    # The third fenced bash block under "라운드 한도 도달 시점" -- distinguished from the
    # round-2->3 extension block and the round-3-rejected block above it by its trailing
    # parenthetical marker just after the closing fence.
    marker = "(이 분기는 위 \"라운드 2→3 조건부 연장\""
    end = text.index(marker)
    start = text.rindex("```bash", 0, end)
    return text[start:end]


def test_ac_fidelity_check_precedes_override_json_check():
    block = _round_limit_block(TASK_SKILL.read_text())
    ac_fidelity_idx = block.index('index("ac_fidelity")')
    override_check_idx = block.index('[ ! -f "<CONTRACT_DIR>/override.json" ]')
    assert ac_fidelity_idx < override_check_idx


def test_ac_fidelity_branch_escalates_regardless_of_override_state():
    block = _round_limit_block(TASK_SKILL.read_text())
    assert "issue #163" in block
    assert "override 단계 스킵, 정상 경로" in block
    assert "CONTRACT_ESCALATE" in block


def test_verdict_r2_existence_still_checked_before_ac_fidelity():
    # Checking ac_fidelity's reasons[] requires verdict-r2.json to already be known-valid --
    # that check must remain the outermost guard, unchanged by the reorder.
    block = _round_limit_block(TASK_SKILL.read_text())
    verdict_missing_idx = block.index('if [ ! -f "<CONTRACT_DIR>/verdict-r2.json" ]')
    ac_fidelity_idx = block.index('index("ac_fidelity")')
    assert verdict_missing_idx < ac_fidelity_idx


def test_only_one_ac_fidelity_check_remains_in_the_block():
    # Before the fix, ac_fidelity was checked twice in this block (once, dead, near the end).
    block = _round_limit_block(TASK_SKILL.read_text())
    assert block.count('index("ac_fidelity")') == 1


def test_stale_detection_subblock_still_reachable_after_reorder():
    # The R3_REQUIRED_SINCE / CONTRACT_SCHEMA_STALE sub-block (issue #160) must still run for the
    # plan_coverage-only, override.json-present case -- the reorder must not have dropped it.
    block = _round_limit_block(TASK_SKILL.read_text())
    assert "R3_REQUIRED_SINCE" in block
    assert "CONTRACT_SCHEMA_STALE" in block
