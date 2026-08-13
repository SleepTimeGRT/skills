"""Regression coverage for issue #142 -- Orca's `dispatch --inject` coordinator preamble tells
every spawned worker to send `heartbeat` messages, but none of this repo's skills consume them
(self-recovery.md's own liveness mechanism is a bounded `terminal read` probe, confirmed live
against dispatches whose `last_heartbeat_at` was always null). Each heartbeat still interrupts the
parent REPL with a runtime notification regardless of `check --wait`'s own `--types` filter,
costing a full-context turn for zero signal -- observed live during the #122 epic drain: 8+ parent
turns consumed by heartbeat-only wakeups across one 40-minute evaluate call.

The fix adds an explicit suppression instruction to every dispatch spec this repo assembles (four
sites in orca-workflow-task, one in orca-workflow-epic), each telling the spawned worker to also
propagate the same instruction to whatever it in turn spawns -- since the same per-turn cost
recurs at every level of the spawn tree, not just the first.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_SKILL = REPO_ROOT / "skills" / "orca-workflow-task" / "SKILL.md"
EPIC_SKILL = REPO_ROOT / "skills" / "orca-workflow-epic" / "SKILL.md"
SELF_RECOVERY = REPO_ROOT / "orca-workflows" / "self-recovery.md"

SUPPRESSION_MARKER = "heartbeat 억제"
PROPAGATION_CLAUSE = "네가 스폰하는 워커에게도 동일하게 지시하라"


def test_task_skill_defines_shared_heartbeat_suppression_contract():
    text = TASK_SKILL.read_text()
    assert "issue #142" in text
    assert PROPAGATION_CLAUSE in text


def test_task_skill_all_four_spec_texts_reference_the_contract():
    text = TASK_SKILL.read_text()
    spec_text_lines = [line for line in text.splitlines() if line.startswith("spec_text=")]
    assert len(spec_text_lines) == 4
    for line in spec_text_lines:
        assert f"{SUPPRESSION_MARKER} 계약(§0) 전문" in line


def test_epic_skill_spec_text_includes_suppression_and_propagation():
    text = EPIC_SKILL.read_text()
    spec_text_lines = [line for line in text.splitlines() if line.startswith("spec_text=")]
    assert len(spec_text_lines) == 1
    assert "issue #142" in spec_text_lines[0]
    assert PROPAGATION_CLAUSE in spec_text_lines[0]


def test_self_recovery_documents_why_suppression_is_safe():
    text = SELF_RECOVERY.read_text()
    assert "issue #142" in text
    assert "no consumer" in text or "never" in text
    # Must sit right where last_heartbeat_at is already discussed, not floating elsewhere.
    idx_heartbeat_field = text.index("last_heartbeat_at")
    idx_142 = text.index("issue #142")
    assert 0 < (idx_142 - idx_heartbeat_field) < 700
