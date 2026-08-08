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
    assert "Quota check before pinning" in text, (
        "orca-evaluate §3 must source codex_available from model-selection.md's live quota-check "
        "procedure, not a hardcoded default"
    )
    assert "더 최신 정보를 알고 있으면" in text and "덮어쓴다" in text, (
        "orca-evaluate §3 must still let this session's more current information override the "
        "quota check, not just `command -v codex`"
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
    file, and requiring task-runner's count to be exactly 1, is what would have caught it.

    orca-task-runner's total is 2 as of issue #70: one is the original C1 read (subtask impl
    terminal, before close, for recv logging) and the other is the new commit-helper terminal's
    read (checking COMMIT_EXIT status, unrelated to recv logging — a different terminal role
    entirely). Scoping by `--terminal <handle>` placeholder keeps both invariants distinct instead
    of collapsing them into one magic total."""
    expected_by_handle = {
        "orca-task-runner": {"<impl_handle>": 1, "<commit_helper_handle>": 1},
        "orca-evaluate": {"<agent-e2e-handle>": 1},
        "orca-workflow": {},
    }
    expected_total = {"orca-task-runner": 2, "orca-evaluate": 1, "orca-workflow": 0}
    for name, count in expected_total.items():
        text = _read_skill(name)
        actual = len(re.findall(r"orca terminal read\b", text))
        assert actual == count, (
            f"{name}: expected {count} 'orca terminal read' occurrence(s), found {actual}"
        )
    for name, by_handle in expected_by_handle.items():
        text = _read_skill(name)
        for handle, count in by_handle.items():
            actual = text.count(f"orca terminal read --terminal {handle}")
            assert actual == count, (
                f"{name}: expected {count} 'orca terminal read --terminal {handle}' "
                f"occurrence(s), found {actual}"
            )


def test_spawn_failures_has_orca_restart_retry_row():
    text = (WORKFLOWS_DIR / "spawn-failures.md").read_text()
    assert "Could not connect to the running Orca app" in text
    assert "Orca is not running. Run 'orca open' first." in text
    assert "orca_call_with_retry" in text
    assert "#42" in text


def test_spawn_failures_has_broadened_regex_pointer_row():
    """orca-evaluate final review (issue #42 retry): the #42 row's two literals no longer reflect
    the wrapper's full match set after the regex was broadened to 4 keywords, so a pointer row
    must exist directing readers to the script's header comment instead of leaving the table to
    silently under-represent the real match set."""
    text = (WORKFLOWS_DIR / "spawn-failures.md").read_text()
    assert "pointer row" in text
    assert "_ORCA_RETRY_SIGNATURE_RE" in text
    header_count = text.count("| `failure_signature` (grep substring) |")
    assert header_count == 1, (
        f"expected exactly one 'Known signatures' table (one header line), found {header_count}"
    )


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


EXPECTED_RETRY_REQUEST_COUNTS = {
    "orca-workflow": 8,
    "orca-task-runner": 2,
    "orca-evaluate": 6,
}

_RETRY_REQUEST_MUTATING_CALL_RE = re.compile(
    r"orca orchestration (?:task-create|dispatch|worker-start)\b[^\n]*"
    r"(?:\n[ \t]+--[^\n]*)*",  # command may continue on wrapped `\`-continuation lines
)


@pytest.mark.parametrize(("name", "expected"), EXPECTED_RETRY_REQUEST_COUNTS.items())
def test_mutating_call_sites_carry_retry_request(name, expected):
    """AC2: every task-create/dispatch/worker-start invocation must embed its own
    --retry-request "$(uuidgen)" so the server can dedupe a client-side spurious retry
    (issue #73). Scoped to the three flags that --help confirms support it -- terminal create
    does not and is asserted absent below, not required here."""
    text = _read_skill(name)
    calls = _RETRY_REQUEST_MUTATING_CALL_RE.findall(text)
    assert len(calls) == expected, (
        f"{name}: expected {expected} task-create/dispatch/worker-start call sites, found {len(calls)}"
    )
    missing = [c.splitlines()[0] for c in calls if "--retry-request" not in c]
    assert missing == [], f"{name}: call site(s) missing --retry-request: {missing}"


@pytest.mark.parametrize("name", NEW_SKILLS)
def test_terminal_create_never_carries_retry_request(name):
    """orca terminal create --help has no --retry-request flag (confirmed 2026-08-08) -- a
    site that adds it anyway would silently no-op or error depending on CLI strictness, and
    either way signals someone copy-pasted the mutating-call pattern onto the wrong command.
    Scoped to fenced ```bash blocks via the repo's existing _BASH_FENCE_RE (same convention as
    _bare_wrapped_call_line_numbers, tests/test_orca_skills.py:686-711) rather than a loose
    re.S span over the whole file -- round 1's version of this test used `.*?--json` with re.S,
    which over-matches into prose sentences that merely mention 'orca terminal create' (e.g.
    each skill's own §0 note) and would false-positive the moment an unrelated --retry-request
    site landed later in the same file."""
    text = _read_skill(name)
    for m in _BASH_FENCE_RE.finditer(text):
        block_lines = m.group(1).splitlines()
        for j, line in enumerate(block_lines):
            if "orca terminal create" in line:
                window = "\n".join(block_lines[j : j + 4])
                assert "--retry-request" not in window, (
                    f"{name}: 'orca terminal create' must not carry --retry-request (unsupported flag)"
                )


EXPECTED_DISPATCH_POSITIONS = {
    "orca-workflow": 4,
    "orca-task-runner": 1,
    "orca-evaluate": 3,
}


@pytest.mark.parametrize(("name", "expected"), EXPECTED_DISPATCH_POSITIONS.items())
def test_dispatch_inject_positions_not_vacuous(name, expected):
    """Vacuity guard (round-1 rejection root cause): test_dispatch_sites_are_followed_by_*_pointer
    iterate `_dispatch_positions(text)` and assert something about each element -- an empty list
    makes the loop body never execute and the test passes having verified nothing. This pins the
    per-skill count so a future edit that collapses positions to 0 (e.g. by breaking
    _DISPATCH_INJECT_RE's `--inject --json` adjacency requirement, exactly what round 1 of this
    proposal did before this fix) fails loudly here instead of the pointer tests going green
    for the wrong reason. Counts match today's pre-#73 baseline exactly -- this proposal's
    call-site edits are additive-only and must not change how many sites _DISPATCH_INJECT_RE
    matches."""
    text = _read_skill(name)
    positions = _dispatch_positions(text)
    assert len(positions) == expected, (
        f"{name}: expected {expected} _DISPATCH_INJECT_RE match(es), found {len(positions)} "
        f"-- a drop to 0 would make the logging/dispatch-verify pointer tests vacuously pass"
    )


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


def test_orca_workflow_round2_relay_worker_start_uses_worktree_current():
    """Issue #75: `worker-start --terminal <handle>` re-engaging an already-existing terminal fails
    with selector_not_found when --worktree is `active` -- only `current` works (verified live, 2x
    reproduction: one orca-task-runner re-engage, one orca-evaluate re-engage). The three
    `terminal create --worktree active` sites elsewhere in this file spawn a brand-new terminal in
    the same call and are unaffected (confirmed by the issue's own repro) -- this assertion is
    scoped to the round-2+ worker-start call only, not a file-wide ban on `--worktree active`.
    """
    text = _read_skill("orca-workflow")
    round2_idx = text.index("**Contract 협상 relay — 라운드 2+")
    round2_end = text.index("## 3.", round2_idx)
    round2_section = text[round2_idx:round2_end]
    ws_idx = round2_section.index("orca orchestration worker-start --task")
    ws_call = round2_section[ws_idx : round2_section.index("--json", ws_idx) + len("--json")]
    assert "--worktree active" not in ws_call, (
        "round-2+ relay worker-start must not use --worktree active against a re-engaged "
        "terminal -- selector_not_found (issue #75)"
    )
    assert "--worktree current" in ws_call, (
        "round-2+ relay worker-start must use --worktree current against the re-engaged terminal"
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


def _workflow_section1d_span(text: str) -> tuple[int, int]:
    start = text.index("**1d. Retro")
    end = text.index("## 2. Task 경로")
    return start, end


def test_orca_workflow_dispatch_sites_call_log_dispatch_helper():
    """AC2/AC3(issue #68): §2a 라운드-1의 두 사이트(task-runner/evaluator)와 라운드 2+ relay, 총 3곳
    모두 log_dispatch 호출을 forward window 안에 가져야 한다. §1d(retro)는 이슈 스코프 밖이라 제외."""
    text = _read_skill("orca-workflow")
    section1d_start, section1d_end = _workflow_section1d_span(text)
    positions = [p for p in _dispatch_positions(text) if not (section1d_start <= p < section1d_end)]
    assert len(positions) == 3, f"expected 3 in-scope dispatch sites, found {len(positions)}"
    call_re = re.compile(r'^log_dispatch --skill "orca-workflow"', re.M)
    for pos in positions:
        window = _forward_window(text, pos)
        assert call_re.search(window), (
            f"orca-workflow: dispatch site at {pos} does not call log_dispatch in its forward window"
        )
    assert len(call_re.findall(text)) == 3


def test_orca_workflow_no_longer_has_prose_only_dual_log_instructions():
    """구조적 회귀 방지: 프로즈만 있고 실행 블록이 없던 옛 이중 지시(issue #68이 지목한 정확한 문구)가
    사라졌는지 — 단순 추가가 아니라 진짜 교체인지 확인."""
    text = _read_skill("orca-workflow")
    assert 'logging.md §1 assign 이벤트: role="task-runner"' not in text
    assert 'logging.md §1 assign 이벤트: role="evaluator"' not in text
    assert "logging.md §2 term 로그: skill=" not in text


def test_orca_workflow_log_dispatch_blocks_source_the_helper():
    """log_dispatch를 쓰는 각 fenced 블록이 자체 source 줄을 갖는지 —
    test_every_retry_invocation_block_sources_the_wrapper와 대칭인 검사."""
    text = _read_skill("orca-workflow")
    log_dispatch_call_re = re.compile(r'^log_dispatch --skill "', re.M)
    checked_any = False
    for m in _BASH_FENCE_RE.finditer(text):
        block = m.group(1)
        if log_dispatch_call_re.search(block):
            checked_any = True
            assert "source ~/.agents/orca-workflows/scripts/log_dispatch.sh" in block, (
                f"a fenced block using log_dispatch (near char offset {m.start()}) "
                "is missing its own source line"
            )
    assert checked_any


def test_orca_workflow_log_dispatch_sites_preserve_recv_exception_prose():
    """AC4: 헬퍼 전환 후에도 recv 미기록 근거(liveness probe / check --wait)가 SKILL.md 프로즈에
    남아 있는지 — 헬퍼가 recv를 안 쓴다는 코드 동작만으로는 사람이 왜 그런지 알 수 없으므로, 설명
    프로즈 존속 자체를 AC로 요구한 것으로 해석."""
    text = _read_skill("orca-workflow")
    assert text.count("recv는 기록하지 않는다") >= 3


def test_logging_md_points_to_log_dispatch_helper():
    """라운드 1 잔여 리스크 2: logging.md §1/§2 레시피 안으로 log_dispatch.sh가 스키마를 그대로 복제해
    가져갔는데 원본 문서에 상호참조가 없으면, 나중에 §1/§2를 고치는 세션이 스크립트 사본의 존재를 모른다
    — test_spawn_failures_has_broadened_regex_pointer_row와 같은 선례의 대칭 검사."""
    text = (WORKFLOWS_DIR / "logging.md").read_text()
    assert "log_dispatch.sh" in text


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


# --- issue #69: outcome enum 2-axis split, CONTRACT_APPROVED_ROUND1/MANUAL_RECOVERY_COMPLETED,
# provider canon (layer-3 retro follow-up to #62) ---


def test_logging_outcome_enum_includes_progress_branch_values():
    text = (WORKFLOWS_DIR / "logging.md").read_text()
    assert text.count('"outcome":"<') == 1, (
        "logging.md must keep exactly one outcome-enum placeholder line — a second occurrence "
        "would make test_logging_outcome_enum_includes_retro_values's re.search silently check "
        "the wrong line"
    )
    m = re.search(r'"outcome":"<([^>]+)>"', text)
    assert m, "outcome enum line missing in logging.md"
    values = m.group(1)
    assert "CONTRACT_APPROVED_ROUND1" in values, (
        "outcome enum must document round-1 contract approval (issue #69) — omitting or "
        "inventing ad-hoc strings for this branch is exactly the drift #62/#69 hunt"
    )
    assert "MANUAL_RECOVERY_COMPLETED" in values, (
        "outcome enum must document manual worker_done-loss recovery completion (issue #69)"
    )


def test_logging_documents_verdict_and_progress_branch_axes():
    text = (WORKFLOWS_DIR / "logging.md").read_text()
    start = text.index("**`outcome`**")
    end = text.index("**`wave_start`/`wave_end`**")
    outcome_section = text[start:end]
    assert "verdict 축" in outcome_section and "진행-분기 축" in outcome_section, (
        "logging.md's outcome section must split its documentation into a verdict axis and a "
        "progress-branch axis (issue #69) so a future addition knows which list it belongs to"
    )


def test_logging_states_no_ad_hoc_outcome_values_rule():
    text = (WORKFLOWS_DIR / "logging.md").read_text()
    start = text.index("**`outcome`**")
    end = text.index("**`wave_start`/`wave_end`**")
    outcome_section = text[start:end]
    assert "이슈를 연다" in outcome_section, (
        "logging.md's outcome section must state that an unlisted normal branch gets a new "
        "issue filed, not an invented ad-hoc string or a skipped event (issue #62/#69 recurrence)"
    )


def test_logging_documents_provider_value_source():
    text = (WORKFLOWS_DIR / "logging.md").read_text()
    start = text.index("**`assign`**")
    end = text.index("**`outcome`**")
    assign_section = text[start:end]
    assert "models/*.md" in assign_section, (
        "logging.md's assign recipe must pin provider's allowed values to the "
        "orca-workflows/models/*.md basenames (issue #69 evidence 3 — claude vs claude-code drift), "
        "documented next to the assign recipe itself, not just somewhere in the file"
    )
    for value in ("claude-code", "codex", "agy"):
        assert f"`{value}`" in assign_section, (
            f"logging.md's assign recipe section must enumerate `{value}` as a documented "
            "provider value"
        )


def test_orca_workflow_records_outcome_on_round1_approval():
    text = _read_skill("orca-workflow")
    start = text.index("**2a.")
    end = text.index("**2b.")
    section_2a = text[start:end]
    assert "CONTRACT_APPROVED_ROUND1" in section_2a, (
        "orca-workflow §2a must instruct recording outcome=CONTRACT_APPROVED_ROUND1 when a "
        "contract proposal is approved straight in round 1 (issue #69) — symmetric to the "
        "existing CONTRACT_FINALIZED_BY_GENERATOR instruction for round-limit reached"
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


def test_orca_retro_issue_body_has_version_section():
    text = _read_skill("orca-retro")
    assert "환경/버전" in text, "issue body must carry a 환경/버전 section"
    assert "skill_version" in text and "orca_workflows_commit" in text and "orca_app_version" in text, (
        "orca-retro must pull the same three fields Task 1 added to the meta record"
    )
    assert "실행 당시와 다를 수 있음" in text, (
        "the no-term-log fallback path must warn the version may not match when the bug occurred"
    )


def test_orca_retro_label_documented_as_general_convention():
    text = _read_skill("orca-retro")
    assert "orca-retro 전용이 아니라" in text, (
        "retro label must be documented as a general skill-discovered-issue convention, "
        "not orca-retro-exclusive, even though orca-retro is currently the only implementer"
    )


def test_orca_retro_version_section_falls_through_on_null_fields():
    text = _read_skill("orca-retro")
    assert 'select(.type=="meta")' in text, (
        "priority-1 term-log lookup must gate on the meta record type, not just file existence"
    )
    assert "전부 null이면" in text and "우선순위 2로 넘어간다" in text, (
        "priority-1 must explicitly fall through to priority-2 when the term log predates the "
        "version fields or line 1 isn't a meta record — not paste an all-null 환경/버전 section"
    )


def test_orca_retro_version_section_attributes_spawning_skill():
    text = _read_skill("orca-retro")
    assert "skill, terminal, skill_version" in text, (
        "the term-log projection must include `skill` (spawning skill) alongside the version "
        "fields, not just the bare version keys"
    )
    assert "스폰한" in text, (
        "when meta.skill differs from the issue's target skill, the pasted version must be "
        "labeled as belonging to the spawning skill, not silently attributed to the target"
    )


def test_orca_retro_term_log_path_is_bound_before_use():
    text = _read_skill("orca-retro")
    assert "`$term_log`에" in text and "바인딩" in text, (
        "the skill must tell the executing agent how $term_log gets its value (from §1's "
        "collection loop) before §4 reads it, instead of leaving it undefined"
    )


def test_orca_retro_recurrence_comment_also_carries_version_section():
    text = _read_skill("orca-retro")
    idx = text.index("재발 코멘트**를 단다")
    window = text[idx : idx + 120]
    assert "환경/버전" in window, (
        "the gh issue comment (recurrence) path must reference the assembled 환경/버전 section "
        "too, not just gh issue create — both paths are in scope per the design spec"
    )


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


def test_orca_workflow_premerge_block_captures_exit_code_before_branching():
    text = _read_skill("orca-workflow")
    start = text.index("if [ -f scripts/premerge.sh ]; then")
    end = text.index("## 3. Inspecting")
    block = text[start:end]
    assert "if ! bash scripts/premerge.sh" not in block, (
        "premerge block must not branch on `if ! cmd; then premerge_exit=$?` — $? there captures "
        "the negated `!` pipeline's status, which is always 0 (issue #72, verified live in both "
        "bash and zsh)"
    )
    assert 'premerge_exit="$(' in block, (
        "premerge block must capture premerge.sh's exit code from the detached job's own "
        "EXIT: line, not from a live $? on a foreground negated command"
    )


def test_orca_workflow_premerge_block_specifies_execution_mode():
    text = _read_skill("orca-workflow")
    start = text.index("if [ -f scripts/premerge.sh ]; then")
    end = text.index("## 3. Inspecting")
    block = text[start:end]
    assert "harness" in block and "타임아웃" in block, (
        "premerge block must state that the gate command's runtime can exceed the coordinator "
        "harness's single-command timeout (issue #72)"
    )
    assert "nohup" in block, (
        "premerge block must specify a concrete detached-execution pattern for gate commands "
        "that can outrun the harness single-command timeout"
    )


def test_orca_workflow_premerge_fail_requires_verdict_line():
    text = _read_skill("orca-workflow")
    start = text.index("if [ -f scripts/premerge.sh ]; then")
    end = text.index("## 3. Inspecting")
    block = text[start:end]
    assert r"\[premerge\] " in block, (
        "premerge block must check for premerge.sh's own verdict-line prefix before recording "
        "PREMERGE_FAIL — a nonzero exit with no verdict line is an infra kill, not a gate verdict"
    )
    assert "PREMERGE_TIMEOUT" in block, (
        "premerge block must route the no-verdict-line/budget-exceeded case to a distinct "
        "outcome, not PREMERGE_FAIL"
    )


def test_logging_outcome_enum_includes_premerge_timeout():
    text = (WORKFLOWS_DIR / "logging.md").read_text()
    m = re.search(r'"outcome":"<([^>]+)>"', text)
    assert m, "outcome enum line missing in logging.md"
    assert "PREMERGE_TIMEOUT" in m.group(1), (
        "outcome enum must document PREMERGE_TIMEOUT (issue #72) — an infra kill with no "
        "premerge.sh verdict line must not be logged as PREMERGE_FAIL"
    )


def test_orca_workflow_premerge_poll_loop_emits_heartbeat_output():
    text = _read_skill("orca-workflow")
    start = text.index("if [ -f scripts/premerge.sh ]; then")
    end = text.index("## 3. Inspecting")
    block = text[start:end]
    while_start = block.index("while true")
    while_end = block.index("done", while_start)
    loop_body = block[while_start:while_end]
    assert "printf 'premerge poll:" in loop_body, (
        "the poll loop must print progress output every iteration before sleeping — round-1 "
        "rejection (#72): a silent multi-minute single call risks self-triggering the exact "
        "harness no-output kill this design exists to detect"
    )


def test_orca_workflow_premerge_poll_survives_interrupted_retry():
    text = _read_skill("orca-workflow")
    start = text.index("if [ -f scripts/premerge.sh ]; then")
    end = text.index("## 3. Inspecting")
    block = text[start:end]
    assert ".started" in block, (
        "poll budget must be tracked via a wall-clock start-time file, not a shell-local "
        "counter, so a coordinator that re-issues the poll block after an interrupted call "
        "resumes with a correct elapsed time instead of restarting the budget at zero "
        "(round-1 rejection #72: no documented recovery path when the poll block itself dies)"
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


def test_orca_workflow_task_runner_dispatch_spec_instructs_retry_wrapping():
    text = _read_skill("orca-workflow")
    marker = "제안서/구현 모드"
    idx = text.index(marker)
    end = text.index('>"', idx)
    segment = text[idx:end]
    assert "orca_call_with_retry" in segment
    assert ".orca-orphaned-result-<task_id>.json" in segment


def test_orca_workflow_evaluator_dispatch_spec_instructs_retry_wrapping():
    text = _read_skill("orca-workflow")
    marker = "요청 모드"
    idx = text.index(marker)
    end = text.index('>"', idx)
    segment = text[idx:end]
    assert "orca_call_with_retry" in segment
    assert ".orca-orphaned-result-<task_id>.json" in segment


def test_orca_workflow_round2_relay_dispatch_spec_instructs_retry_wrapping():
    text = _read_skill("orca-workflow")
    marker = "반려 사유 요약"
    idx = text.index(marker)
    end = text.index('>"', idx)
    segment = text[idx:end]
    assert "orca_call_with_retry" in segment
    assert ".orca-orphaned-result-<task_id>.json" in segment


def test_orca_workflow_section0_recovery_references_orphan_result_path():
    """AC4(issue #42): 이미 PR #51(issue #41)에서 충족됨 — 회귀 방지 락(기능 변경 없음).
    승인 조건 1 — 이 테스트를 생략하면 AC5가 깨진다(계약 검토 리포트 참고). 절대 빼지 말 것."""
    text = _read_skill("orca-workflow")
    section0_start = text.index("## 0.")
    section0_end = text.index("## 1.")
    section0 = text[section0_start:section0_end]
    assert ".orca-orphaned-result-<task_id>.json" in section0


def test_codex_md_documents_linked_worktree_sandbox_exception():
    """AC1 (issue #70): codex.md's sandbox paragraph must document the linked-worktree commit
    exception exactly once (a duplicated sandbox paragraph must not silently pass)."""
    text = (WORKFLOWS_DIR / "models" / "codex.md").read_text()
    assert text.count("permits reads and writes inside the") == 1
    sandbox_idx = text.index("permits reads and writes inside the")
    exception_idx = text.index("Linked worktree exception", sandbox_idx)
    assert sandbox_idx < exception_idx
    para_end = text.index("\n\n", exception_idx)
    segment = text[exception_idx:para_end]
    assert ".git/worktrees/" in segment
    assert "git add" in segment and "git commit" in segment


def test_orca_task_runner_subtask_spec_branches_commit_instruction_by_provider():
    """AC2/AC3 (issue #70): the required-items list must flag ②/⑥ as codex exceptions, and the
    exception paragraph must instruct codex workers not to commit while leaving claude/agy
    unaffected."""
    text = _read_skill("orca-task-runner")
    checklist_idx = text.index("subtask spec 필수 항목")
    second_idx = text.index("②", checklist_idx)
    sixth_idx = text.index("⑥", checklist_idx)
    assert "provider=codex는 예외" in text[second_idx:text.index("③", second_idx)]
    assert "provider=codex는 예외" in text[sixth_idx:text.index("⑦", sixth_idx)]

    exception_idx = text.index("provider=codex 예외", checklist_idx)
    para_end = text.index("\n\n", exception_idx)
    segment = text[exception_idx:para_end]
    assert "커밋하지 마라" in segment
    assert "worker_done" in segment
    assert "filesModified" in segment
    assert "claude/agy" in segment and "그대로 적용된다" in segment


def test_orca_task_runner_subtask_spec_required_items_preserve_commit_text_for_non_codex():
    """AC3 (issue #70): the original ②/⑥ commit-instruction wording must survive verbatim inside
    the required-items list itself — not just be *claimed* unchanged by the exception prose. If
    ⑥'s pathspec rule text is ever deleted (even while the codex-exception paragraph still says
    'claude/agy unaffected'), this must go red."""
    text = _read_skill("orca-task-runner")
    checklist_idx = text.index("subtask spec 필수 항목")
    second_idx = text.index("②", checklist_idx)
    third_idx = text.index("③", second_idx)
    sixth_idx = text.index("⑥", checklist_idx)
    seventh_idx = text.index("⑦", sixth_idx)
    second_segment = text[second_idx:third_idx]
    sixth_segment = text[sixth_idx:seventh_idx]
    assert "커밋 대상 브랜치·worktree 명시" in second_segment
    assert '`git commit -m "<msg>" -- <files>`' in sixth_segment
    assert "`git add` 명시 경로만" in sixth_segment
    assert "index.lock 재시도" in sixth_segment


def test_orca_task_runner_section5_codex_commit_uses_separate_unsandboxed_terminal():
    """AC4 (issue #70): commit-on-behalf of a codex subtask must run in a separate plain terminal
    (no codex/claude/agy launch wrapper), never the coordinator's own shell — the coordinator's own
    shell may itself be a codex process under -s workspace-write in the same worktree (High-Risk
    tier can resolve orca-task-runner's own provider to codex), which would hit the identical
    .git/worktrees sandbox denial the subtask worker hit."""
    text = _read_skill("orca-task-runner")
    section5_start = text.index("## 5.")
    section6_start = text.index("## 6.")
    section5 = text[section5_start:section6_start]
    commit_idx = section5.index("commit-helper")
    close_idx = section5.index("orca terminal close --terminal <impl_handle>", commit_idx)
    assert commit_idx < close_idx, (
        "the commit-helper step must appear before the existing close-loop bullet, as a new "
        "bullet/fence inserted ahead of it — not spliced into the existing fenced block"
    )
    segment = section5[commit_idx:close_idx]
    assert "코디네이터 자신의 셸에서 실행하지 않는다" in segment
    assert "codex" in segment and "claude" in segment and "agy" in segment
    assert "terminal create" in segment


def test_orca_task_runner_section5_files_modified_sourced_from_check_wait_not_terminal_read():
    """AC4 (issue #70): filesModified must be sourced from the check --wait worker_done response
    (not read_json/terminal scrollback). The worker preamble fills it via --files-modified "a,b",
    a comma-separated string, not an array (D3 in the round-2 contract review) — round 3 replaced
    the bash-array split this test used to pin with a shared portable helper script (see
    test_orca_task_runner_section5_uses_portable_csv_split_helper below); this test only checks
    where the raw CSV comes from, not how it's later split."""
    text = _read_skill("orca-task-runner")
    section5_start = text.index("## 5.")
    section6_start = text.index("## 6.")
    section5 = text[section5_start:section6_start]
    commit_idx = section5.index("commit-helper")
    fence_idx = section5.index("```bash", commit_idx)
    prose = section5[commit_idx:fence_idx]
    assert "check --wait" in prose
    assert "read_json" in prose
    assert "꺼내지" in prose and "않는다" in prose
    assert "콤마 구분" in prose

    fetch_fence_end = section5.index("```", fence_idx + len("```bash"))
    fetch_segment = section5[fence_idx:fetch_fence_end]
    assert "files_modified_csv" in fetch_segment
    assert "jq -r" in fetch_segment


def test_orca_task_runner_section5_uses_portable_csv_split_helper():
    """Round-3 fix (issue #70 contract review, retry 1/2): a bash-only `IFS=',' read -r -a
    files_modified <<< "$csv"` split silently produced zero elements under zsh (this machine's
    actual runtime shell, ZSH_VERSION=5.9) while working under bash — `read -a` errors in zsh
    ("bad option: -a") but still exits 0, so the length guard that followed it treated every
    codex subtask as "nothing to commit" with no error and no escalation (a worse fail-open than
    issue #70's original defect). SKILL.md must delegate the CSV-to-pathspec-file step to the
    shared, cross-shell-tested `write_pathspec_from_csv.sh` (same portability contract as
    `orca_call_with_retry.sh`/`log_dispatch.sh` in the same directory — see
    tests/test_write_pathspec_from_csv.py for the behavioral bash+zsh coverage this text-matching
    check cannot provide on its own) and must never reintroduce a bash array, `IFS`-based split,
    or `read -a` for this purpose."""
    text = _read_skill("orca-task-runner")
    section5_start = text.index("## 5.")
    section6_start = text.index("## 6.")
    section5 = text[section5_start:section6_start]
    commit_idx = section5.index("commit-helper")
    close_idx = section5.index("orca terminal close --terminal <impl_handle>", commit_idx)
    segment = section5[commit_idx:close_idx]

    assert "write_pathspec_from_csv.sh" in segment
    assert "source ~/.agents/orca-workflows/scripts/write_pathspec_from_csv.sh" in segment
    assert 'if write_pathspec_from_csv "$files_modified_csv" "$pathspec_file"; then' in segment

    # Scope the negative checks to the executable fence itself, not the surrounding prose — the
    # prose above legitimately quotes the rejected `IFS=',' read -r -a` snippet for context (same
    # as log_dispatch.sh's own header does for its rejected `${!req}` draft), so a naive
    # whole-segment "not in" check would trip on that explanatory text instead of the real code.
    guard_start = segment.index('if write_pathspec_from_csv "$files_modified_csv" "$pathspec_file"; then')
    guard_end = segment.index("```", guard_start)
    guard_code = segment[guard_start:guard_end]
    assert "IFS=" not in guard_code
    assert "read -a" not in guard_code and "read -r -a" not in guard_code
    assert "files_modified[@]" not in guard_code
    assert "files_modified=()" not in guard_code


def test_write_pathspec_from_csv_script_documents_the_ifs_read_a_regression():
    """The shared script's own header must document the exact defect it exists to prevent (bash
    `read -a` silently producing an empty split under zsh) — this is what makes the portability
    contract legible to a future editor who might otherwise "simplify" it back to `read -a`."""
    text = (REPO_ROOT / "orca-workflows" / "scripts" / "write_pathspec_from_csv.sh").read_text()
    assert "read -a" in text
    assert "zsh" in text.lower()
    assert "bad option" in text


def test_orca_task_runner_section5_commit_guard_handles_nothing_to_commit_and_uses_tui_idle():
    """D1/D2 (issue #70 round-2 contract review): "nothing to commit" (git's rc=1) must be
    branched as a normal outcome, not escalation, and completion must be detected via
    --for tui-idle, not --for exit (D2 — the helper shell returns to its prompt instead of
    exiting, per agy.md's documented mechanism). The array-length guard this test used to pin
    (${#files_modified[@]}) was removed in round 3 — see
    test_orca_task_runner_section5_uses_portable_csv_split_helper for its replacement."""
    text = _read_skill("orca-task-runner")
    section5_start = text.index("## 5.")
    section6_start = text.index("## 6.")
    section5 = text[section5_start:section6_start]
    commit_idx = section5.index("commit-helper")
    close_idx = section5.index("orca terminal close --terminal <impl_handle>", commit_idx)
    segment = section5[commit_idx:close_idx]

    guard_start = segment.index('if write_pathspec_from_csv "$files_modified_csv" "$pathspec_file"; then')
    guard_end = segment.index("```", guard_start)
    guard_code = segment[guard_start:guard_end]
    assert "nothing to commit" in guard_code
    assert "정상 no-op" in guard_code
    assert "orca terminal wait --terminal <commit_helper_handle> --for tui-idle" in guard_code
    assert "--terminal <commit_helper_handle> --for exit" not in segment
