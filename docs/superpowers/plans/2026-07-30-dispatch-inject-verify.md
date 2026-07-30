# Dispatch-Inject Verify Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect and recover from `dispatch --inject` landing text in a terminal's input box without Enter registering (issue #43), so the resulting stuck state doesn't sit indistinguishable from normal post-completion idle.

**Architecture:** A new git-tracked reference doc, `orca-workflows/dispatch-verify.md`, defines a provider-agnostic bounded tail-diff check (compare `terminal read` output before/after a short wait) plus a single Enter-only retry, following the same pointer-doc precedent as `orca-workflows/logging.md`/`spawn-failures.md`. The three `SKILL.md` files that call `dispatch --inject` (`orca-task-runner`, `orca-workflow`, `orca-evaluate`) each get a one-line pointer comment added at every non-duplicate call site. `orca-workflows/spawn-failures.md` gets one new row so a later occurrence is recognized as known rather than re-diagnosed from scratch.

**Tech Stack:** Markdown (`SKILL.md`, reference docs), `bash`/`jq`, the `orca` CLI, Python/pytest for the existing structural regression suite (`tests/test_orca_skills.py`, run via `uvx pytest` — confirmed working in this environment; plain `pytest` is not on `PATH` here).

## Global Constraints

- Every `dispatch --inject` call site in the three `SKILL.md` files gets the verify pointer **except** `skills/orca-evaluate/SKILL.md`'s §0 launch block (around line 25) — it duplicates `orca-workflow`'s own evaluate-dispatch site (`skills/orca-workflow/SKILL.md:87`) and has no independent execution of its own, matching the exact exception `tests/test_orca_skills.py::test_dispatch_site_count_and_section0_exception_shape` already encodes for the `logging.md` pointer. Do not add a pointer there — it would make the site count assertion in that existing test meaningless (a future regression at a real site could hide behind a "some sites have two pointers" pattern).
- The verify pointer is a comment only — never inline the actual bash from `dispatch-verify.md` into any `SKILL.md`. This matches how `logging.md`/`spawn-failures.md` are already referenced (one line, not duplicated bash), and keeps `tests/test_orca_skills.py::test_orca_terminal_read_counts_per_skill_file`'s existing per-file literal-count assertions (`{"orca-task-runner": 1, "orca-evaluate": 1, "orca-workflow": 0}`) unaffected — do not let the pointer comment's wording contain the literal phrase `orca terminal read`.
- Do not resend the original `--inject` text on retry — only Enter. Resending the full text risks a duplicate prompt if the first attempt actually landed a moment after the first read was captured.
- Do not hardcode any provider-specific UI marker (e.g. Claude Code's `❯`/`⏺`) anywhere in `dispatch-verify.md` or the `SKILL.md` pointers — the detection must work the same way regardless of which REPL-capable provider (`model-selection.md`) is running in the target terminal.
- `orca-workflows/` is not deployed via `scripts/deploy-skills.sh` — edits there go live on merge to `main` (symlink-tracks-main convention). `skills/*/SKILL.md` changes are different: `~/.agents/skills/orca-task-runner`, `orca-workflow`, `orca-evaluate` are commit-pinned directory copies, not symlinks, so editing `skills/*/SKILL.md` in this repo does nothing live until `scripts/deploy-skills.sh` runs (per `AGENTS.md`). Sequencing matters here: merge this branch to `main` **first** (so `~/.agents/orca-workflows/dispatch-verify.md` resolves for the symlink), **then** run `scripts/deploy-skills.sh orca-task-runner orca-workflow orca-evaluate` — deploying before merge would ship pointer comments referencing a file not yet present at the referenced path.
- Baseline check before starting: `uvx pytest tests/test_orca_skills.py -q` currently reports `2 failed, 65 passed` on an unmodified tree (`test_orca_evaluate_review_model_selection_is_dynamic_not_fixed_high_risk` and `test_orca_evaluate_preserves_evaluator_separation_intent`). Both are pre-existing and unrelated to issue #43 — do not attempt to fix them as part of this plan. Every verification step below expects exactly these same 2 failures to persist, plus all-passing for everything this plan touches.

---

## File Structure

- Create: `orca-workflows/dispatch-verify.md` — shared bounded tail-diff + retry + escalation procedure
- Modify: `skills/orca-task-runner/SKILL.md` — add verify pointer at its one `dispatch --inject` site (§5)
- Modify: `skills/orca-workflow/SKILL.md` — add verify pointer at its two `dispatch --inject` sites (task-runner dispatch, evaluate dispatch)
- Modify: `skills/orca-evaluate/SKILL.md` — add verify pointer at its two non-duplicate `dispatch --inject` sites (§1 contract-review, §3 code-review); §0 stays untouched (see Global Constraints)
- Modify: `orca-workflows/spawn-failures.md` — one new known-signature row (log-based, documented exception to the literal-substring convention) + a short exception note near "Adding a new row"
- Modify: `tests/test_orca_skills.py` — new structural tests pinning all of the above

---

### Task 1: Create `orca-workflows/dispatch-verify.md`

**Files:**
- Create: `orca-workflows/dispatch-verify.md`
- Modify: `tests/test_orca_skills.py`

**Interfaces:**
- Produces: the canonical bounded tail-diff + retry + escalation procedure that Tasks 2-4's `SKILL.md`
  pointer comments refer to by filename (`dispatch-verify.md`) — later tasks don't inline any of this
  file's bash, only reference it.

- [ ] **Step 1: Write the failing tests**

Append to the end of `tests/test_orca_skills.py` (after the existing `test_orca_terminal_read_counts_per_skill_file`, which currently ends the file at line 611):

```python


DISPATCH_VERIFY_FILE = "dispatch-verify.md"


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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uvx pytest tests/test_orca_skills.py -q -k "dispatch_verify"`

Expected: `4 failed` (`test_dispatch_verify_file_documents_bounded_tail_diff_and_escalation` fails because
the file doesn't exist yet; `test_dispatch_sites_are_followed_by_dispatch_verify_pointer` fails for all
three `NEW_SKILLS` parametrizations because no `SKILL.md` has the pointer yet).

- [ ] **Step 3: Write `orca-workflows/dispatch-verify.md`**

```markdown
# Orca Workflows Dispatch Verify

> verified_at: 2026-07-30

Shared post-`dispatch --inject` verification procedure for `orca-task-runner`/`orca-evaluate`/`orca-workflow`
(issue #43) — split out so the three `SKILL.md` files point here instead of each repeating the same bash
(same precedent as `logging.md`/`spawn-failures.md`).

## Why

`dispatch --inject` can land text in a target terminal's input box without Enter actually registering. A
single `terminal read` right after cannot tell "stuck, unsent" apart from "task already finished, terminal
legitimately idle" — both render as static output with no further activity. This file defines a bounded
check that can, without depending on any provider-specific UI marker (Claude Code's `❯`/`⏺` vs. Codex's own
REPL chrome — a marker-based check would need a parallel definition per provider with no shared primitive
to keep them in sync).

## Procedure — run immediately after every `dispatch --inject`

```bash
tail_0="$(orca terminal read --terminal <handle> --json | jq -r '.result.terminal.tail | join("\n")')"
sleep 15
tail_1="$(orca terminal read --terminal <handle> --json | jq -r '.result.terminal.tail | join("\n")')"
if [ "$tail_0" = "$tail_1" ]; then
  # Unsent — resend Enter only, never resend the original text (avoids a duplicate prompt if the
  # first attempt actually landed a moment after tail_0 was captured). Confirm the CLI's exact
  # "Enter only" affordance against `orca skills get orca-cli` — do not assume a flag name.
  orca orchestration dispatch --task <task_id> --to <handle> --inject --enter --json
  sleep 15
  tail_2="$(orca terminal read --terminal <handle> --json | jq -r '.result.terminal.tail | join("\n")')"
  if [ "$tail_1" = "$tail_2" ]; then
    # Still static — hand off to ~/.agents/orca-workflows/spawn-failures.md (grep known
    # signatures first, diagnose if no match) rather than looping this retry indefinitely.
    :
  fi
fi
```

15s is a starting default, not a validated constant — tune it if a provider's typical first-token latency
needs more headroom. A false positive (retry fires on a merely slow turn) costs one harmless extra Enter (a
no-op on an already-submitted prompt) plus one more 15s wait, not a corrupted session.

This check compares tail content for equality only — it never parses or acts on what the content says.
Skills whose stated principle is not reading a terminal's output directly for judgment (e.g.
`orca-workflow`, "diff/report 본문을 직접 읽지 않는다") are not violating that principle by running this
check — opaque equality comparison is not content interpretation.

## Escalation

A second static comparison means: apply the `spawn-failures.md` procedure (grep known signatures, diagnose
if no match) rather than retrying `--enter` a second time.

## Edge cases

- This does not replace `orca-task-runner`'s existing wave-loop timeout/`count:0` checkpoint (`terminal
  read` for "생사 확인") — that check covers stalls *during* a task's execution, potentially minutes later.
  This procedure covers only the narrow window immediately after `dispatch --inject` itself.
- Distinguish from `spawn-failures.md`'s `#37` row: both involve `dispatch --inject` landing on a terminal
  that looks idle, but `#37`'s target has already exited to a bare shell (`zsh: parse error` reappears on
  the *next* interaction), while this procedure's target is still a live, waiting REPL — the text is
  genuinely sitting in that REPL's own input box, not falling through to a dead shell underneath it.
```

- [ ] **Step 4: Verify the new file's own test now passes (pointer test stays red — expected)**

Run: `uvx pytest tests/test_orca_skills.py -q -k "test_dispatch_verify_file_documents_bounded_tail_diff_and_escalation"`

Expected: `1 passed`.

Run: `uvx pytest tests/test_orca_skills.py -q -k "test_dispatch_sites_are_followed_by_dispatch_verify_pointer"`

Expected: `3 failed` (unchanged — no `SKILL.md` has been touched yet; Tasks 2-4 turn these green one at a
time).

- [ ] **Step 5: Commit**

```bash
git add orca-workflows/dispatch-verify.md tests/test_orca_skills.py
git commit -m "$(cat <<'EOF'
docs(orca-workflows): add dispatch-verify.md (issue #43)

Provider-agnostic bounded tail-diff check for detecting dispatch
--inject text that lands in a terminal's input box without Enter
registering, plus a single Enter-only retry before escalating to
the existing spawn-failures.md procedure.
EOF
)"
```

---

### Task 2: Update `skills/orca-task-runner/SKILL.md`

**Files:**
- Modify: `skills/orca-task-runner/SKILL.md`

**Interfaces:**
- Consumes: `orca-workflows/dispatch-verify.md` (Task 1) by filename reference only.

- [ ] **Step 1: Add the verify pointer to the §5 wave-loop dispatch**

Old (`skills/orca-task-runner/SKILL.md:116-126`):

```bash
orca orchestration dispatch --task <task_id> --to <impl_handle> --inject --json   # wave 크기만큼 병렬 — 상한 임시 해제, §3 참고
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. dispatch와 같은 블록에서 즉시 실행(누락 방지).
#  logging.md §1 assign 이벤트: role="subtask-impl", issue=<issue-num>, task_id=<task_id>, wave_index=<n>,
#    subtask_type=<전사|통합|아키텍처>, provider/model/effort=resolved 값, terminal=<impl_handle>,
#    worktree=<worktree 경로>. wave_index는 §3 wave_start 로그와 join한다.
#  logging.md §2 term 로그: skill="orca-task-runner", role="subtask-impl", terminal=<impl_handle>,
#    meta 기록 후 sent.content=$spec_text(위 사이드카에서 로드한 값). recv는 아래 close 직전에
#    기록한다(§5 마지막 블록). 사이드카는 여기서 지우지 않는다 — 스폰 실패 재시도나 worker_done
#    유실 수동 복구가 같은 task_id로 이 블록을 다시 태울 수 있어, 삭제는 터미널이 실제로 닫히는
#    시점(§5 마지막 블록)으로 미룬다.
```

New:

```bash
orca orchestration dispatch --task <task_id> --to <impl_handle> --inject --json   # wave 크기만큼 병렬 — 상한 임시 해제, §3 참고
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43): 15초 뒤 재-read해서
# tail이 그대로면 Enter만 재전송, 그래도 그대로면 spawn-failures.md로.
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. dispatch와 같은 블록에서 즉시 실행(누락 방지).
#  logging.md §1 assign 이벤트: role="subtask-impl", issue=<issue-num>, task_id=<task_id>, wave_index=<n>,
#    subtask_type=<전사|통합|아키텍처>, provider/model/effort=resolved 값, terminal=<impl_handle>,
#    worktree=<worktree 경로>. wave_index는 §3 wave_start 로그와 join한다.
#  logging.md §2 term 로그: skill="orca-task-runner", role="subtask-impl", terminal=<impl_handle>,
#    meta 기록 후 sent.content=$spec_text(위 사이드카에서 로드한 값). recv는 아래 close 직전에
#    기록한다(§5 마지막 블록). 사이드카는 여기서 지우지 않는다 — 스폰 실패 재시도나 worker_done
#    유실 수동 복구가 같은 task_id로 이 블록을 다시 태울 수 있어, 삭제는 터미널이 실제로 닫히는
#    시점(§5 마지막 블록)으로 미룬다.
```

- [ ] **Step 2: Run the scoped test to verify it now passes**

Run: `uvx pytest tests/test_orca_skills.py -q -k "test_dispatch_sites_are_followed_by_dispatch_verify_pointer and orca-task-runner"`

Expected: `1 passed`.

Run: `uvx pytest tests/test_orca_skills.py -q -k "test_orca_terminal_read_counts_per_skill_file"`

Expected: `1 passed` — confirms the new pointer comment did not add a literal `orca terminal read` occurrence to this file (it must stay at exactly 1).

- [ ] **Step 3: Commit**

```bash
git add skills/orca-task-runner/SKILL.md
git commit -m "$(cat <<'EOF'
fix(orca-task-runner): add dispatch-verify pointer at wave dispatch (#43)

Detect dispatch --inject text that lands unsent (Enter not
registered) at the one dispatch site this skill owns.
EOF
)"
```

---

### Task 3: Update `skills/orca-workflow/SKILL.md`

**Files:**
- Modify: `skills/orca-workflow/SKILL.md`

**Interfaces:**
- Consumes: `orca-workflows/dispatch-verify.md` (Task 1) by filename reference only.

- [ ] **Step 1: Add the verify pointer to the task-runner dispatch**

Old (`skills/orca-workflow/SKILL.md:65-73`):

```bash
orca orchestration dispatch --task <task_id> --to <run-handle> --inject --json
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. dispatch와 같은 블록에서 즉시 실행(누락 방지).
#  logging.md §1 assign 이벤트: role="task-runner", issue=<issue-num>, task_id=<task_id>, provider/model/effort=resolved 값,
#    terminal=<run-handle>, worktree=<worktree 경로>
#  logging.md §2 term 로그: skill="orca-workflow", role="task-runner", terminal=<run-handle>, meta 기록 후
#    sent.content=$spec_text. recv는 기록하지 않는다 — 이 스킬은 diff/report 본문을 직접 읽지 않는다
#    (도입부 원칙); term-<run-handle>.jsonl은 orca-workflow 자신이 소유하는 파일이라 task-runner는
#    거기 쓰지 않는다 — task-runner 자신의 왕복 내용은 그쪽이 스폰한 term-<impl_handle>.jsonl들
#    (subtask worker마다 하나씩)에 이미 남는다.
```

New:

```bash
orca orchestration dispatch --task <task_id> --to <run-handle> --inject --json
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43): 15초 뒤 재-read해서
# tail이 그대로면 Enter만 재전송, 그래도 그대로면 spawn-failures.md로. tail 비교는 내용을 해석하지
# 않는 불투명 비교라 위 "diff/report 본문을 직접 읽지 않는다" 원칙과 충돌하지 않는다.
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. dispatch와 같은 블록에서 즉시 실행(누락 방지).
#  logging.md §1 assign 이벤트: role="task-runner", issue=<issue-num>, task_id=<task_id>, provider/model/effort=resolved 값,
#    terminal=<run-handle>, worktree=<worktree 경로>
#  logging.md §2 term 로그: skill="orca-workflow", role="task-runner", terminal=<run-handle>, meta 기록 후
#    sent.content=$spec_text. recv는 기록하지 않는다 — 이 스킬은 diff/report 본문을 직접 읽지 않는다
#    (도입부 원칙); term-<run-handle>.jsonl은 orca-workflow 자신이 소유하는 파일이라 task-runner는
#    거기 쓰지 않는다 — task-runner 자신의 왕복 내용은 그쪽이 스폰한 term-<impl_handle>.jsonl들
#    (subtask worker마다 하나씩)에 이미 남는다.
```

- [ ] **Step 2: Add the verify pointer to the evaluate dispatch**

Old (`skills/orca-workflow/SKILL.md:87-92`):

```bash
orca orchestration dispatch --task <task_id> --to <evaluate-handle> --inject --json
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로.
#  logging.md §1 assign 이벤트: role="evaluator", issue=<issue-num>, task_id=<task_id>, provider/model/effort=resolved 값,
```

New:

```bash
orca orchestration dispatch --task <task_id> --to <evaluate-handle> --inject --json
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43): 15초 뒤 재-read해서
# tail이 그대로면 Enter만 재전송, 그래도 그대로면 spawn-failures.md로. (이 이슈의 실제 발생 사례가
# 바로 이 dispatch 대상 터미널 — task-evaluate-411 — 이었다.)
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로.
#  logging.md §1 assign 이벤트: role="evaluator", issue=<issue-num>, task_id=<task_id>, provider/model/effort=resolved 값,
```

(This block continues past what's shown above with the `recv는 기록하지 않는다...` explanation already
present — leave everything after line 92 unchanged.)

- [ ] **Step 3: Run the scoped test to verify it now passes**

Run: `uvx pytest tests/test_orca_skills.py -q -k "test_dispatch_sites_are_followed_by_dispatch_verify_pointer and orca-workflow"`

Expected: `1 passed` (this parametrization checks both of `orca-workflow`'s sites in one assertion loop).

Run: `uvx pytest tests/test_orca_skills.py -q -k "test_orca_terminal_read_counts_per_skill_file"`

Expected: `1 passed` — `orca-workflow`'s count must stay at 0.

- [ ] **Step 4: Commit**

```bash
git add skills/orca-workflow/SKILL.md
git commit -m "$(cat <<'EOF'
fix(orca-workflow): add dispatch-verify pointers at both dispatch sites (#43)

Detect dispatch --inject text that lands unsent at the task-runner
and evaluate dispatch sites — the evaluate site is where issue #43
was actually observed (task-evaluate-411).
EOF
)"
```

---

### Task 4: Update `skills/orca-evaluate/SKILL.md`

**Files:**
- Modify: `skills/orca-evaluate/SKILL.md`

**Interfaces:**
- Consumes: `orca-workflows/dispatch-verify.md` (Task 1) by filename reference only.

Only the §1 (contract-review) and §3 (code-review) sites get the pointer. The §0 site (around line 25)
duplicates `orca-workflow`'s own evaluate-dispatch site (already covered in Task 3) and has no independent
execution of its own — see Global Constraints and
`test_dispatch_site_count_and_section0_exception_shape`.

- [ ] **Step 1: Add the verify pointer to the §1 contract-review dispatch**

Old (`skills/orca-evaluate/SKILL.md:44-56`, first five lines shown — rest of the comment block is
unaffected):

```bash
orca orchestration dispatch --task <task_id> --to <contract-handle> --inject --json
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. §3 스폰도 동일한 형태(§2 agent-e2e는
# assign만 — term 로그 대상 아님).
#  logging.md §1 assign 이벤트: role="contract-review", issue=<issue-num>, task_id=<task_id>,
#    provider/model/effort=resolved 값, terminal=<contract-handle>, worktree=<worktree 경로>
```

New:

```bash
orca orchestration dispatch --task <task_id> --to <contract-handle> --inject --json
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43): 15초 뒤 재-read해서
# tail이 그대로면 Enter만 재전송, 그래도 그대로면 spawn-failures.md로. §3 스폰도 동일하게 적용한다.
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. §3 스폰도 동일한 형태(§2 agent-e2e는
# assign만 — term 로그 대상 아님).
#  logging.md §1 assign 이벤트: role="contract-review", issue=<issue-num>, task_id=<task_id>,
#    provider/model/effort=resolved 값, terminal=<contract-handle>, worktree=<worktree 경로>
```

- [ ] **Step 2: Add the verify pointer to the §3 code-review dispatch**

Old (`skills/orca-evaluate/SKILL.md:141-146`, first four lines shown):

```bash
orca orchestration dispatch --task <task_id> --to <review-handle> --inject --json
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로.
#  logging.md §1 assign 이벤트: role="code-review", issue=<issue-num>, task_id=<task_id>, provider=$reviewer_provider,
#    model=$reviewer_model, effort=$reviewer_effort, advisor=${reviewer_advisor:-}, terminal=<review-handle>,
```

New:

```bash
orca orchestration dispatch --task <task_id> --to <review-handle> --inject --json
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43): 15초 뒤 재-read해서
# tail이 그대로면 Enter만 재전송, 그래도 그대로면 spawn-failures.md로.
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로.
#  logging.md §1 assign 이벤트: role="code-review", issue=<issue-num>, task_id=<task_id>, provider=$reviewer_provider,
#    model=$reviewer_model, effort=$reviewer_effort, advisor=${reviewer_advisor:-}, terminal=<review-handle>,
```

- [ ] **Step 3: Run the scoped test to verify it now passes**

Run: `uvx pytest tests/test_orca_skills.py -q -k "test_dispatch_sites_are_followed_by_dispatch_verify_pointer and orca-evaluate"`

Expected: `1 passed` (this parametrization checks §1 and §3, and confirms §0 stays excluded, in one
assertion loop).

Run: `uvx pytest tests/test_orca_skills.py -q -k "test_dispatch_site_count_and_section0_exception_shape or test_orca_terminal_read_counts_per_skill_file"`

Expected: `2 passed` — confirms the total dispatch-site count (6) and the §0 exclusion (1) are unchanged,
and `orca-evaluate`'s literal `orca terminal read` count stays at 1.

- [ ] **Step 4: Commit**

```bash
git add skills/orca-evaluate/SKILL.md
git commit -m "$(cat <<'EOF'
fix(orca-evaluate): add dispatch-verify pointers at owned dispatch sites (#43)

Detect dispatch --inject text that lands unsent at the
contract-review and code-review dispatch sites. The §0
evaluate-session launch site is intentionally left untouched — it
duplicates orca-workflow's own dispatch, already covered.
EOF
)"
```

---

### Task 5: Add the new `spawn-failures.md` row

**Files:**
- Modify: `orca-workflows/spawn-failures.md`
- Modify: `tests/test_orca_skills.py`

**Interfaces:**
- Consumes: `orca-workflows/dispatch-verify.md` (Task 1) by filename reference, for the row's `fix` column.

- [ ] **Step 1: Write the failing test**

Append to the end of `tests/test_orca_skills.py`:

```python


def test_spawn_failures_has_dispatch_inject_unsent_row():
    """issue #43's failure mode has no literal terminal-output substring to grep — it's an
    absence of change, not a string. This pins that the new row exists, points at
    dispatch-verify.md for the fix, and is explicitly flagged as a log-based exception to the
    table's normal literal-substring convention (so a future reader isn't confused about why
    this row doesn't look like the others)."""
    text = _read_workflows_file("spawn-failures.md")
    assert "#43" in text, "must link the new row to issue #43"
    assert "dispatch-verify.md" in text, "the row's fix column must point at the new procedure"
    assert "log-based" in text, (
        "must explicitly flag this row as an exception to the literal-grep-substring convention"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uvx pytest tests/test_orca_skills.py -q -k "test_spawn_failures_has_dispatch_inject_unsent_row"`

Expected: `1 failed` (`AssertionError` on `"#43" in text`).

- [ ] **Step 3: Add the exception note and the new row**

Old (`orca-workflows/spawn-failures.md`, "Adding a new row" section, currently the last two lines of the
file):

```markdown
## Adding a new row

Keep `failure_signature` a short, literal substring that would actually appear in `terminal read` output —
not a paraphrase, or grep won't find it next time. Link the GitHub issue number rather than re-explaining
the cause here; this table maps symptom → issue, it doesn't replace the issue body.
```

New:

```markdown
## Adding a new row

Keep `failure_signature` a short, literal substring that would actually appear in `terminal read` output —
not a paraphrase, or grep won't find it next time. Link the GitHub issue number rather than re-explaining
the cause here; this table maps symptom → issue, it doesn't replace the issue body.

**Exception (log-based signatures):** issue #43's row below has no literal terminal-output substring — its
failure is an *absence* of change, not a string. Its signature is instead checked with `jq` against a
terminal's own `term-<handle>.jsonl` (see `logging.md` §2). Use a log-based signature only when a failure
genuinely has no literal substring; default to the literal-substring form whenever one exists.

| `failure_signature` (grep substring) | root cause | fix | known_issue |
|---|---|---|---|
| *(log-based, not literal terminal text)* — in a terminal's `term-<handle>.jsonl`, two consecutive `recv` events with identical `content`, or a `sent` event with no `recv` after it for an unusually long span | `dispatch --inject`'s text-injection and Enter-confirmation are not atomic from the caller's side — one can complete while the other silently does not, and a single `terminal read` cannot distinguish the resulting stuck state from normal post-completion idle | `~/.agents/orca-workflows/dispatch-verify.md` procedure — bounded tail-diff immediately after dispatch, single Enter-only retry, escalate here only if still static | #43 |
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uvx pytest tests/test_orca_skills.py -q -k "test_spawn_failures_has_dispatch_inject_unsent_row"`

Expected: `1 passed`.

Also re-run the pre-existing content check to confirm the new row didn't break JSON-encoding conventions
elsewhere in the file:

Run: `uvx pytest tests/test_orca_skills.py -q -k "test_spawn_failure_log_uses_json_encoder"`

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add orca-workflows/spawn-failures.md tests/test_orca_skills.py
git commit -m "$(cat <<'EOF'
docs(orca-workflows): add spawn-failures.md row for issue #43

Log-based signature (term-<handle>.jsonl recv comparison) since
this failure — dispatch --inject landing unsent — has no literal
terminal-output substring to grep, unlike every other row in this
table. Explicitly documented as an exception.
EOF
)"
```

---

### Task 6: Cross-file validation sweep

**Files:**
- No new modifications — read-only verification across Tasks 1-5's output.

**Interfaces:**
- Consumes: the final state of all files touched in Tasks 1-5.

- [ ] **Step 1: Run the full structural test suite**

Run: `uvx pytest tests/test_orca_skills.py -q`

Expected: `2 failed, <N> passed`, where the 2 failures are exactly the pre-existing
`test_orca_evaluate_review_model_selection_is_dynamic_not_fixed_high_risk` and
`test_orca_evaluate_preserves_evaluator_separation_intent` (see Global Constraints), and `<N>` includes
every new test added in Tasks 1-5. If any other test fails, fix the underlying file before proceeding — do
not treat any additional failure as pre-existing without checking it against a clean `git stash` baseline
first.

- [ ] **Step 2: Grep-confirm no dispatch site was missed**

```bash
for f in skills/orca-task-runner/SKILL.md skills/orca-workflow/SKILL.md skills/orca-evaluate/SKILL.md; do
  echo "== $f =="
  awk '/dispatch --task.*--inject/{print NR": "$0}' "$f"
done
```

Manually confirm each printed line's surrounding fenced code block also contains a `dispatch-verify.md`
pointer comment, except `orca-evaluate`'s §0 block (the one intentionally-unowned duplicate — confirm it
still lacks both the `logging.md` and `dispatch-verify.md` pointers, on purpose).

- [ ] **Step 3: `bash -n` syntax-check `dispatch-verify.md`'s bash block**

```bash
awk '/^```bash/{flag=1; block=""; next} /^```/{if(flag){print block > "/tmp/_blk.sh"; close("/tmp/_blk.sh"); system("bash -n /tmp/_blk.sh || echo FAILED")}; flag=0} flag{block = block $0 "\n"}' orca-workflows/dispatch-verify.md
```

Expected: no `FAILED` output (the one bash block uses `<handle>`/`<task_id>` placeholders only inside
strings/arguments, not in positions that would be a real shell syntax error).

- [ ] **Step 4: Report validation results to the user**

Summarize pass/fail for Steps 1-3. If any step fails, fix the underlying file (return to the relevant Task
1-5 step) before considering this plan complete — do not commit a "fix" as part of this validation task;
re-open the task whose file needed the correction.
