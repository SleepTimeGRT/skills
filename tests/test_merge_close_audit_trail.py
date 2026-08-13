"""Doc-schema regression coverage for issue #115's post-merge close/audit-trail fixes.

MediCount#540: a coordinator deliberately left the auto-close keyword out of the PR body (the
AC could only be verified after prod deploy), but the branch had a single commit whose message
carried a stray `Closes #540` trailer -- `gh pr merge --squash` inherited that trailer as the
squash commit message (since neither --subject nor --body was passed), and the issue auto-closed
two seconds after merge. The `is_open` guard before `close_issue` then produced a false no-op
(the issue looked already-closed), so the "Merged via PR #541" audit comment was never posted --
this is *also* true of the ordinary GitHub happy path, since `link_pr_for_close`'s body keyword
usually auto-closes the issue at merge time before the guard is even checked.

Items 2/3/4 from the issue (item 1 -- a real deferred-close routing branch -- is deferred, see
issue #115's tracker comment):

  2. `orca-workflow-task` SKILL.md §4 must pin the squash commit message to the PR's own
     title/body via --subject/--body, closing the second auto-close channel.
  3. `orca-workflows/issue-trackers/github.md` must document that channel next to
     `link_pr_for_close`.
  4. §4 must not silently no-op when `is_open` is already false at merge time -- it must fall
     back to `add_comment` so the audit trail survives regardless of which channel closed the
     issue. `add_comment` itself must exist as an adapter operation (github.md and jira.md).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "orca-workflow-task" / "SKILL.md"
GITHUB_ADAPTER = REPO_ROOT / "orca-workflows" / "issue-trackers" / "github.md"
JIRA_ADAPTER = REPO_ROOT / "orca-workflows" / "issue-trackers" / "jira.md"


def _routing_window() -> str:
    text = SKILL.read_text()
    start = text.index("## 4. 라우팅")
    end = text.index("- FAIL →", start)
    return text[start:end]


def test_routing_window_documents_the_is_open_false_fallback_to_add_comment():
    window = _routing_window()
    close_idx = window.index('`close_issue(task-issue-num, "Merged via PR #$pr_num")`를 호출')
    fallback_idx = window.index("`is_open`이 이미 false면")
    add_comment_idx = window.index(
        '`add_comment(task-issue-num, "Merged via PR #$pr_num")`를 호출', fallback_idx
    )
    # the false-branch documentation must come after the true-branch, and must actually call
    # add_comment with the same note the true-branch would have used with close_issue.
    assert close_idx < fallback_idx < add_comment_idx
    assert "issue #115" in window


def test_add_comment_referenced_as_state_preserving_unlike_close_issue():
    window = _routing_window()
    fallback = window[window.index("`is_open`이 이미 false면"):]
    assert "add_comment" in fallback
    assert "상태를 건드리지" in fallback or "상태를" in fallback


def test_merge_block_pins_subject_and_body_before_the_merge_loop():
    text = SKILL.read_text()
    comment_start = text.index("# 스쿼시 커밋 메시지를 이 스킬이 소유한다")
    title_assign = text.index('pr_title="$(gh pr view', comment_start)
    loop_start = text.index("merge_started_file=", title_assign)
    merge_call = text.index('gh pr merge "$pr_num"', loop_start)
    prelude = text[title_assign:loop_start]

    assert 'pr_title="$(gh pr view "$pr_num" --json title -q .title)"' in prelude
    assert 'pr_body="$(gh pr view "$pr_num" --json body -q .body)"' in prelude
    assert comment_start < title_assign < loop_start < merge_call

    call_line = text[merge_call : text.index("\n", merge_call)]
    assert '--subject "$pr_title"' in call_line
    assert '--body "$pr_body"' in call_line


def test_merge_block_references_issue_115_second_channel_rationale():
    text = SKILL.read_text()
    comment_start = text.index("# 스쿼시 커밋 메시지를 이 스킬이 소유한다")
    loop_start = text.index("merge_started_file=", comment_start)
    prelude = text[comment_start:loop_start]
    assert "issue #115" in prelude
    assert "Closes #N" in prelude
    assert "issue-trackers/github.md" in prelude


def test_github_adapter_defines_add_comment_operation():
    text = GITHUB_ADAPTER.read_text()
    assert "## `add_comment(id, note)`" in text
    add_comment_start = text.index("## `add_comment(id, note)`")
    add_comment_end = text.index("## `link_pr_for_close", add_comment_start)
    block = text[add_comment_start:add_comment_end]
    assert "gh issue comment <id> --body" in block
    assert "close_issue" in block  # documents the distinction from close_issue


def test_jira_adapter_defines_add_comment_operation():
    text = JIRA_ADAPTER.read_text()
    assert "## `add_comment(id, note)`" in text
    add_comment_start = text.index("## `add_comment(id, note)`")
    add_comment_end = text.index("## `find_regressions", add_comment_start)
    block = text[add_comment_start:add_comment_end]
    assert "addCommentToJiraIssue(cloudId, issueIdOrKey=id, comment=note)" in block


def test_github_adapter_documents_the_squash_commit_message_channel():
    text = GITHUB_ADAPTER.read_text()
    link_start = text.index("## `link_pr_for_close(pr_number, id)`")
    window = text[link_start : link_start + 2000]
    assert "issue #115" in window
    assert "커밋이 1개뿐인 PR" in window
    assert "--subject" in window and "--body" in window
