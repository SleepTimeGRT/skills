# orca-workflow §2a Round-2+ Relay: `worker-start --worktree active` → `current` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Issue:** #75 — `skills/orca-workflow/SKILL.md` §2a's round-2+ contract-negotiation relay calls
`orca orchestration worker-start --task <t> --worktree active --terminal <기존 handle> ...` to re-engage
an already-existing terminal. Live reproduction (2x — one `orca-task-runner` re-engage, one
`orca-evaluate` re-engage) shows this fails with `selector_not_found` ("Run this command inside a
live Orca terminal"); swapping only `--worktree active` → `--worktree current` (every other arg
identical) succeeds. `worker-start --help` documents `active`/`current` side by side as if
interchangeable — they are not, for this call shape.

**Goal:** The round-2+ relay's `worker-start` example uses `--worktree current`, and a structural
test pins that this specific site never regresses back to `active`.

**Root cause (why only this one site, not the other three `--worktree active` occurrences in the
same file):** the three `orca terminal create --worktree active` calls (§1d retro, §2a round-1
task-runner, §2a round-1 evaluator — lines 92/130/157) spawn a **brand-new** terminal; `active`
there is confirmed working by the issue's own repro step 1 ("새 터미널 생성 시엔 `active`가 정상
동작"). The one broken site (line 205) is the only place in this file that calls `worker-start`
against a terminal that **already exists**, addressed via `--terminal <handle>` rather than being
freshly created in the same call. That's the exact shape the issue reproduced as broken.

## Global Constraints

- Single-line value swap in `skills/orca-workflow/SKILL.md` — no restructuring of §2a, no change
  to `orca_call_with_retry` wrapping, no change to the `log_dispatch` call that follows.
- Do not touch the three `terminal create --worktree active` sites (lines 92, 130, 157) — the issue's
  own repro confirms `active` is correct for those (new-terminal creation, not re-engage).
- Do not touch `skills/orca-task-runner/SKILL.md` or `skills/orca-evaluate/SKILL.md`. The issue's
  "제안하는 수정" section marks checking those files as optional/선택, and this issue's Acceptance
  Criteria names only `skills/orca-workflow/SKILL.md` and `tests/test_orca_skills.py`. **Note for the
  record (not in scope here):** `skills/orca-task-runner/SKILL.md` §5 (line 168) has a
  `worker-start --task <task_id> --worktree active --terminal <impl_handle> ...` call with the same
  "targets an existing/pre-created terminal via `--terminal`" shape as the broken site — plausibly
  the same underlying bug, unverified live. Flagging so it isn't lost; a separate issue should cover
  it if confirmed, since fixing it here would exceed this issue's AC.
- Do not add or remove any `orca_call_with_retry` invocation — the swap happens on the same
  already-wrapped multi-line call, so `EXPECTED_RETRY_WRAP_COUNTS["orca-workflow"]` (currently 12,
  `tests/test_orca_skills.py` line ~725) stays unchanged.
- Do not register a new `spawn-failures.md` known-signature row — the issue's own "제안하는 수정"
  section marks this as conditional on further judgment ("신규 스폰이 아니라 재-engage 상황에서만
  발생하는 조건부 실패라 판단 필요"), and it isn't in the Acceptance Criteria.

---

## File Structure

- Modify: `skills/orca-workflow/SKILL.md` — §2a round-2+ relay, the `worker-start` call (1 line).
- Modify: `tests/test_orca_skills.py` — one new structural test scoped to that call.

---

### Task 1: Swap `--worktree active` → `--worktree current` in the round-2+ `worker-start` call

**Files:**
- Modify: `skills/orca-workflow/SKILL.md` (§2a round-2+ relay code block, currently line 205)
- Test: `tests/test_orca_skills.py`

**Interfaces:**
- No function/schema interface — this is a literal-text fix inside a documented CLI invocation
  example. The "interface" is the exact substring `--worktree current` appearing inside the
  `worker-start --task ... --json` call within the round-2+ section, which Task 1's test pins.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orca_skills.py`, directly after `test_orca_workflow_round2_uses_worker_start_not_raw_dispatch`
(currently ends at line 776, right before `test_orca_workflow_creates_own_run_in_section0`):

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_orca_skills.py::test_orca_workflow_round2_relay_worker_start_uses_worktree_current -v`
Expected: FAIL (`--worktree active` still present in the round-2+ `worker-start` call at line 205).

- [ ] **Step 3: Edit `skills/orca-workflow/SKILL.md`**

In the round-2+ relay code block (currently lines 193-217), change:

```bash
orca_call_with_retry "orca-workflow" "contract-round" -- \
  orca orchestration worker-start --task <방금 만든 task_id> --worktree active \
  --terminal <재-engage 대상 handle> --run "$RUN_ID" --from <자기 handle> --json
```

to:

```bash
orca_call_with_retry "orca-workflow" "contract-round" -- \
  orca orchestration worker-start --task <방금 만든 task_id> --worktree current \
  --terminal <재-engage 대상 handle> --run "$RUN_ID" --from <자기 handle> --json
```

(Only the `active` → `current` token changes; the line-continuation backslash, all other flags, and
every surrounding line are untouched.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_orca_skills.py::test_orca_workflow_round2_relay_worker_start_uses_worktree_current -v`
Expected: PASS

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `python3 -m pytest tests/test_orca_skills.py -v`
Expected: all passing (same count as before + 1). In particular confirm unchanged:
`test_orca_call_with_retry_count_per_skill[orca-workflow-12]`,
`test_no_bare_wrapped_call_sites[orca-workflow]`,
`test_orca_workflow_round2_uses_worker_start_not_raw_dispatch`,
`test_orca_workflow_documents_round2_relay_protocol`.

- [ ] **Step 6: Commit**

```bash
git add skills/orca-workflow/SKILL.md tests/test_orca_skills.py
git commit -m "fix(orca-workflow): round-2+ relay worker-start uses --worktree current, not active

Re-engaging an existing terminal via worker-start --terminal <handle>
fails with selector_not_found when --worktree is active; only current
works (verified live, 2x reproduction). The three fresh terminal-create
sites elsewhere in this file are unaffected and stay on active.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Verification Plan (maps to issue #75 Acceptance Criteria)

- AC1 (`skills/orca-workflow/SKILL.md` §2a round-2+ `worker-start` example uses `--worktree current`)
  → Task 1 Step 3, directly verified by Task 1 Step 4's test.
- AC2 (`tests/test_orca_skills.py` structural assertion that this site doesn't use `--worktree active`
  in a re-engage context) → Task 1 Step 1's new test, which scopes to the round-2+ section specifically
  (not a file-wide string ban) so it can't spuriously fail against the three legitimate
  `terminal create --worktree active` sites.

## Existing tests expected to go red

None. This is a same-shape literal-value swap inside an already-wrapped, already-tested call; no
existing assertion in `tests/test_orca_skills.py` currently pins the value `active` at this site
(confirmed: `grep -n "worktree active\|worktree current" tests/test_orca_skills.py` returns no
hits before this change).

## Destructive operations

None. This plan touches only two prose/test files in this skills repo; no schema, migration, or
data-affecting change.

## Self-Review Notes

- **Scope match:** both AC checkboxes map 1:1 to Task 1's two file edits; nothing else in the
  issue's "제안하는 수정" section (optional task-runner/evaluate check, optional spawn-failures.md
  registration) is in the AC, so both are called out as explicitly out of scope above rather than
  silently done or silently ignored.
- **Placeholder scan:** no TBD/TODO; the exact before/after code block is literal.
- **Blast radius:** confirmed via grep that no other test or skill file references `--worktree active`
  at this call site, so the swap can't silently break an unrelated assertion.
