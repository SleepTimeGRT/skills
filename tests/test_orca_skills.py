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

NEW_SKILLS = ["orca-workflow", "orca-task-runner", "orca-evaluate", "orca-retro"]
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
    # bd6a69f moved the "not a hard requirement" statement out of §3 into the reviewer-selection
    # reference — the invariant now lives there, reachable via §3's pointer.
    assert "references/reviewer-selection.md" in section_3, (
        "orca-evaluate §3 must point at references/reviewer-selection.md for selection policy "
        "details (candidate pool, exclusions, high-risk override)"
    )
    reviewer_selection = (
        SKILLS_DIR / "orca-evaluate" / "references" / "reviewer-selection.md"
    ).read_text()
    assert "not a hard requirement" in reviewer_selection, (
        "reviewer-selection.md must keep stating that a reviewer differing from the generator "
        "is a diversity benefit, not a hard requirement"
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
    # b808d3d retired the agy(Gemini)-pinned evaluator session; the separation invariant survives
    # in provider-neutral form and must not be lost to further rewording: the §3 reviewer spawn
    # stays a separate session from this evaluator session, and the fallback keeps refusing
    # self-judgment — a different concern from reviewer != generator.
    assert "이 evaluator 세션과는 별개 세션" in text, (
        "orca-evaluate §3 must keep stating the code reviewer is a separate session from this "
        "evaluator session itself, not just 'fresh context' in the abstract"
    )
    assert "같은 세션이 스스로를 판단하지 않도록" in text, (
        "orca-evaluate's fallback must keep the no-self-judgment clause for the §1/§3 coding "
        "agents when the orca runtime is down"
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
# Matches a *write* redirect (`>>` or `>`) targeting the old fixed, un-dated file name --
# the actual bug this test guards against (a copy-pasted write silently un-partitioning the log).
# Deliberately does not match bare substring occurrences: both logging.md's own "Reading across
# dates" recipe (§1, issue #55) and orca-retro §1 correctly `cat`/`-f`-check
# "$logs/assignments.jsonl" (the pre-date-partition legacy file, kept around on purpose) before
# falling back to the dated files -- that read is required backward compatibility, not a bug.
_UNDATED_LOG_WRITE_RE = re.compile(r">>?\s*\"[^\"]*\b(?:assignments|waves)\.jsonl\"")


def _read_log_restructure_file(name: str) -> str:
    if name == "logging.md":
        return (WORKFLOWS_DIR / "logging.md").read_text()
    return _read_skill(name)


@pytest.mark.parametrize("name", LOG_RESTRUCTURE_FILES)
def test_no_bare_undated_assignments_or_waves_path(name):
    text = _read_log_restructure_file(name)
    matches = _UNDATED_LOG_WRITE_RE.findall(text)
    assert not matches, (
        f"{name}: found a write redirect into an un-dated log path {matches} — assignments/waves "
        "log writes must be date-suffixed (assignments-<date>.jsonl / waves-<date>.jsonl), never "
        "the old fixed name"
    )


# Matches either the low-level `dispatch --task ... --inject` verb (still used at sites with
# no wait-loop problem: orca-workflow §1d retro, the initial §2a task-runner/evaluator dispatch)
# or its supervised replacement `worker-start --task ...` (orca-task-runner §5's wave dispatch,
# orca-workflow §2a's round-2+ relay dispatch — docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md).
# [\s\S]*? spans the backslash-continued multi-line worker-start invocation; non-greedy so it
# stops at the nearest following --json rather than swallowing later, unrelated blocks.
_DISPATCH_INJECT_RE = re.compile(
    r"orca orchestration (?:dispatch --task .*? --inject --json|worker-start --task[\s\S]*?--json)"
)


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
    assert total == 8, (
        f"expected 8 `dispatch --task ... --inject` sites across the NEW_SKILLS family's "
        f"SKILL.md files combined (7 pre-#64 + 1 new round-2+ relay site in orca-workflow §2a), "
        f"found {total}"
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


_BASH_FENCE_RE = re.compile(r"^[ \t]*```bash\n(.*?)^[ \t]*```", re.M | re.S)


def _bare_wrapped_call_line_numbers(text: str) -> list[int]:
    """Line numbers (1-indexed) where an orca terminal-create/task-create/dispatch call appears
    inside a ```bash fenced block without 'orca_call_with_retry' on the same or immediately
    preceding line. Scoped to fenced code on purpose — a prose sentence that merely mentions one of
    these commands (e.g. describing a manual orphan-recovery diagnostic step) is not a call site
    this plan wraps, and scanning the whole file would false-positive on such mentions."""
    patterns = (
        "orca terminal create",
        "orca orchestration task-create --spec",
        "orca orchestration task-list",
        "orca orchestration dispatch --task",
        "orca orchestration worker-start --task",
    )
    bare = []
    for m in _BASH_FENCE_RE.finditer(text):
        block_start_line = text[: m.start()].count("\n") + 2
        block_lines = m.group(1).splitlines()
        for j, line in enumerate(block_lines):
            if any(pat in line for pat in patterns):
                window = "\n".join(block_lines[max(0, j - 1) : j + 1])
                if "orca_call_with_retry" not in window:
                    bare.append(block_start_line + j)
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
    "orca-workflow": 12,  # +3 for issue #64's round-2+ relay: task-list (reportPath lookup), task-create, worker-start
    "orca-task-runner": 6,
    "orca-evaluate": 10,
}


_RETRY_INVOCATION_LINE_RE = re.compile(r'^orca_call_with_retry "', re.M)


@pytest.mark.parametrize(("name", "expected"), EXPECTED_RETRY_WRAP_COUNTS.items())
def test_orca_call_with_retry_count_per_skill(name, expected):
    actual = len(_RETRY_INVOCATION_LINE_RE.findall(_read_skill(name)))
    assert actual == expected, f"{name}: expected {expected} orca_call_with_retry invocations, found {actual}"


def test_orca_workflow_documents_round2_relay_protocol():
    """Issue #64: §2a must name the actual mechanism (new task-create per round, event-driven wait
    via self-recovery.md, dispatched to the same terminal handle via worker-start) rather than
    leaving round 2+ undocumented. Pins the load-bearing phrases so a future rewrite can't silently
    reintroduce task-list polling as the primary wait mechanism or task_id reuse.

    docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md supersedes this test's
    original 'must poll task-list, not terminal read' assertion -- that assertion enforced the
    now-disproven check-queue-miss claim."""
    text = _read_skill("orca-workflow")
    assert "already has an active dispatch" in text, (
        "must document the verified error a premature round-2 dispatch produces"
    )
    assert "is dispatched; only ready tasks can be dispatched" in text, (
        "must document why reusing the round-1 task_id is impossible"
    )
    assert "self-recovery.md" in text, "round-2+ completion wait must point at the shared event-driven loop"
    assert "reportPath" in text, (
        "must name the path-only relay channel (task-list result.reportPath) -- still needed as a "
        "one-shot lookup after worker_done, since the event payload itself doesn't carry it"
    )
    assert "`--deps`는 걸지" in text, "must explicitly instruct against --deps between round tasks"


def test_orca_workflow_round2_uses_worker_start_not_raw_dispatch():
    """docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md §3/§6b: only the
    round-2+ dispatch site migrates to worker-start -- the initial §2a task-runner/evaluator
    dispatch and §1d retro stay on raw dispatch --inject (no polling problem there)."""
    text = _read_skill("orca-workflow")
    round2_idx = text.index("**Contract 협상 relay — 라운드 2+")
    round2_end = text.index("## 3.", round2_idx)
    round2_section = text[round2_idx:round2_end]
    assert "worker-start" in round2_section
    assert "task-list --json` 폴링(20-30s" not in text, (
        "the old 20-30s polling bullet must be gone, not merely superseded in prose"
    )


def test_orca_workflow_creates_own_run_in_section0():
    text = _read_skill("orca-workflow")
    section0_start = text.index("## 0.")
    section0_end = text.index("## 1.")
    section0 = text[section0_start:section0_end]
    assert "run-create" in section0, (
        "orca-workflow §0 must create and bind its own Run once per invocation, distinct from "
        "whatever Run orca-task-runner/orca-evaluate create for their own internal fan-out"
    )


def test_orca_workflow_round2_relay_has_no_deploy_placeholder():
    """The production incident this issue traces to used a `terminal-send-fallback` task_id placeholder
    — the fixed procedure must never reintroduce it."""
    text = _read_skill("orca-workflow")
    assert "terminal-send-fallback" not in text


def test_logging_no_longer_flags_round2_relay_as_unresolved():
    """Issue #64 is resolved as of this plan — logging.md must not keep pointing a future reader at it
    as an open design question, nor keep the disproven "task 재사용" prediction, nor the ad hoc
    'terminal-send-fallback' placeholder the unresolved state produced in production."""
    text = (WORKFLOWS_DIR / "logging.md").read_text()
    assert "아직 미해결 설계 질문" not in text
    assert "terminal-send-fallback" not in text
    assert "기존 task 재사용 방식으로 확정하면" not in text


def test_orca_task_runner_states_contract_round_is_a_new_dispatch_not_a_wait():
    """Issue #64: §1's "반려되면 수정해서 다시 제안한다" narrates the whole multi-dispatch protocol in one
    sentence — a fresh dispatched worker could misread it as "wait/poll in this same turn" instead of "end
    the turn; the next round arrives as a new dispatch." No new orca command is needed here (dispatch
    --inject already auto-injects the full worker_done protocol on every call) — only this one sentence
    of turn-boundary prose."""
    text = _read_skill("orca-task-runner")
    assert "이번 턴을 끝낸다" in text, (
        "orca-task-runner §1 must clarify that each contract round ends the current turn "
        "(worker_done, per the injected preamble) rather than waiting/polling in-turn for the next round"
    )


def test_orca_evaluate_states_contract_round_is_a_new_dispatch_not_a_wait():
    """Mirrors test_orca_task_runner_states_contract_round_is_a_new_dispatch_not_a_wait for the
    evaluator side of the same round."""
    text = _read_skill("orca-evaluate")
    assert "이번 턴을 끝낸다" in text, (
        "orca-evaluate §1 must clarify that relaying the verdict ends the current turn "
        "(worker_done, per the injected preamble) rather than waiting/polling in-turn for the next round"
    )


# Scoped to the skills that actually invoke the wrapper, not the whole NEW_SKILLS family —
# orca-retro makes no `orca` CLI calls, so a `source` line there would be dead prose. Per-block
# enforcement lives in test_every_retry_invocation_block_sources_the_wrapper (correctly conditional).
@pytest.mark.parametrize("name", list(EXPECTED_RETRY_WRAP_COUNTS))
def test_sources_retry_wrapper_script(name):
    text = _read_skill(name)
    assert "source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh" in text, (
        f"{name}: must source orca_call_with_retry.sh before using the wrapper function"
    )


DISPATCH_VERIFY_FILE = "dispatch-verify.md"
SELF_RECOVERY_FILE = "self-recovery.md"


def _read_workflows_file(name: str) -> str:
    path = WORKFLOWS_DIR / name
    assert path.is_file(), f"orca-workflows/{name} missing"
    return path.read_text()


def test_dispatch_verify_file_documents_bounded_tail_diff_and_escalation():
    """issue #43: dispatch --inject can land text without Enter registering, and a single
    `terminal read` can't tell that apart from normal post-completion idle. This pins the new
    shared reference file's key content so a future edit can't silently drop the bounded-wait
    check or the escalation path back to spawn-failures.md."""
    text = _read_workflows_file(DISPATCH_VERIFY_FILE)
    assert "tail" in text, "must describe comparing terminal tail output"
    assert "sleep 15" in text, "bounded wait window must be a concrete value, not a placeholder"
    assert "spawn-failures.md" in text, "must document escalation to the existing spawn-failure procedure"
    assert "❯" not in text and "⏺" not in text, (
        "must stay provider-agnostic — no Claude-Code-specific UI markers"
    )
    assert "worker-start" in text, (
        "docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md: the same "
        "unsubmitted-draft failure mode was confirmed live under worker-start, not only raw "
        "dispatch --inject — the framing sentence must say so"
    )


def test_self_recovery_file_documents_principle_and_loop():
    """docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md: pins the load-bearing
    content of the new shared self-recovery reference so a future edit can't silently drop the
    native-primitives principle, the retry budget, the --ack requirement, or the worker-release
    rejection note."""
    text = _read_workflows_file(SELF_RECOVERY_FILE)
    assert "worker-abandon" in text and "--retry-of" in text, (
        "must document the fence-then-retry recovery mechanism"
    )
    assert "check --wait" in text and "--ack" in text, (
        "must document the event-driven wait and the mandatory ack"
    )
    assert "Retry budget: 2" in text or "재시도 예산" in text, (
        "must state a concrete retry budget, not leave it open"
    )
    assert "worker-release" in text and "external_terminal" in text, (
        "must record why worker-release was rejected for this repo's dispatch shape"
    )
    assert "last_heartbeat_at" in text, (
        "must record that heartbeat was observed null and is not relied on as a liveness signal"
    )
    assert "3600000" in text, (
        "must state the exact 1-hour timeout constant (3600000ms) the user specified, not a rounded "
        "or prose-only restatement"
    )


def test_self_recovery_file_states_no_process_action_for_abandon():
    """worker-abandon's whole value proposition is that it is non-destructive — pin the exact
    observed evidence so a future edit can't quietly turn this into a claim we didn't verify."""
    text = _read_workflows_file(SELF_RECOVERY_FILE)
    assert 'processAction:"none"' in text, (
        "must pin the exact live-observed field:value, not just the word 'none' anywhere in the file"
    )


@pytest.mark.parametrize("name", NEW_SKILLS)
def test_every_retry_invocation_block_sources_the_wrapper(name):
    """A file-wide 'source appears somewhere' check (the test above) is not sufficient: separate
    ```bash fenced blocks in these docs represent separate shell invocations/spawned terminals, so
    a function sourced in one block (e.g. orca-evaluate's §0) is not available in another (§1/§2/§3)
    — each self-contained block that calls orca_call_with_retry must source it itself."""
    text = _read_skill(name)
    for m in _BASH_FENCE_RE.finditer(text):
        block = m.group(1)
        if _RETRY_INVOCATION_LINE_RE.search(block):
            assert "source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh" in block, (
                f"{name}: a fenced block using orca_call_with_retry (starting near char offset "
                f"{m.start()}) is missing its own source line"
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


def test_orca_evaluate_worker_specs_instruct_retry_wrapping():
    text = _read_skill("orca-evaluate")
    for marker in ("제안서 경로", "diff 절대경로"):
        idx = text.index(marker)
        end = text.index('>"', idx)
        segment = text[idx:end]
        assert "orca_call_with_retry" in segment, (
            f"orca-evaluate: spec_text placeholder starting near {marker!r} must instruct the "
            "spawned worker to wrap its own orchestration replies in orca_call_with_retry"
        )


def test_orca_evaluate_section0_notes_retry_wrapping():
    text = _read_skill("orca-evaluate")
    section0_start = text.index("## 0.")
    section0_end = text.index("## 1.")
    section0 = text[section0_start:section0_end]
    assert "orca_call_with_retry" in section0 and "#42" in section0


def test_agents_md_orca_workflows_note_mentions_scripts_dir():
    text = (REPO_ROOT / "AGENTS.md").read_text()
    idx = text.index("orca-workflows/` deploy path (decision, #22)")
    remainder = text[idx:]
    section_end_offset = remainder.index("\n## ") if "\n## " in remainder else len(remainder)
    section = remainder[:section_end_offset]
    assert "scripts/" in section and "orca_call_with_retry.sh" in section, (
        "AGENTS.md's orca-workflows/ deploy-path note must mention the new scripts/ directory "
        "now that it holds an executable helper, not just reference docs"
    )


@pytest.mark.parametrize("name", NEW_SKILLS)
def test_dispatch_sites_are_followed_by_dispatch_verify_pointer(name):
    """Same shape as test_dispatch_sites_are_followed_by_logging_pointer — the verify pointer
    must appear at every dispatch --inject site except orca-evaluate's documented §0 duplicate.
    Written before any SKILL.md is touched, so this starts red for all three names; Tasks 2-4
    turn it green one skill at a time (verify with `-k` scoped to that skill's name)."""
    text = _read_skill(name)
    positions = _dispatch_positions(text)
    if name == "orca-evaluate":
        section0_start, section0_end = _evaluate_section0_span(text)
    for pos in positions:
        if name == "orca-evaluate" and section0_start <= pos < section0_end:
            continue  # documented exception — see test_dispatch_site_count_and_section0_exception_shape
        window = _forward_window(text, pos)
        assert "dispatch-verify.md" in window, (
            f"{name}: `dispatch --inject` site at char offset {pos} has no dispatch-verify.md "
            "pointer comment within the following ~15 lines (or before the block's closing fence)"
        )


def test_spawn_failures_has_dispatch_inject_unsent_row():
    """issue #43's failure mode has no literal terminal-output substring to grep, and no reliable
    retrospective log-based one either (a `sent` with no following `recv` is by-design normal at
    most dispatch sites) — detection only happens live, via dispatch-verify.md. This pins that the
    new row exists, points at dispatch-verify.md as the actual detection mechanism, and is
    explicitly flagged as a signature-less exception to the table's normal literal-substring
    convention (so a future reader isn't confused about why this row doesn't look like the
    others)."""
    text = _read_workflows_file("spawn-failures.md")
    assert "#43" in text, "must link the new row to issue #43"
    assert "dispatch-verify.md" in text, "the row's fix column must point at the new procedure"
    assert "no-signature" in text, (
        "must explicitly flag this row as a signature-less exception to the "
        "literal-grep-substring convention"
    )
    header_count = text.count("| `failure_signature` (grep substring) |")
    assert header_count == 1, (
        f"expected exactly one 'Known signatures' table (one header line), found {header_count} "
        "— a regression could reintroduce #43 as a second, separate table instead of a row in the existing one"
    )


# --- orca-retro: epic-end skill-defect feedback loop (layer-3) ---


def test_logging_outcome_enum_includes_retro_values():
    text = (WORKFLOWS_DIR / "logging.md").read_text()
    m = re.search(r'"outcome":"<([^>]+)>"', text)
    assert m, "outcome enum line missing in logging.md"
    assert "RETRO_DONE" in m.group(1) and "RETRO_FAIL" in m.group(1), (
        "outcome enum must document the epic-retro results; filing undocumented "
        "values is exactly the drift the retro loop hunts"
    )


def test_logging_meta_records_version_fields():
    text = (WORKFLOWS_DIR / "logging.md").read_text()
    meta_section = text[text.index('### `meta`') : text.index('### `sent`')]
    for key in ("skill_version", "orca_workflows_commit", "orca_app_version"):
        assert key in meta_section, (
            f"logging.md meta recipe missing version field: {key} — issues filed "
            "against a term log can't be pinned to the version that produced the bug"
        )
    assert ".installed-version.json" in meta_section, (
        "meta recipe must source skill_version from the deployed commit-pin file"
    )
    assert "orca status --json" in meta_section, (
        "meta recipe must source orca_app_version from a live orca status call"
    )
    assert "rev-parse HEAD" in meta_section, (
        "meta recipe must source orca_workflows_commit from the live orca-workflows checkout"
    )


def test_orca_retro_files_issues_never_edits_skills():
    text = _read_skill("orca-retro")
    assert "gh issue create" in text, "output channel must be GitHub issues"
    assert "직접 수정하지 않는다" in text, (
        "orca-retro must state it never edits skill files itself"
    )


def test_orca_retro_has_four_defect_lenses():
    text = _read_skill("orca-retro")
    for marker in ("스키마 위반", "반복 FAIL", "ESCALATE", "spawn-failure"):
        assert marker in text, f"orca-retro: defect lens marker missing: {marker}"


def test_orca_retro_evidence_bar_and_issue_cap():
    text = _read_skill("orca-retro")
    assert "원문 인용" in text, "evidence-quote requirement missing"
    assert "최대 3개" in text, "per-epic new-issue cap missing"


def test_orca_retro_dedup_against_open_issues():
    text = _read_skill("orca-retro")
    assert "gh issue list" in text and "--state open" in text, (
        "must check open issues before filing"
    )
    assert "재발 코멘트" in text, "recurrence must become a comment, not a duplicate issue"


def test_orca_retro_schema_lens_scans_unfiltered():
    text = _read_skill("orca-retro")
    assert "issue 필터를 거치지 않고" in text, (
        "lens 1 must scan full dated files — records with a drifted issue field "
        "escape the issue filter"
    )


def test_orca_workflow_runs_retro_after_epic_close():
    text = _read_skill("orca-workflow")
    close_pos = text.index("close_issue(epic-num")
    retro_pos = text.index("orca-retro")
    assert close_pos < retro_pos, (
        "retro must run after close_issue succeeds — running before risks leaving "
        "a fully-done epic open if the coordinator dies mid-retro"
    )


def test_orca_workflow_retro_is_best_effort():
    text = _read_skill("orca-workflow")
    assert "RETRO_FAIL" in text and "RETRO_DONE" in text
    assert "실패시키지 않는다" in text, (
        "retro failures must never fail the workflow"
    )


def test_orca_workflow_premerge_exit_semantics_not_replicated():
    text = _read_skill("orca-workflow")
    # The replicated exit-code table drifted from reality once (#45): a deployed v1 premerge.sh
    # never implements exit 5, and the current template ships it opt-in (MIGRATION_LINT_ENABLED
    # defaults to false). The target repo's script header is the only source of truth.
    for stale in ("5=MIGRATION_ESCALATE", "3=PROTECTED", "4=REVIEW"):
        assert stale not in text, (
            f"orca-workflow must not replicate premerge.sh's exit-code table ('{stale}') — "
            "decode from the target repo's scripts/premerge.sh header comment instead"
        )
    assert "헤더 주석이 정본" in text, (
        "orca-workflow must name the target repo's premerge.sh header comment as the exit-code "
        "source of truth"
    )
    assert "merge policy" in text, (
        "orca-workflow §2d must require checking the repo's merge policy independently of "
        "premerge exit codes before self-merging a migration-touching diff"
    )


def test_sweep_stale_dispatched_script_is_report_only():
    script = WORKFLOWS_DIR / "scripts" / "sweep_stale_dispatched.sh"
    assert script.is_file(), "orca-workflows/scripts/sweep_stale_dispatched.sh missing (#41 janitor)"
    text = script.read_text()
    assert "run-list" in text and "--status dispatched" in text, (
        "sweep must enumerate runs and filter dispatched tasks per run (task-list is run-scoped)"
    )
    assert "task-update" not in text, (
        "sweep is report-only — it must never mutate task state; recovery stays a documented "
        "manual step in orca-task-runner §5"
    )
    assert "SWEEP_IGNORE_FILE" in text, (
        "sweep must support an ignore-list for verified-moot tasks that the Orca CLI cannot "
        "bookkeep (orphaned adopted runs refuse takeover), or every session re-reports them"
    )


def test_orca_task_runner_orphan_result_fallback():
    text = _read_skill("orca-task-runner")
    assert ".orca-orphaned-result-" in text, (
        "orca-task-runner must define the orphan-result file fallback for worker_done sends "
        "that exhaust the retry wrapper (#41)"
    )
    assert "ask" not in text.split("exhausted")[1][:200] or "ask를 포함한 추가" in text, (
        "on exhaustion the worker must not attempt further orchestration calls (ask rides the "
        "same dead transport)"
    )


def test_orca_workflow_runs_stale_dispatched_sweep():
    text = _read_skill("orca-workflow")
    assert "sweep_stale_dispatched.sh" in text, (
        "orca-workflow §0 must run the stale-dispatched sweep at session start so stuck tasks "
        "surface instead of accumulating silently"
    )


def test_orca_task_runner_spawn_template_verbatim_rule():
    text = _read_skill("orca-task-runner")
    assert "verbatim 복사" in text, (
        "orca-task-runner must require spawn commands be copied verbatim from the template — "
        "hand-reassembly dropped/altered flags in a measured case (#40)"
    )
    assert "fallback shell" in text, (
        "orca-task-runner must forbid the bare-fallback-shell + retype spawn path"
    )


def test_spawn_failures_has_round2_relay_rejection_rows():
    """Issue #64's live investigation produced two verified `runtime_error` JSON responses from
    `dispatch`/`task-create` themselves — not a spawned terminal's `terminal read` output, unlike every
    prior row in this table. Pins both signatures, the issue link, and the scoping note distinguishing
    their detection channel from the table's default convention."""
    text = _read_workflows_file("spawn-failures.md")
    sig1 = "is dispatched; only ready tasks can be dispatched"
    sig2 = "already has an active dispatch"
    assert sig1 in text
    assert sig2 in text

    # Verify each signature's row ends with | #64 | (not just any #64 in the file)
    sig1_pos = text.find(sig1)
    assert sig1_pos >= 0, f"signature '{sig1}' not found"
    sig1_row_end = text.find("\n", sig1_pos)
    assert sig1_row_end > 0, "row terminator not found after sig1"
    sig1_row = text[sig1_pos:sig1_row_end]
    assert sig1_row.endswith("| #64 |"), (
        f"sig1 row must end with '| #64 |', but ends with: {sig1_row[-20:]}"
    )

    sig2_pos = text.find(sig2)
    assert sig2_pos >= 0, f"signature '{sig2}' not found"
    sig2_row_end = text.find("\n", sig2_pos)
    assert sig2_row_end > 0, "row terminator not found after sig2"
    sig2_row = text[sig2_pos:sig2_row_end]
    assert sig2_row.endswith("| #64 |"), (
        f"sig2 row must end with '| #64 |', but ends with: {sig2_row[-20:]}"
    )

    assert "calling command's own" in text or "호출 자신의" in text, (
        "must scope-note that these two signatures appear in dispatch/task-create's own --json response, "
        "not a spawned terminal's `terminal read` output (every other row in this table is the latter)"
    )
    header_count = text.count("| `failure_signature` (grep substring) |")
    assert header_count == 1, (
        f"expected exactly one 'Known signatures' table (one header line), found {header_count}"
    )


def test_spawn_failures_known_signatures_table_has_no_internal_blank_lines():
    """Task 5's fix round found and fixed a real GFM table break: a blank line between two rows
    made every row after it render as plain text, not part of the table. Nothing guarded against
    a recurrence — this does."""
    text = _read_workflows_file("spawn-failures.md")
    start = text.index("| `failure_signature` (grep substring) |")
    end = text.index("## Adding a new row")
    lines = text[start:end].splitlines()
    # Trim trailing non-table lines (e.g. the blank line before the next heading) so the span
    # covers exactly the header row through the table's last row — not any later prose.
    while lines and not lines[-1].startswith("|"):
        lines.pop()
    table_span = "\n".join(lines)
    assert "\n\n" not in table_span, (
        "blank line found inside the Known signatures table — this breaks GFM table rendering "
        "for every row after it (issue #64's Task 5 fix round found exactly this bug)"
    )


def test_spawn_failures_active_dispatch_row_points_to_check_wait():
    """docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md supersedes this row's old
    fix text ('poll task-list') -- the row must now describe the event-driven replacement, and must
    not still tell a future reader to poll task-list for this specific failure."""
    text = _read_workflows_file("spawn-failures.md")
    assert "already has an active dispatch" in text
    idx = text.index("already has an active dispatch")
    row_end = text.index("\n", idx)
    row = text[max(0, idx - 200):row_end]
    assert "check --wait" in row, "fix column must now point at the check --wait mechanism"
    assert "poll `task-list`" not in row, (
        "must not still recommend the disproven task-list-polling workaround for this row"
    )


def test_logging_documents_self_recovery_event():
    """docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md: pins the self_recovery
    event schema so a future edit can't silently drop a field the self-recovery.md loop relies on."""
    text = (WORKFLOWS_DIR / "logging.md").read_text()
    assert '"event":"self_recovery"' in text
    for field in ("task_id", "dispatch_id", "terminal", "waited_ms", "terminal_status", "action_taken"):
        assert f'"{field}"' in text, f"self_recovery event must include the {field} field"
    assert "resumed_wait" in text and "retried_enter" in text and "worker_abandon_retry" in text, (
        "must enumerate the action_taken values self-recovery.md's loop can produce"
    )
    assert "waves-<date>.jsonl" in text, (
        "must state orca-task-runner writes this event to its dated waves log"
    )


def test_orca_task_runner_creates_own_run_in_section0():
    text = _read_skill("orca-task-runner")
    section0_start = text.index("## 0.")
    section0_end = text.index("## 1.")
    section0 = text[section0_start:section0_end]
    assert "run-create" in section0, (
        "orca-task-runner §0 must create and bind its own Run once per session, distinct from "
        "whatever Run orca-workflow owns"
    )


def test_orca_task_runner_section5_points_to_self_recovery():
    text = _read_skill("orca-task-runner")
    section5_start = text.index("## 5.")
    section5_end = text.index("## 6.")
    section5 = text[section5_start:section5_end]
    assert "self-recovery.md" in section5
    assert "worker-start" in section5
    assert "체크 큐로 안 잡힐 수 있다" not in text, (
        "retired scheduler reasoning must be deleted outright, not annotated (no-history-in-skills)"
    )
