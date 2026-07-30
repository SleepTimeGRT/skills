"""Structural validation for the orca-workflow/orca-task-runner/orca-evaluate
skill family. These are prose/instruction files, not executable code, so the
checks validate structure (frontmatter, cross-references, stale-term absence)
rather than runtime behavior.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
WORKFLOWS_DIR = REPO_ROOT / "orca-workflows"

NEW_SKILLS = ["orca-workflow", "orca-task-runner", "orca-evaluate"]
RETIRED_SKILLS = ["orca-review-gate", "orca-sdd"]
STALE_TERMS = [
    "orca-review-gate",
    "orca-sdd",
    "evaluator에서 제외",
    "cross-model 리뷰 게이트",
]
WORKFLOWS_DOCS = [
    "model-selection.md",
    "models/claude-code.md",
    "models/codex.md",
    "models/agy.md",
]
PROVIDER_REFERENCES = {
    "models/claude-code.md": "../references/models/claude-code.md",
    "models/codex.md": "../references/models/codex.md",
    "models/agy.md": "../references/models/agy.md",
}


def _read_skill(name: str) -> str:
    path = SKILLS_DIR / name / "SKILL.md"
    assert path.is_file(), f"{name}/SKILL.md missing"
    return path.read_text()


def _frontmatter(text: str) -> str:
    assert text.startswith("---\n"), "missing YAML frontmatter"
    return text.split("---\n", 2)[1]


@pytest.mark.parametrize("name", NEW_SKILLS)
def test_skill_directory_exists(name):
    assert (SKILLS_DIR / name / "SKILL.md").is_file(), f"{name}/SKILL.md missing"


@pytest.mark.parametrize("name", NEW_SKILLS)
def test_frontmatter_has_name_and_description(name):
    text = _read_skill(name)
    fm = _frontmatter(text)
    assert re.search(rf"^name:\s*{re.escape(name)}\s*$", fm, re.M), (
        f"{name}: frontmatter 'name' must equal directory name"
    )
    desc = re.search(r"^description:\s*(.+)$", fm, re.M)
    assert desc and len(desc.group(1)) > 40, (
        f"{name}: 'description' missing or too short to carry real trigger info"
    )


@pytest.mark.parametrize("name", RETIRED_SKILLS)
def test_retired_skill_removed(name):
    assert not (SKILLS_DIR / name).exists(), (
        f"{name} must be deleted from skills/, not left alongside its replacement"
    )


@pytest.mark.parametrize("name", NEW_SKILLS)
def test_no_stale_terms_in_body(name):
    text = _read_skill(name)
    for term in STALE_TERMS:
        assert term not in text, f"{name}: stale reference '{term}' should be gone"


def test_delegation_references():
    task_runner = _read_skill("orca-task-runner")
    workflow = _read_skill("orca-workflow")
    assert "orca-evaluate" in task_runner, (
        "orca-task-runner must hand off evaluation to orca-evaluate, not embed it"
    )
    assert "orca-task-runner" in workflow and "orca-evaluate" in workflow, (
        "orca-workflow must route to both orca-task-runner and orca-evaluate"
    )


def test_orca_evaluate_has_verdict_vocabulary():
    text = _read_skill("orca-evaluate")
    for term in ("PASS", "FAIL", "ESCALATE"):
        assert re.search(rf"\b{term}\b", text), f"orca-evaluate must define the '{term}' verdict"


def test_orca_workflow_never_generates_or_evaluates_itself():
    text = _read_skill("orca-workflow")
    assert "생성하지도, 평가하지도 않는다" in text, (
        "orca-workflow must explicitly state it never generates or evaluates directly"
    )


@pytest.mark.parametrize("doc", WORKFLOWS_DOCS)
def test_workflows_docs_do_not_reference_retired_skill_names(doc):
    text = (WORKFLOWS_DIR / doc).read_text()
    for term in RETIRED_SKILLS:
        assert term not in text, f"{doc}: stale reference '{term}'"


def test_model_selection_references_current_workflow_skills():
    text = (WORKFLOWS_DIR / "model-selection.md").read_text()
    for name in NEW_SKILLS:
        assert name in text, (
            f"model-selection.md: workflow entry point should reference {name}"
        )


@pytest.mark.parametrize(("doc", "reference"), PROVIDER_REFERENCES.items())
def test_provider_docs_link_their_evidence_reference(doc, reference):
    text = (WORKFLOWS_DIR / doc).read_text()
    assert f"]({reference})" in text, (
        f"{doc}: should link its provider evidence at {reference}"
    )
    assert (WORKFLOWS_DIR / "models" / reference).resolve().is_file(), (
        f"{doc}: evidence link target does not exist: {reference}"
    )


def test_orca_task_runner_declares_destructive_ops_field():
    text = _read_skill("orca-task-runner")
    assert "의도된 destructive 오퍼레이션" in text, (
        "orca-task-runner's proposal format must require a declared destructive-ops field"
    )


def test_orca_evaluate_has_migration_escalate_condition():
    text = _read_skill("orca-evaluate")
    assert "destructive-op 린터가 flag" in text and "선언에 커버되지 않는다" in text, (
        "orca-evaluate §4 must add the migration destructive-op ESCALATE condition"
    )


ISSUE_TRACKERS_DIR = REPO_ROOT / "orca-workflows" / "issue-trackers"
TRACKER_ADAPTER_FILES = ["github.md", "jira.md"]
TRACKER_ALL_FILES = ["selection.md", "github.md", "jira.md"]
TRACKER_OPERATIONS = [
    "get_issue",
    "get_issue_type",
    "list_children",
    "get_child_order",
    "is_open",
    "close_issue",
    "link_pr_for_close",
]
VPROP_SPECIFIC_LEAKS = ["VP-", "voyagerx", "fb59360c"]


@pytest.mark.parametrize("filename", TRACKER_ALL_FILES)
def test_issue_tracker_file_exists(filename):
    assert (ISSUE_TRACKERS_DIR / filename).is_file(), (
        f"orca-workflows/issue-trackers/{filename} missing"
    )


@pytest.mark.parametrize("filename", TRACKER_ADAPTER_FILES)
def test_issue_tracker_adapter_defines_all_operations(filename):
    text = (ISSUE_TRACKERS_DIR / filename).read_text()
    for op in TRACKER_OPERATIONS:
        assert f"`{op}(" in text, f"{filename}: must define operation '{op}'"


@pytest.mark.parametrize("term", VPROP_SPECIFIC_LEAKS)
def test_jira_adapter_has_no_vprop_specific_values(term):
    text = (ISSUE_TRACKERS_DIR / "jira.md").read_text()
    assert term not in text, (
        f"jira.md must stay repo-agnostic — found vprop-specific value '{term}'"
    )


def test_jira_adapter_uses_structural_fields():
    text = (ISSUE_TRACKERS_DIR / "jira.md").read_text()
    for field in ("hierarchyLevel", "parent", "statusCategory", "getTransitionsForJiraIssue"):
        assert field in text, f"jira.md must use the structural field/tool '{field}'"


def test_github_adapter_uses_gh_cli():
    text = (ISSUE_TRACKERS_DIR / "github.md").read_text()
    for call in ("gh issue view", "gh issue list", "gh issue close"):
        assert call in text, f"github.md must define '{call}'"


def test_github_adapter_prefers_native_sub_issues_and_exact_close_match():
    text = (ISSUE_TRACKERS_DIR / "github.md").read_text()
    assert "sub_issues" in text, "github.md must query GitHub's native sub-issues API"
    assert re.search(
        r"Refs #N.*?의존 edge로 취급하지 않는다",
        text,
        re.S,
    ), "github.md must explicitly exclude informational refs from dependency edges"
    assert "([^0-9]|$)" in text, (
        "github.md closing-keyword check must not match #12 inside #123"
    )


def test_selection_doc_defines_backend_choice_and_onboarding_trigger():
    text = (ISSUE_TRACKERS_DIR / "selection.md").read_text()
    assert "Issue tracker" in text, (
        "selection.md must describe the AGENTS.md/CLAUDE.md pointer lookup"
    )
    assert "온보딩" in text, (
        "selection.md must reference the onboarding trigger for undocumented repos"
    )


def test_linear_adapter_requires_selection_disambiguation():
    text = (ISSUE_TRACKERS_DIR / "selection.md").read_text()
    assert "Jira와 Linear" in text and "식별자" in text, (
        "selection.md must disambiguate Jira and Linear project-style identifiers"
    )
    assert "변경은 필요 없다" not in text, (
        "selection.md must not claim a Linear adapter is sufficient by itself"
    )


def test_jira_adapter_is_runtime_portable():
    text = (ISSUE_TRACKERS_DIR / "jira.md").read_text()
    assert "mcp__claude_ai_Atlassian" not in text, (
        "jira.md must not pin the adapter to Claude's MCP namespace"
    )
    for capability in (
        r"issue\s+조회",
        r"JQL\s+검색",
        r"transition\s+목록",
        r"상태\s+전환",
        r"comment\s+추가",
    ):
        assert re.search(capability, text), (
            f"jira.md must name the Atlassian capability matching {capability!r}"
        )


def test_spawn_failure_log_uses_json_encoder():
    text = (WORKFLOWS_DIR / "spawn-failures.md").read_text()
    assert "jq -cn" in text, "spawn-failures.md must encode JSONL with jq"
    assert "printf '{\"ts\"" not in text, (
        "spawn-failures.md must not interpolate unescaped values into JSON"
    )


def test_orca_workflow_no_hardcoded_gh_issue_calls():
    text = _read_skill("orca-workflow")
    for term in ("gh issue view", "gh issue list", "gh issue close"):
        assert term not in text, (
            f"orca-workflow must not call '{term}' directly — route through the issue-tracker adapter"
        )
    assert "gh pr" in text, (
        "orca-workflow must keep gh pr calls — code hosting stays GitHub-specific"
    )


def test_orca_workflow_references_issue_tracker_selection():
    text = _read_skill("orca-workflow")
    assert "issue-trackers/selection.md" in text, (
        "orca-workflow §0 must resolve the backend via issue-trackers/selection.md"
    )


def test_orca_workflow_has_onboarding_subflow():
    text = _read_skill("orca-workflow")
    assert "온보딩" in text, (
        "orca-workflow §0 must define the onboarding subflow for undocumented repos"
    )


def test_orca_workflow_uses_abstract_tracker_operations():
    text = _read_skill("orca-workflow")
    for op in ("get_issue", "list_children", "get_child_order", "is_open", "close_issue"):
        assert op in text, f"orca-workflow must route issue-tracker access through '{op}'"


@pytest.mark.parametrize("name", NEW_SKILLS)
def test_no_hardcoded_acceptance_criteria_heading(name):
    text = _read_skill(name)
    assert "## Acceptance criteria" not in text, (
        f"{name}: acceptance-criteria heading must come from the resolved tracker marker, "
        "not a hardcoded GitHub heading"
    )
    assert "## What to build" not in text, (
        f"{name}: 'what to build' heading must not be hardcoded either"
    )


def _gate_safety_item_anchors(text: str) -> tuple[int, int, int, int]:
    """Locates the mandatory reviewer checklist's ⑤ item and its enclosing paragraph, scoped by
    the enumeration's own paragraph boundary rather than a fixed character window.

    Round1 Finding 1: the original version of this anchor asserted only
    `checklist_idx < fourth_idx < fifth_idx`. `str.index(sub, start)` is defined to return an
    index `>= start` on success, so once both `index()` calls succeed that inequality is true by
    construction — it cannot fail. Concretely: it stays green even if ⑤ is moved into a wholly
    unrelated paragraph (or a different section entirely), which is exactly the gap the
    coordinator's "boundary" requirement in the original review was meant to close (that
    requirement was dropped when this anchor was first written).

    The fix restores a real boundary: `para_end`, the first blank line after the checklist
    sentence starts. ⑤ must fall strictly before it. `test_gate_safety_anchor_rejects_item_
    relocated_outside_enumeration` below proves this is no longer a tautology by feeding it
    round1's own forged counterexample and checking it is rejected.
    """
    checklist_idx = text.index("리뷰어는 반드시 이 항목들을 갖는다")
    fourth_idx = text.index("④", checklist_idx)
    fifth_idx = text.index("⑤", fourth_idx)
    para_end = text.index("\n\n", checklist_idx)
    return checklist_idx, fourth_idx, fifth_idx, para_end


def test_gate_safety_anchor_rejects_item_relocated_outside_enumeration():
    # Round1's own counterexample, verbatim: ④ ends the mandatory enumeration's paragraph, and ⑤
    # reappears later in a separate, unrelated paragraph. The pre-fix anchor
    # (checklist_idx < fourth_idx < fifth_idx only) passed this text; this test proves the fixed
    # anchor no longer does, i.e. that it is not a tautology.
    forged = (
        "리뷰어는 반드시 이 항목들을 갖는다: ①a ②b ③c ④d\n\n"
        "관계없는 다른 절.\n\n"
        "⑤ ...를 지시한다. 비망라적. Critical/Important. escalation."
    )
    checklist_idx, fourth_idx, fifth_idx, para_end = _gate_safety_item_anchors(forged)
    assert not (checklist_idx < fourth_idx < fifth_idx < para_end), (
        "the paragraph-boundary anchor must reject ⑤ once it has been relocated outside the "
        "mandatory checklist's own paragraph — if this assertion fails, the anchor has "
        "regressed back into round1's tautological ordering-only check"
    )


def test_orca_evaluate_requires_gate_safety_judgment_in_review():
    text = _read_skill("orca-evaluate")
    checklist_idx, fourth_idx, fifth_idx, para_end = _gate_safety_item_anchors(text)
    assert checklist_idx < fourth_idx < fifth_idx < para_end, (
        "orca-evaluate §3 must add the gate-safety judgment instruction as item ⑤ inside the "
        "reviewer's mandatory checklist enumeration (before the enumeration's own paragraph "
        "ends), not as a trailing sentence relocated outside it"
    )
    # The ⑤ segment itself must use imperative language, not a soft recommendation.
    fifth_segment = text[fifth_idx:para_end]
    assert "지시한다" in fifth_segment or "요구한다" in fifth_segment, (
        "orca-evaluate §3's ⑤ item must be phrased as an instruction/requirement, not advice"
    )


def test_orca_evaluate_gate_safety_examples_are_non_exhaustive():
    text = _read_skill("orca-evaluate")
    _, _, fifth_idx, para_end = _gate_safety_item_anchors(text)
    assert "비망라적" in text[fifth_idx:para_end], (
        "orca-evaluate §3's ⑤ item must mark its example category list as non-exhaustive, so it "
        "cannot calcify into the static path list AC1 forbids"
    )


def test_orca_evaluate_gate_safety_mitigates_tier_conflation():
    text = _read_skill("orca-evaluate")
    _, _, fifth_idx, para_end = _gate_safety_item_anchors(text)
    segment = text[fifth_idx:para_end]
    assert "Critical" in segment or "Important" in segment, (
        "orca-evaluate §3's ⑤ item must require an explicit finding/severity when a gate-safety "
        "concern cannot be fully cleared, so a small gate-integrity diff choosing a cheap "
        "reviewer tier doesn't silently waive scrutiny"
    )
    assert "escalation" in segment or "에스컬레이션" in segment, (
        "orca-evaluate §3's ⑤ item must route an unresolved gate-safety concern toward the "
        "existing FAIL/ESCALATE path"
    )


def _section_3_text(full_text: str) -> str:
    # §1 (Contract review) deliberately keeps the fixed-strong-model placeholder — only §3's own
    # copy of it must change. Scoping to §3's own section avoids a false failure against §1.
    start = full_text.index("## 3. Diff 리뷰")
    end = full_text.index("## 4.", start)
    return full_text[start:end]


def test_orca_evaluate_review_model_selection_is_dynamic_not_fixed_high_risk():
    text = _read_skill("orca-evaluate")
    section_3 = _section_3_text(text)
    assert "select_reviewer" in section_3, (
        "orca-evaluate §3 must delegate reviewer selection to select_reviewer.py"
    )
    assert "<강한 reasoning provider의 launch 문법 — provider 문서에서 resolve>" not in section_3, (
        "orca-evaluate §3's spawn point must not stay a fixed strong-model placeholder"
    )
    assert "일부러 다른 모델을 쓰는 것" not in section_3, (
        "orca-evaluate §3 must not keep the stale 'deliberately different model' framing that "
        "implied a fixed High-Risk model regardless of diff size"
    )
    assert "하드 요구사항은 없다" in section_3 or "하드 요구사항이 없다" in section_3, (
        "orca-evaluate §3 must state that reviewer != generator is not a hard requirement"
    )


def _reviewer_json_call_text(section_3: str) -> str:
    # Scope to the actual select_reviewer.py invocation, not just "somewhere in §3" — an ordinary
    # refactor can extract the --high-risk-signal flag into an earlier variable and then simply not
    # reference it at the call site, leaving the substring present elsewhere in §3 (e.g. in the now
    # dead extracted variable) while the flag itself is never passed.
    start = section_3.index('reviewer_json="$(')
    end = section_3.index("\nreviewer_provider=", start)
    return section_3[start:end]


def test_orca_evaluate_high_risk_signal_wired_to_reviewer_selection():
    text = _read_skill("orca-evaluate")
    section_3 = _section_3_text(text)
    # "migration_files_present" and "--high-risk-signal" both also appear in this section's prose
    # (explaining *why* the wiring exists), so a plain substring check on those names would stay
    # green even if the actual code lines were deleted. Anchor on code-only substrings instead.
    assert "${#migration_files[@]}" in section_3, (
        "orca-evaluate §3 must keep computing migration_files_present from the migration_files "
        "array so a small destructive-migration diff isn't silently dropped back to the lowest "
        "reviewer tier"
    )
    assert "migration_files_present=true" in section_3, (
        "orca-evaluate §3 must keep the migration_files_present=true assignment itself, not just "
        "the array-length test that feeds it — inlining that test into the surrounding `if` "
        "condition is an ordinary refactor that can drop this assignment while leaving the "
        "array-length substring (and this test's other assertion) intact"
    )
    assert "echo --high-risk-signal" in _reviewer_json_call_text(section_3), (
        "orca-evaluate §3's select_reviewer.py invocation must itself reference --high-risk-signal "
        "wiring — extracting the flag into an earlier variable and forgetting to use it at the call "
        "site would leave the substring present elsewhere in §3 while the flag is never passed"
    )


def test_orca_evaluate_preserves_evaluator_separation_intent():
    text = _read_skill("orca-evaluate")
    # Removing "일부러 다른 모델을 쓰는 것" must not delete the one sentence in §3 saying the
    # reviewer must differ from this evaluator session (Gemini) itself — a different concern from
    # reviewer != generator, and the one round1 found at risk of accidental deletion.
    assert "evaluator 세션(Gemini)" in text, (
        "orca-evaluate §3 must keep stating the reviewer must be a different model from this "
        "evaluator session (Gemini) itself, not just 'fresh context' in the abstract"
    )


def test_orca_evaluate_codex_availability_is_runtime_checked_not_a_permanent_ban():
    text = _read_skill("orca-evaluate")
    assert "영구적으로 쓸 수 없다" not in text, (
        "orca-evaluate must not hardcode a permanent Codex ban"
    )
    assert "--no-codex-available" in text, (
        "orca-evaluate §3 must document the runtime retry/fallback mechanism for Codex spawn failure"
    )
    assert "사용자가 알려준" in text, (
        "orca-evaluate §3 must treat this session's user-provided information as the primary "
        "signal for Codex availability, not just `command -v codex`"
    )


def test_orca_evaluate_contract_review_no_longer_cites_section_3():
    text = _read_skill("orca-evaluate")
    # §1's own reasoning for using a fixed strong model must not lean on §3 anymore, since §3's
    # model choice is now dynamic while §1 stays fixed-strong for an independent reason.
    assert "§3 code-reviewer와 같은 이유로" not in text, (
        "orca-evaluate §1 must justify its fixed strong-model choice on its own terms, not by "
        "pointing at §3 (which no longer uses a fixed strong model)"
    )


def test_orca_workflow_has_no_protected_static_gate():
    text = _read_skill("orca-workflow")
    for term in ("PROTECTED_ESCALATE", "protected_paths.py", "lifecycle-gate.toml"):
        assert term not in text, (
            f"orca-workflow must not reintroduce the discarded static PROTECTED gate ('{term}') "
            "— issue #24 was redesigned around reviewer judgment instead"
        )


def test_select_reviewer_script_exists():
    assert (SKILLS_DIR / "orca-evaluate" / "scripts" / "select_reviewer.py").is_file(), (
        "orca-evaluate/scripts/select_reviewer.py is missing"
    )


# ---------------------------------------------------------------------------
# Log restructure invariants (date-partitioned assignments/waves logs, the
# shared logging.md doc, and the per-terminal term-<handle>.jsonl transcript).
# ---------------------------------------------------------------------------

LOG_RESTRUCTURE_FILES = NEW_SKILLS + ["logging.md"]
BARE_UNDATED_LOG_PATHS = ["logs/assignments.jsonl", "logs/waves.jsonl"]


def _read_log_restructure_file(name: str) -> str:
    if name == "logging.md":
        return (WORKFLOWS_DIR / "logging.md").read_text()
    return _read_skill(name)


@pytest.mark.parametrize("name", LOG_RESTRUCTURE_FILES)
def test_no_bare_undated_assignments_or_waves_path(name):
    # Bare "waves.jsonl"/"assignments.jsonl" (no "logs/" prefix) still appears legitimately in
    # logging.md's own explanatory prose (e.g. "instead of the fixed `waves.jsonl`") — this
    # assertion is scoped to the exact "logs/..." path a copy-pasted command would use, which must
    # always carry a date suffix now.
    text = _read_log_restructure_file(name)
    for term in BARE_UNDATED_LOG_PATHS:
        assert term not in text, (
            f"{name}: found un-dated log path '{term}' — assignments/waves logs must be "
            "date-suffixed (assignments-<date>.jsonl / waves-<date>.jsonl), never the old fixed name"
        )


_DISPATCH_INJECT_RE = re.compile(r"orca orchestration dispatch --task .*? --inject --json")


def _dispatch_positions(text: str) -> list[int]:
    return [m.start() for m in _DISPATCH_INJECT_RE.finditer(text)]


def _forward_window(text: str, pos: int, max_lines: int = 15) -> str:
    """Bounded forward window from a dispatch site: up to max_lines lines, truncated early at the
    next closing fence (```) so the window can't accidentally swallow unrelated later blocks."""
    tail = text[pos:]
    lines = tail.splitlines()
    window = "\n".join(lines[: max_lines + 1])
    fence_idx = window.find("\n```")
    if fence_idx != -1:
        window = window[:fence_idx]
    return window


def _evaluate_section0_span(text: str) -> tuple[int, int]:
    start = text.index("## 0.")
    end = text.index("## 1.")
    return start, end


def test_dispatch_site_count_and_section0_exception_shape():
    """Structural guard on the exception itself: orca-evaluate's §0 launch block dispatches to a
    coding-agent terminal but duplicates orca-workflow's owning dispatch site and has no
    log-writing code of its own, so it's the one documented case allowed to skip the logging.md
    pointer. This pins both the total dispatch-site count and that the exception matches exactly
    one site — so a future regression at evaluate's §2/§3 dispatch sites (which must have a
    pointer) can't hide by being silently absorbed into a looser "allow any one miss" check."""
    total = 0
    excluded = 0
    for name in NEW_SKILLS:
        text = _read_skill(name)
        positions = _dispatch_positions(text)
        total += len(positions)
        if name == "orca-evaluate":
            start, end = _evaluate_section0_span(text)
            excluded += sum(1 for pos in positions if start <= pos < end)
    assert total == 6, (
        f"expected 6 `dispatch --task ... --inject` sites across the three SKILL.md files "
        f"combined, found {total}"
    )
    assert excluded == 1, (
        f"expected exactly 1 dispatch site inside orca-evaluate's §0 (the documented exception "
        f"— it duplicates orca-workflow's dispatch, no log-writing code of its own), found {excluded}"
    )


@pytest.mark.parametrize("name", NEW_SKILLS)
def test_dispatch_sites_are_followed_by_logging_pointer(name):
    text = _read_skill(name)
    positions = _dispatch_positions(text)
    if name == "orca-evaluate":
        section0_start, section0_end = _evaluate_section0_span(text)
    for pos in positions:
        if name == "orca-evaluate" and section0_start <= pos < section0_end:
            continue  # documented exception — see test_dispatch_site_count_and_section0_exception_shape
        window = _forward_window(text, pos)
        assert "logging.md" in window, (
            f"{name}: `dispatch --inject` site at char offset {pos} has no logging.md pointer "
            "comment within the following ~15 lines (or before the block's closing fence)"
        )


def test_orca_task_runner_every_close_preceded_by_read_in_same_block():
    """This is the exact invariant C1 violated: a fenced block that closes a subtask terminal
    without ever reading it first destroys the scrollback (and the only chance to log `recv`)
    permanently. Scoped to fenced bash blocks so an unrelated close elsewhere in prose can't
    trigger a false positive."""
    text = _read_skill("orca-task-runner")
    checked_any = False
    for m in re.finditer(r"```bash\n(.*?)\n```", text, re.S):
        block = m.group(1)
        if "orca terminal close" in block:
            checked_any = True
            assert "orca terminal read" in block, (
                "orca-task-runner: a fenced block calls `orca terminal close` without a "
                "preceding `orca terminal read` in the same block"
            )
    assert checked_any, "expected at least one `orca terminal close` block in orca-task-runner"


def test_orca_terminal_read_counts_per_skill_file():
    """Per-file counts, not a combined total — a combined "exactly one across all three files"
    would already be satisfied by orca-evaluate's pre-existing §2 agent-e2e completion read alone,
    so it wouldn't actually catch C1 (task-runner's read being silently dropped). Counting per
    file, and requiring task-runner's count to be exactly 1, is what would have caught it."""
    expected = {"orca-task-runner": 1, "orca-evaluate": 1, "orca-workflow": 0}
    for name, count in expected.items():
        text = _read_skill(name)
        actual = len(re.findall(r"orca terminal read\b", text))
        assert actual == count, (
            f"{name}: expected {count} 'orca terminal read' occurrence(s), found {actual}"
        )


def test_spawn_failures_has_orca_restart_retry_row():
    text = (WORKFLOWS_DIR / "spawn-failures.md").read_text()
    assert "Could not connect to the running Orca app" in text
    assert "Orca is not running. Run 'orca open' first." in text
    assert "orca_call_with_retry" in text
    assert "#42" in text


def _bare_wrapped_call_line_numbers(text: str) -> list[int]:
    """Line numbers (1-indexed) where an orca terminal-create/task-create/dispatch call appears
    without 'orca_call_with_retry' on the same or immediately preceding line."""
    patterns = (
        "orca terminal create",
        "orca orchestration task-create --spec",
        "orca orchestration task-list",
        "orca orchestration dispatch --task",
    )
    lines = text.splitlines()
    bare = []
    for i, line in enumerate(lines):
        if any(pat in line for pat in patterns):
            window = "\n".join(lines[max(0, i - 1) : i + 1])
            if "orca_call_with_retry" not in window:
                bare.append(i + 1)
    return bare


@pytest.mark.parametrize("name", NEW_SKILLS)
def test_no_bare_wrapped_call_sites(name):
    text = _read_skill(name)
    bare = _bare_wrapped_call_line_numbers(text)
    assert bare == [], (
        f"{name}: orca terminal create/task-create/dispatch call(s) not wrapped by "
        f"orca_call_with_retry at line(s) {bare}"
    )


EXPECTED_RETRY_WRAP_COUNTS = {
    "orca-workflow": 6,
    "orca-task-runner": 6,
    "orca-evaluate": 10,
}


_RETRY_INVOCATION_LINE_RE = re.compile(r'^orca_call_with_retry "', re.M)


@pytest.mark.parametrize(("name", "expected"), EXPECTED_RETRY_WRAP_COUNTS.items())
def test_orca_call_with_retry_count_per_skill(name, expected):
    actual = len(_RETRY_INVOCATION_LINE_RE.findall(_read_skill(name)))
    assert actual == expected, f"{name}: expected {expected} orca_call_with_retry invocations, found {actual}"


@pytest.mark.parametrize("name", NEW_SKILLS)
def test_sources_retry_wrapper_script(name):
    text = _read_skill(name)
    assert "source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh" in text, (
        f"{name}: must source orca_call_with_retry.sh before using the wrapper function"
    )


def test_orca_workflow_section0_notes_retry_wrapping():
    text = _read_skill("orca-workflow")
    section0_start = text.index("## 0.")
    section0_end = text.index("## 1.")
    section0 = text[section0_start:section0_end]
    assert "orca_call_with_retry" in section0 and "#42" in section0


def test_orca_task_runner_subtask_spec_required_items_includes_retry_wrapping():
    text = _read_skill("orca-task-runner")
    checklist_idx = text.index("subtask spec 필수 항목")
    sixth_idx = text.index("⑥", checklist_idx)
    seventh_idx = text.index("⑦", sixth_idx)
    assert checklist_idx < sixth_idx < seventh_idx
    para_end = text.index("\n\n", checklist_idx)
    seventh_segment = text[seventh_idx:para_end]
    assert "orca_call_with_retry" in seventh_segment


def test_orca_task_runner_section0_notes_retry_wrapping():
    text = _read_skill("orca-task-runner")
    section0_start = text.index("## 0.")
    section0_end = text.index("## 1.")
    section0 = text[section0_start:section0_end]
    assert "orca_call_with_retry" in section0 and "#42" in section0
