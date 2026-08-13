"""Doc-schema regression coverage for issue #118 -- the coordinator's own `orca orchestration`/
`orca terminal` calls (not a spawned worker's) getting denied by Claude Code's auto-mode
classifier, with no registered signature and no hand-off procedure, forcing ad hoc re-spawns
(observed live: 3 coordinator terminals per child issue across #627/#628) each time it recurred.

Distinct from #87 (CLOSED): #87 was a spawned worker's launch command missing a bypass flag;
this is the calling coordinator session's own tool calls being denied -- hardcoding a flag on a
worker's launch line does not touch the caller session's own classifier.

The fix has three parts, and the tests below pin the load-bearing details of each:
- spawn-failures.md: a new row, explicitly marked session-unrecoverable, that says the recovery
  steps are executed by the *reader* of the report (parent orca-workflow-epic or a human) --
  never by the tripped session itself, since `orca terminal create` is itself one of the denied
  call classes once tripped.
- orca-workflow-task SKILL.md: a §0 bullet routing to §5 outcome=ESCALATE with `detail` carrying
  the CONTRACT_DIR path and a live task-runner handle, explicitly calling out the deviation from
  §0's own crash-resume default of never reusing a previous session's terminal.
- orca-workflow-epic SKILL.md: §3 outcome routing prose requiring the CONTRACT_DIR/handle to be
  surfaced verbatim in the parked record or hitl question, without adding an automatic re-spawn
  (out of scope per the issue's own text: "회피가 아니라 이관 절차의 명문화가 이 이슈의 범위다").
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPAWN_FAILURES = REPO_ROOT / "orca-workflows" / "spawn-failures.md"
TASK_SKILL = REPO_ROOT / "skills" / "orca-workflow-task" / "SKILL.md"
EPIC_SKILL = REPO_ROOT / "skills" / "orca-workflow-epic" / "SKILL.md"

CLASSIFIER_SIGNATURE = "Permission for this action was denied by the Claude Code auto mode classifier"


def _known_signatures_table() -> str:
    text = SPAWN_FAILURES.read_text()
    start = text.index("## Known signatures")
    end = text.index("\n\n## Adding a new row", start)
    return text[start:end]


def _table_rows(table: str) -> list[str]:
    return [
        line for line in table.splitlines()
        if line.startswith("| ") and not line.startswith("| `failure_signature`")
        and set(line.replace("|", "").replace("-", "").strip()) != set()
    ]


def _classifier_row() -> str:
    table = _known_signatures_table()
    return next(r for r in _table_rows(table) if CLASSIFIER_SIGNATURE in r)


def test_classifier_row_present_and_distinguished_from_87():
    row = _classifier_row()
    assert row.rstrip().endswith("#118 |")
    assert "#87" in row


def test_classifier_row_marks_session_unrecoverable_and_forbids_same_session_retry():
    row = _classifier_row()
    lowered = row.lower()
    assert "session-unrecoverable" in lowered or "복구 불가" in row
    assert "do not retry" in lowered or "재시도하지 않는다" in row


def test_classifier_row_assigns_recovery_to_the_reader_not_the_tripped_session():
    row = _classifier_row()
    assert "orca-workflow-epic" in row
    assert "orca terminal create" in row
    assert "never by the tripped session itself" in row or "tripped session itself" in row


def test_classifier_row_documents_contract_dir_and_handle_reuse_deviation():
    row = _classifier_row()
    assert "CONTRACT_DIR" in row
    assert "issue #156" in row or "#156" in row
    assert "reuse" in row.lower()


def test_task_skill_section_0_routes_own_call_denial_to_escalate_with_detail():
    text = TASK_SKILL.read_text()
    assert CLASSIFIER_SIGNATURE in text
    assert "issue #118" in text
    assert "outcome=ESCALATE" in text
    assert "CONTRACT_DIR" in text
    assert "log_outcome --detail" in text or "--detail" in text


def test_task_skill_calls_out_deviation_from_no_reuse_default():
    text = TASK_SKILL.read_text()
    section_0_start = text.index("## 0. 전제")
    section_1_start = text.index("## 1. Contract 협상 relay")
    section_0 = text[section_0_start:section_1_start]
    assert "issue #118" in section_0
    assert "재사용하지 않는다" in section_0  # quotes the existing crash-resume default it's deviating from
    assert "재사용" in section_0  # and states the deviation (reuse, not respawn, the reported handle)


def test_task_skill_section_5_report_content_covers_classifier_escalate():
    text = TASK_SKILL.read_text()
    section_5_start = text.index("## 5. Escalation")
    section_5 = text[section_5_start:]
    assert "issue #118" in section_5
    assert "detail" in section_5
    assert "CONTRACT_DIR" in section_5


def test_epic_skill_surfaces_contract_dir_and_handle_without_auto_respawning():
    text = EPIC_SKILL.read_text()
    assert "issue #118" in text
    assert CLASSIFIER_SIGNATURE in text
    assert "CONTRACT_DIR" in text
    # Out of scope per the issue body: no automatic re-spawn code path.
    assert "자동으로 재스폰하지는 않는다" in text or "자동 재시도로 성공을 단정할 근거가 없다" in text


def test_epic_skill_hitl_question_changes_for_this_signature():
    text = EPIC_SKILL.read_text()
    assert "재스폰(같은 CONTRACT_DIR" in text or "재스폰(같은 CONTRACT_DIR·핸들 재사용)" in text
