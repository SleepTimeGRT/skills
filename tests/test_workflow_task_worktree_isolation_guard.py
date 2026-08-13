"""Doc-schema coverage for issue #180's coordinator worktree guard.

`orca-workflow-task`'s own coordinator session had no worktree isolation check at all: every
downstream `terminal create --worktree active`/`current` call in §1 resolves against *this
session's own cwd* -- confirmed live (2026-08-13) two ways: (a) calling `orca terminal create
--worktree active` from the main checkout with no prior worktree creation resolves straight to
main; (b) calling it again from inside a plain `git worktree add`-created directory fails outright
with `selector_not_found`, because that directory was never registered with Orca. Only a worktree
made via `orca worktree create` is resolvable by `--worktree active`/`current` afterward -- verified
live by creating one, `cd`-ing into it, and confirming `--worktree active` from there returns that
same worktree's id. This is why the guard uses `orca worktree create`/`show` (Orca's own tracked
mechanism) rather than raw `git worktree add` the way `orca-task-runner`'s sibling guard (issue
#136) does -- that sibling's mechanism does not register with Orca and would leave every downstream
`--worktree active` call in §1 unable to resolve at all.

Two follow-up findings from an advisor review, both confirmed live before being written into the
guard: (1) the `name:` selector is scoped to the calling session's repo context, not global --
querying `name:text-autosize-group` (a worktree that genuinely exists and is tracked in a sibling
repo, `vprop`) from within this repo's checkout still returns `selector_not_found`, so
`task-<issue-number>` cannot collide across repos. (2) `--activate` is unnecessary for downstream
`--worktree active` resolution -- a worktree created *without* `--activate`, then `cd`-ed into,
still resolves correctly -- and it has a UI side effect (changing Orca's displayed "active"
worktree) with no functional benefit here, so the guard omits it. Also, the create call's `ok`
field is now checked before reading `.result.worktree.path`: an unchecked failure would previously
have produced `task_worktree=null` and `cd null`.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "orca-workflow-task" / "SKILL.md"
GUARD_START = "- **격리 가드(issue #180)**"


def _guard_window(text: str) -> str:
    start = text.index(GUARD_START)
    end = text.index("- CLI 기반 coordinator(Codex/agy)는 launch 시", start)
    return text[start:end]


def test_isolation_guard_present_before_the_cli_coordinator_bullet():
    text = SKILL.read_text()
    assert GUARD_START in text
    window = _guard_window(text)
    assert "orca worktree create" in window
    assert "orca worktree show" in window
    assert "cd " in window


def _extract_guard_snippet(text: str) -> str:
    window = _guard_window(text)
    start = window.index("source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh")
    end = window.index("```", start)
    return window[start:end]


def test_guard_snippet_is_syntactically_valid_shell():
    text = SKILL.read_text()
    snippet = _extract_guard_snippet(text)
    # placeholders (<...>) make this non-executable as-is; just check shell syntax with -n.
    result = subprocess.run(["bash", "-n", "-c", snippet], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    # doesn't regress to raw git worktree manipulation, which Orca can't resolve `active` against
    assert "git worktree add" not in snippet


def test_guard_does_not_hardcode_a_default_branch():
    text = SKILL.read_text()
    snippet = _extract_guard_snippet(text)
    # --base-branch is omitted deliberately so Orca resolves the repo's actual default branch
    # instead of assuming `main` (issue #180 review: not every repo's default is `main`, e.g. the
    # live `vprop` repo tracked `develop`).
    assert "--base-branch" not in snippet
    assert "origin/main" not in snippet


def test_guard_omits_activate_flag():
    text = SKILL.read_text()
    snippet = _extract_guard_snippet(text)
    # --activate has a UI side effect (switching Orca's displayed "active" worktree) and was
    # confirmed live to be unnecessary for downstream --worktree active resolution (cd alone
    # suffices) -- dropping it avoids an unrequested effect on every afk task run too.
    assert "--activate" not in snippet


def test_guard_checks_create_ok_before_reading_path():
    text = SKILL.read_text()
    snippet = _extract_guard_snippet(text)
    # an unchecked `orca worktree create` failure previously would have produced
    # task_worktree=null and `cd null` -- the guard must fail closed instead. Pin the
    # create-branch check specifically (not just the pre-existing show-branch check on
    # `$existing`, which alone wouldn't catch a regression here).
    assert 'if ! printf \'%s\' "$created" | jq -e \'.ok\'' in snippet
    assert "exit 1" in snippet
    window = _guard_window(text)
    assert "spawn-failures.md" in window


def test_guard_explains_name_selector_is_repo_scoped():
    window = _guard_window(SKILL.read_text())
    assert "vprop" in window
    assert "selector_not_found" in window


def test_guard_is_idempotent_across_resume_via_orca_worktree_show():
    text = SKILL.read_text()
    window = _guard_window(text)
    assert 'orca worktree show --worktree "name:$task_branch"' in window
    assert "재개" in window


def test_guard_wires_task_branch_into_section4_pr_lookup():
    text = SKILL.read_text()
    assert "§0 격리 가드(issue #180)가 계산한" in text
    assert "<task-branch>" in text


def test_guard_references_the_actual_incident_and_leaves_task_runner_guard_alone():
    text = SKILL.read_text()
    window = _guard_window(text)
    assert "issue #180" in window
    assert "issue #136" in window
    assert "안전망으로 남는다" in window
    # the task-runner sibling's own guard section is untouched by this change
    task_runner_skill = REPO_ROOT / "skills" / "orca-task-runner" / "SKILL.md"
    assert "- **격리 가드(issue #136)**" in task_runner_skill.read_text()


def test_mode_bullet_no_longer_claims_section1_is_mode_invariant():
    text = SKILL.read_text()
    assert "§1~§4의\n  동작은 mode와 무관하게 동일하다" not in text
    assert "§1~§4의 동작은 mode와 무관하게 동일하다" not in text
    assert "issue #180" in text
