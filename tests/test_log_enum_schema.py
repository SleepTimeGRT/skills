"""Doc-schema assertions for issue #86 (log-enum gaps: named values + UNMAPPED_BRANCH sentinel).

These check that orca-workflows/logging.md, orca-workflows/self-recovery.md, and the SKILL.md
sites that instruct writing those enums actually contain the AC-mandated literal tokens at their
specific sites -- not merely somewhere in the file. Unlike the deleted tests/test_orca_skills.py
(removed in f666b3a for asserting a SKILL.md's prose matched itself, encoding a stale claim as a
passing invariant), these assert that the diff contains externally-mandated tokens fixed by
proposal-r2.json's draft_acceptance_criteria (the confirmed contract for this issue) -- an
independent requirement, not a self-referential one. This repo has no CI, so this suite is the
only mechanical gate these docs get.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGGING_MD = REPO_ROOT / "orca-workflows" / "logging.md"
SELF_RECOVERY_MD = REPO_ROOT / "orca-workflows" / "self-recovery.md"
WORKFLOW_TASK_SKILL = REPO_ROOT / "skills" / "orca-workflow-task" / "SKILL.md"
WORKFLOW_EPIC_SKILL = REPO_ROOT / "skills" / "orca-workflow-epic" / "SKILL.md"
RETRO_SKILL = REPO_ROOT / "skills" / "orca-retro" / "SKILL.md"
SET_VERSION = REPO_ROOT / "skills" / "orca-set.version"


def _outcome_printf_line(text: str) -> str:
    prefix = 'printf \'{"ts":"%s","event":"outcome"'
    for line in text.splitlines():
        if line.strip().startswith(prefix):
            return line
    raise AssertionError("outcome printf recipe line not found")


def _logging_self_recovery_printf_line(text: str) -> str:
    prefix = 'printf \'{"ts":"%s","event":"self_recovery","skill":"<skill>"'
    for line in text.splitlines():
        if line.strip().startswith(prefix):
            return line
    raise AssertionError("logging.md self_recovery printf recipe line not found")


def _self_recovery_own_printf_line(text: str) -> str:
    prefix = 'printf \'{"ts":"%s","event":"self_recovery","skill":"%s"'
    for line in text.splitlines():
        if line.strip().startswith(prefix):
            return line
    raise AssertionError("self-recovery.md's own printf recipe line not found")


# ---------------------------------------------------------------------------
# ac1 -- CONTRACT_APPROVED_ROUND1 generalized to CONTRACT_APPROVED + variable round
# ---------------------------------------------------------------------------


def test_logging_md_generalizes_contract_approved():
    text = LOGGING_MD.read_text()
    assert re.search(r"CONTRACT_APPROVED_ROUND", text) is None
    assert len(re.findall(r"CONTRACT_APPROVED(?!_)", text)) >= 3
    assert "고정" not in text
    assert re.search(r"round=1\b", text) is None
    # override-absorbed (verdict-r2.json ac1): the replacement text must still say round is
    # variable, not just delete the fixed-round sentence. Window anchors ("CONTRACT_ESCALATE는
    # contract 협상이" / "MANUAL_RECOVERY_COMPLETED는") are unchanged by this diff, so this window
    # is valid both before and after the edit.
    start = text.index("`CONTRACT_ESCALATE`는 contract 협상이")
    end = text.index("`MANUAL_RECOVERY_COMPLETED`는")
    window = text[start:end]
    assert "가변" in window or "round=<" in window


def test_orca_workflow_task_skill_generalizes_round():
    text = WORKFLOW_TASK_SKILL.read_text()
    assert re.search(r"CONTRACT_APPROVED_ROUND", text) is None
    assert "outcome=CONTRACT_APPROVED, round=<" in text
    assert re.search(r"round=1\b", text) is None


# ---------------------------------------------------------------------------
# ac2 -- escalation_parked
# ---------------------------------------------------------------------------


def test_logging_md_writer_restriction_names_epic():
    text = LOGGING_MD.read_text()
    w1 = text[text.index("**`outcome`**"):text.index("진행-분기 축")]
    assert "orca-workflow-epic" in w1 and "escalation_parked" in w1
    w2 = text[text.index("`skill`은 기록 주체다"):text.index("**목록에 없는 정상 분기를 만나면**")]
    assert "orca-workflow-epic" in w2 and "escalation_parked" in w2


def test_logging_md_enum_window_has_escalation_parked():
    text = LOGGING_MD.read_text()
    window = text[text.index("진행-분기 축"):text.index("`skill`은 기록 주체다")]
    assert window.count("escalation_parked") >= 2


def test_orca_workflow_epic_logs_escalation_parked():
    text = WORKFLOW_EPIC_SKILL.read_text()
    window = text[text.index("**outcome 라우팅**"):text.index("## 4. root close")]
    assert "escalation_parked" in window
    assert "orca-workflow-epic" in window


# ---------------------------------------------------------------------------
# ac3 -- none_decision_gate_self_timed_out_worker_proceeded
# ---------------------------------------------------------------------------


def test_self_recovery_md_documents_new_action_taken_value():
    text = SELF_RECOVERY_MD.read_text()
    window = text[text.index("`recv` line for it."):text.index("**Retry budget: 2**")]
    assert "none_decision_gate_self_timed_out_worker_proceeded" in window
    assert "#93" in window
    # out-of-scope guard: the wait loop's listened-type argument is untouched by this change.
    assert "--types worker_done,escalation" in text


def test_logging_md_self_recovery_recipe_has_new_action_taken():
    line = _logging_self_recovery_printf_line(LOGGING_MD.read_text())
    assert "none_decision_gate_self_timed_out_worker_proceeded" in line


# ---------------------------------------------------------------------------
# ac4 -- UNMAPPED_BRANCH + raw_outcome/raw_action + schema_gap_issue safety valve
# ---------------------------------------------------------------------------


def test_logging_md_unmapped_branch_safety_valve():
    text = LOGGING_MD.read_text()
    enum_window = text[text.index("진행-분기 축"):text.index("`skill`은 기록 주체다")]
    assert enum_window.count("UNMAPPED_BRANCH") >= 1

    escape_hatch_window = text[
        text.index("목록에 없는 정상 분기를 만나면"):text.index("`RETRO_DONE`/`RETRO_FAIL`은")
    ]
    assert "UNMAPPED_BRANCH" in escape_hatch_window
    assert "raw_outcome" in escape_hatch_window
    assert "schema_gap_issue" in escape_hatch_window

    # override-absorbed (verdict-r2.json ac4): the outcome printf recipe itself -- the copy
    # origin dispatched skills actually paste -- must carry the same fields, not just the prose.
    outcome_line = _outcome_printf_line(text)
    assert "UNMAPPED_BRANCH" in outcome_line
    assert "raw_outcome" in outcome_line
    assert "schema_gap_issue" in outcome_line

    self_recovery_line = _logging_self_recovery_printf_line(text)
    assert "UNMAPPED_BRANCH" in self_recovery_line
    assert "raw_action" in self_recovery_line
    assert "schema_gap_issue" in self_recovery_line


def test_self_recovery_md_unmapped_branch_safety_valve():
    text = SELF_RECOVERY_MD.read_text()
    window = text[text.index("`recv` line for it."):text.index("**Retry budget: 2**")]
    assert "UNMAPPED_BRANCH" in window
    assert "raw_action" in window
    assert "schema_gap_issue" in window

    line = _self_recovery_own_printf_line(text)
    assert '"raw_action":"%s"' in line
    assert '"schema_gap_issue":"%s"' in line

    # the %s placeholder count in the printf format must match the positional-arg count on the
    # continuation lines, or the recipe prints garbage at runtime (this is executable, not prose).
    fmt_placeholders = line.count("%s")
    arg_lines = []
    lines = text.splitlines()
    idx = lines.index(line)
    j = idx + 1
    while j < len(lines) and lines[j].rstrip().endswith("\\"):
        arg_lines.append(lines[j])
        j += 1
    arg_lines.append(lines[j])
    args_text = " ".join(arg_lines).split(">>", 1)[0]  # drop the redirect target, not a printf arg
    arg_count = len(re.findall(r'"\$\{?[A-Za-z_][A-Za-z0-9_]*(?::-\})?"|"\$\([^)]*\)"', args_text))
    assert fmt_placeholders == arg_count == 11


# ---------------------------------------------------------------------------
# ac5 -- orca-retro lens 1 splits UNMAPPED_BRANCH-with-schema_gap_issue from without
# ---------------------------------------------------------------------------


def test_orca_retro_lens1_splits_unmapped_branch_with_and_without_schema_gap_issue():
    text = RETRO_SKILL.read_text()
    window = text[text.index("문서화된 스키마 위반"):text.index("스킬 문구 기인 반복 FAIL")]
    assert "추적 중인 알려진 구멍으로 읽고 후보에서 제외" in window
    assert "그대로 위반 후보" in window


# ---------------------------------------------------------------------------
# ac6 -- orca-set.version bump
# ---------------------------------------------------------------------------


def test_orca_set_version_bumped():
    lines = [l for l in SET_VERSION.read_text().splitlines() if l.strip()]
    assert lines[0] == "v1.1.2"
    assert sorted(lines[1:]) == sorted(
        [
            "orca-evaluate",
            "orca-retro",
            "orca-task-runner",
            "orca-workflow",
            "orca-workflow-epic",
            "orca-workflow-task",
        ]
    )


# ---------------------------------------------------------------------------
# ac7 -- GitHub comment structure matcher (override-absorbed: verdict-r2.json ac7)
#
# ac7 is a GitHub side effect, not repo state, so it is not read from disk here. This is the
# matcher function orca-evaluate applies to the live comment body via `gh issue view 86
# --comments --json comments`; it is unit-tested here (no network) against fixture strings so its
# correctness -- specifically, that it rejects DOTALL-style string reuse instead of requiring a
# real per-line raw-string -> reading pairing -- is independently verifiable.
# ---------------------------------------------------------------------------

AC7_MARKER = "## Schema readback (#86)"
AC7_RAW_STRINGS = (
    "CONTRACT_APPROVED_ROUND2",
    "escalation_parked",
    "none_decision_gate_self_timed_out_worker_proceeded",
)


def ac7_comment_matches(body: str) -> bool:
    if AC7_MARKER not in body:
        return False
    matched_lines = 0
    for raw in AC7_RAW_STRINGS:
        pattern = re.compile(r"^- .*" + re.escape(raw) + r".*->.*$", re.MULTILINE)
        matches = pattern.findall(body)
        if len(matches) != 1:
            return False
        matched_lines += 1
    return matched_lines == 3


def test_ac7_matcher_rejects_dotall_style_string_reuse():
    adversarial = (
        f"{AC7_MARKER}\n\n"
        "Raw strings observed: CONTRACT_APPROVED_ROUND2, escalation_parked, "
        "none_decision_gate_self_timed_out_worker_proceeded.\n\n"
        "-> these all map onto the new schema: CONTRACT_APPROVED_ROUND2, escalation_parked, "
        "none_decision_gate_self_timed_out_worker_proceeded.\n"
    )
    assert ac7_comment_matches(adversarial) is False


def test_ac7_matcher_rejects_missing_marker():
    valid_lines_no_marker = (
        "- `CONTRACT_APPROVED_ROUND2`,`round:2` -> `CONTRACT_APPROVED`+`round=2`\n"
        "- `escalation_parked` -> identical to the new escalation_parked value\n"
        "- `none_decision_gate_self_timed_out_worker_proceeded` -> identical to the new value\n"
    )
    assert ac7_comment_matches(valid_lines_no_marker) is False


def test_ac7_matcher_accepts_pinned_template():
    valid = (
        f"{AC7_MARKER}\n\n"
        "- `CONTRACT_APPROVED_ROUND2`,`round:2` (2026-08-08, assignments-2026-08-08.jsonl, "
        "#513 session) -> `CONTRACT_APPROVED`+`round=2`\n"
        "- `escalation_parked` (2026-08-08, assignments-2026-08-08.jsonl, #524 session) -> "
        "identical to the new escalation_parked value, no rewrite needed\n"
        "- `none_decision_gate_self_timed_out_worker_proceeded` (2026-08-08, "
        "waves-2026-08-08.jsonl, #524 session) -> identical to the new value of the same name, "
        "no rewrite needed\n"
    )
    assert ac7_comment_matches(valid) is True
